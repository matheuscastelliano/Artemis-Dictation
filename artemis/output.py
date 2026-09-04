"""Entrega do texto na aplicacao ativa.

Estrategia: clipboard + Ctrl+V injetado. Avaliei UI Automation
(ValuePattern), mas ela nao funciona em Electron/Chromium nem em apps com
render proprio - justamente WhatsApp Web, Teams, Slack, Discord e VS Code,
que sao o caso de uso principal. Clipboard + Ctrl+V funciona em praticamente
todo campo de texto do Windows.

Se qualquer etapa da colagem falhar, o texto continua no clipboard: o
usuario so precisa apertar Ctrl+V. Nunca se perde um ditado.
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

import pyperclip
from pynput import keyboard

from .errors import OutputError
from .i18n import t

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_controller = keyboard.Controller()


def foreground_window():
    """HWND da janela em foco, para restaurar depois. None se falhar."""
    try:
        return _user32.GetForegroundWindow() or None
    except Exception:
        return None


def restore_focus(hwnd) -> bool:
    """Traz a janela de volta ao foco, se ela ja nao estiver.

    Normalmente e no-op: o Artemis nunca rouba o foco (o overlay usa
    WS_EX_NOACTIVATE e o tray nao ativa janela). So faz diferenca se o
    usuario trocou de janela durante o processamento.
    """
    if not hwnd or not _user32.IsWindow(hwnd):
        return False
    if _user32.GetForegroundWindow() == hwnd:
        return True

    # O Windows bloqueia SetForegroundWindow vindo de processo em background.
    # Anexar nossa fila de input a da janela alvo contorna a restricao.
    target_thread = _user32.GetWindowThreadProcessId(hwnd, None)
    our_thread = _kernel32.GetCurrentThreadId()
    attached = False
    try:
        if target_thread and target_thread != our_thread:
            attached = bool(_user32.AttachThreadInput(our_thread, target_thread, True))
        return bool(_user32.SetForegroundWindow(hwnd))
    except Exception as exc:
        log.warning("Nao consegui restaurar o foco: %s", exc)
        return False
    finally:
        if attached:
            _user32.AttachThreadInput(our_thread, target_thread, False)


def copy(text: str, attempts: int = 4) -> None:
    """Escreve no clipboard, com retry.

    O clipboard do Windows e um recurso global travavel: qualquer processo
    pode segura-lo por alguns milissegundos e fazer a escrita falhar.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            pyperclip.copy(text)
            return
        except Exception as exc:
            last = exc
            time.sleep(0.05 * (attempt + 1))
    raise OutputError(t("err.clipboard"), str(last))


def read_clipboard() -> str | None:
    try:
        return pyperclip.paste()
    except Exception:
        return None  # conteudo nao-texto (imagem, arquivo) ou clipboard travado


def send_paste() -> None:
    """Injeta Ctrl+V via SendInput (por baixo do pynput.Controller)."""
    try:
        with _controller.pressed(keyboard.Key.ctrl):
            _controller.press("v")
            _controller.release("v")
    except Exception as exc:
        raise OutputError(
            t("err.paste"), t("err.paste.detail", error=exc)
        ) from exc


def deliver(
    text: str,
    hwnd=None,
    *,
    wait_modifiers=None,
    restore_previous: bool = False,
) -> bool:
    """Copia e cola o texto. Retorna True se a colagem foi injetada.

    True significa apenas que o Ctrl+V foi injetado - nao que algum campo
    recebeu o texto. Se nao havia campo em foco, a tecla vai para o nada.
    Por isso `restore_previous` e False por padrao: devolver o clipboard
    antigo nessa situacao apagaria o ditado sem deixar rastro.

    False significa "o texto esta no clipboard, mas cole voce mesmo" - nunca
    significa que o ditado se perdeu.

    `wait_modifiers` e uma funcao que bloqueia ate o usuario soltar Ctrl/Alt.
    Sem ela, o Ctrl+V injetado se soma aos modificadores ainda pressionados
    (virando Ctrl+Alt+V) e a colagem nao acontece.
    """
    previous = read_clipboard() if restore_previous else None

    copy(text)  # se isto falhar, e OutputError e o ditado precisa ser refeito

    if wait_modifiers is not None and not wait_modifiers():
        log.warning("Modificadores ainda pressionados; nao vou injetar Ctrl+V.")
        return False

    restore_focus(hwnd)
    time.sleep(0.05)  # deixa o alvo processar a mudanca de foco

    try:
        send_paste()
    except OutputError:
        return False

    if previous is not None and previous != text:
        # Devolve o clipboard depois que o alvo ja leu o nosso texto.
        time.sleep(0.35)
        try:
            pyperclip.copy(previous)
        except Exception:
            pass  # perder o clipboard antigo e um incomodo, nao um erro
    return True
