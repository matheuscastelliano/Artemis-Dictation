"""Implementacoes especificas de Linux (Wayland e X11).

Reune o que no Windows mora em output_win.py, startup_win.py e nos poucos
pontos Win32 de __main__.py e app.py. Os modulos output.py e startup.py sao
shims que escolhem entre este arquivo e os _win pelo sys.platform.

Por que nada aqui usa pynput, ao contrario do Windows:
  - Listener: no Linux o pynput so tem backend X11 (bisbilhota o servidor via
    XRecord). Sob Wayland o compositor so entrega ao XWayland os eventos
    destinados a janelas X, entao com um app Wayland nativo em foco o listener
    nao recebe nada. Quem cuida disso e o backend evdev em hotkeys.py.
  - Controller: injetar Ctrl+V por XTEST tem o mesmo problema. A injecao aqui
    vai por /dev/uinput, que entra abaixo do compositor e por isso funciona em
    Wayland, X11, GNOME e KDE igual. (wtype foi descartado: usa o protocolo
    zwp_virtual_keyboard_v1, que o mutter nao implementa para clientes comuns.)

Foco de janela nao existe neste arquivo de proposito: o Wayland esconde qual
janela esta em foco. Nao e uma limitacao pratica porque o Artemis nunca rouba
o foco - o overlay e override-redirect e o tray nao ativa janela.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

from .errors import ArtemisError, OutputError
from .i18n import t

log = logging.getLogger(__name__)


# --------------------------------------------------------------- clipboard

def _wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _clipboard_tool() -> tuple[list[str], list[str]] | None:
    """(comando de copiar, comando de colar) conforme a sessao e o que existe."""
    if _wayland() and shutil.which("wl-copy") and shutil.which("wl-paste"):
        return (["wl-copy"], ["wl-paste", "--no-newline"])
    if shutil.which("xclip"):
        return (
            ["xclip", "-selection", "clipboard"],
            ["xclip", "-selection", "clipboard", "-o"],
        )
    if shutil.which("xsel"):
        return (["xsel", "--clipboard", "--input"], ["xsel", "--clipboard", "--output"])
    return None


def copy(text: str, attempts: int = 3) -> None:
    """Escreve no clipboard. Falhar aqui perde o ditado, entao tem retry."""
    tool = _clipboard_tool()
    if tool is None:
        raise OutputError(t("err.clipboard"), "wl-clipboard/xclip/xsel nao instalado")

    last: Exception | None = None
    for attempt in range(attempts):
        try:
            # wl-copy se destaca sozinho para servir a selecao; nao segura o run().
            subprocess.run(
                tool[0], input=text.encode("utf-8"), check=True, timeout=5
            )
            return
        except Exception as exc:
            last = exc
            time.sleep(0.05 * (attempt + 1))
    raise OutputError(t("err.clipboard"), str(last))


def read_clipboard() -> str | None:
    tool = _clipboard_tool()
    if tool is None:
        return None
    try:
        done = subprocess.run(tool[1], capture_output=True, timeout=5)
        if done.returncode != 0:
            return None  # clipboard vazio ou conteudo nao-texto
        return done.stdout.decode("utf-8")
    except Exception:
        return None


# ------------------------------------------------------------------- foco

def foreground_window():
    """Sempre None: o Wayland nao expoe a janela em foco. Ver docstring do modulo."""
    return None


def restore_focus(hwnd) -> bool:
    """No-op. O Artemis nunca tira o foco de ninguem, entao nao ha o que restaurar."""
    return False


# -------------------------------------------------------------- injecao

_uinput = None
_uinput_failed = False


def _get_uinput():
    """Teclado virtual via /dev/uinput, criado uma vez e mantido vivo.

    Criado sob demanda e nao no import porque nem toda invocacao do Artemis
    injeta tecla (--devices, --set-key). Mantido vivo depois de criado porque
    o compositor leva um instante para reconhecer um dispositivo novo: recriar
    a cada colagem perderia a primeira tecla de cada vez.
    """
    global _uinput, _uinput_failed
    if _uinput is not None:
        return _uinput
    if _uinput_failed:
        raise OutputError(t("err.paste"), "sem acesso a /dev/uinput")

    try:
        from evdev import UInput, ecodes
    except ImportError as exc:
        _uinput_failed = True
        raise OutputError(t("err.paste"), "python3-evdev nao instalado") from exc

    try:
        device = UInput(
            {ecodes.EV_KEY: [ecodes.KEY_LEFTCTRL, ecodes.KEY_V]},
            name="Artemis Dictation virtual keyboard",
        )
    except Exception as exc:
        _uinput_failed = True
        raise OutputError(
            t("err.paste"),
            f"nao consegui abrir /dev/uinput ({exc}). "
            "Verifique a regra udev e se voce esta no grupo 'input'.",
        ) from exc

    time.sleep(0.3)  # deixa o compositor registrar o dispositivo novo
    _uinput = device
    return device


def send_paste() -> None:
    """Injeta Ctrl+V por /dev/uinput."""
    from evdev import ecodes

    device = _get_uinput()
    try:
        device.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
        device.syn()
        device.write(ecodes.EV_KEY, ecodes.KEY_V, 1)
        device.syn()
        device.write(ecodes.EV_KEY, ecodes.KEY_V, 0)
        device.syn()
        device.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)
        device.syn()
    except Exception as exc:
        raise OutputError(t("err.paste"), t("err.paste.detail", error=exc)) from exc


def deliver(
    text: str,
    hwnd=None,
    *,
    wait_modifiers=None,
    restore_previous: bool = False,
) -> bool:
    """Copia e cola o texto. Mesmo contrato do output_win.deliver.

    True = o Ctrl+V foi injetado (nao que algum campo recebeu o texto).
    False = "esta no clipboard, cole voce mesmo" - nunca significa ditado
    perdido. Por isso so o copy() levanta excecao aqui.
    """
    previous = read_clipboard() if restore_previous else None

    copy(text)  # se isto falhar, o ditado precisa ser refeito: propaga

    if wait_modifiers is not None and not wait_modifiers():
        log.warning("Modificadores ainda pressionados; nao vou injetar Ctrl+V.")
        return False

    try:
        send_paste()
    except OutputError as exc:
        log.warning("Colagem falhou, texto segue no clipboard: %s", exc)
        return False

    if previous is not None and previous != text:
        time.sleep(0.35)  # deixa o alvo ler o nosso texto antes de devolver
        try:
            copy(previous)
        except Exception:
            pass  # perder o clipboard antigo e um incomodo, nao um erro
    return True


# -------------------------------------------------------------------- som

def beep(frequency: int, duration_ms: int = 70) -> None:
    """Bipe curto pelo sounddevice, que ja e dependencia (nao ha winsound aqui).

    Sintetiza um seno com fade de 5 ms nas pontas: sem o fade, o corte abrupto
    estala mais alto que o proprio bipe.
    """
    import sounddevice as sd

    rate = 44100
    total = int(rate * duration_ms / 1000)
    fade = int(rate * 0.005)
    samples = bytearray()
    for i in range(total):
        gain = 0.25
        if i < fade:
            gain *= i / fade
        elif i > total - fade:
            gain *= max(0, total - i) / fade
        value = int(32767 * gain * math.sin(2 * math.pi * frequency * i / rate))
        samples += struct.pack("<h", value)

    with sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16") as stream:
        stream.write(bytes(samples))


# ------------------------------------- instancia unica e comandos entre elas

_lock_socket = None

# Socket Unix no namespace abstrato (o \0 inicial). Vantagem sobre um arquivo
# de lock: o kernel libera o nome sozinho quando o processo morre, entao um
# crash nao deixa lock orfao travando a proxima execucao. Alem de garantir a
# instancia unica, ele e por onde a segunda invocacao pede alguma coisa a
# primeira - abrir as configuracoes, tipicamente.
_ADDRESS = "\0ArtemisDictation"


def claim_single_instance() -> bool:
    """False se ja houver um Artemis rodando."""
    global _lock_socket
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(_ADDRESS)
    except OSError:
        sock.close()
        return False
    sock.listen(4)
    _lock_socket = sock  # referencia viva pelo resto do processo: solta no exit
    return True


def serve_commands(handler) -> None:
    """Atende os pedidos de outras invocacoes do Artemis, numa thread.

    Sem isto, clicar no Artemis no menu de aplicativos com o app ja rodando
    nao faria nada visivel - e, sem icone na bandeja, nao haveria como chegar
    nas configuracoes.
    """
    sock = _lock_socket
    if sock is None:
        return

    def loop() -> None:
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return  # socket fechado: o app esta encerrando
            try:
                with conn:
                    conn.settimeout(2)
                    command = conn.recv(64).decode("utf-8", "replace").strip()
            except OSError:
                continue
            if not command:
                continue
            try:
                handler(command)
            except Exception:
                log.exception("Erro ao tratar o comando '%s'", command)

    threading.Thread(target=loop, name="artemis-ipc", daemon=True).start()


def send_command(command: str, timeout: float = 2.0) -> bool:
    """Manda um comando para o Artemis que ja esta rodando."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(_ADDRESS)
        sock.sendall(command.encode("utf-8") + b"\n")
        return True
    except OSError:
        return False
    finally:
        sock.close()


# ------------------------------------------------------------ area de notificacao

def status_notifier_available() -> bool:
    """A sessao tem quem hospede um icone de bandeja?

    O GNOME nao implementa area de notificacao no proprio Shell: quem oferece
    o servico (org.kde.StatusNotifierWatcher, o protocolo que o AppIndicator
    fala) e a extensao AppIndicator. Sem ela no ar, o icone do Artemis nao
    aparece em lugar nenhum - e o usuario precisa saber disso, senao o app
    parece nao ter subido.
    """
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        answer = bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        return bool(answer.unpack()[0])
    except Exception:
        log.debug("Nao consegui consultar o StatusNotifierWatcher", exc_info=True)
        return True  # na duvida, nao alarma o usuario


def open_folder(path) -> None:
    subprocess.Popen(["xdg-open", str(path)])


# ------------------------------------------------- menu de aplicativos

DESKTOP_FILE = "artemis-dictation.desktop"
AUTOSTART_FILE = DESKTOP_FILE
ICON_NAME = "artemis-dictation"
# Os tamanhos que o GNOME procura para menu, dock e Alt-Tab.
ICON_SIZES = (48, 64, 128, 256)


def _data_home() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    return Path(base) if base else Path.home() / ".local" / "share"


def _autostart_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "autostart" / AUTOSTART_FILE


def _desktop_path() -> Path:
    return _data_home() / "applications" / DESKTOP_FILE


def _icon_path(size: int) -> Path:
    return (
        _data_home()
        / "icons"
        / "hicolor"
        / f"{size}x{size}"
        / "apps"
        / f"{ICON_NAME}.png"
    )


def install_icon() -> None:
    """Grava o icone do app no tema do usuario, num tamanho por resolucao."""
    from .ui.icon import COLORS, make_icon

    for size in ICON_SIZES:
        path = _icon_path(size)
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        make_icon(COLORS["idle"], size).save(path)


def _entry_text(*, autostart: bool) -> str:
    """O .desktop, igual para o menu e para a inicializacao automatica."""
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=Artemis Dictation",
        f"Comment={t('app.tagline')}",
        f"Exec={command()}",
        f"Icon={ICON_NAME}",
        "Terminal=false",
        "StartupNotify=false",
        "Categories=Utility;Accessibility;",
        f"Keywords={t('desktop.keywords')}",
    ]
    if autostart:
        lines.append("X-GNOME-Autostart-enabled=true")
    else:
        # Botao direito no icone do dock -> "Configuracoes".
        lines += [
            "Actions=settings;",
            "",
            "[Desktop Action settings]",
            f"Name={t('desktop.settings')}",
            f"Exec={command()} --settings",
        ]
    return "\n".join(lines) + "\n"


def install_desktop_entry() -> None:
    """Poe o Artemis no menu de aplicativos (e no dock, se o usuario fixar).

    E o unico caminho garantido ate o app: a bandeja do sistema depende de
    uma extensao do GNOME que pode nao estar no ar, e sem ela nao havia como
    abrir as configuracoes senao pelo terminal. Clicar aqui com o app ja
    rodando abre as configuracoes, via o socket de instancia unica.
    """
    try:
        install_icon()
        path = _desktop_path()
        text = _entry_text(autostart=False)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            log.info("Entrada no menu de aplicativos: %s", path)
            _refresh_desktop_database(path.parent)
    except OSError as exc:
        # Nao ter atalho no menu e um incomodo, nao um motivo para nao subir.
        log.warning("Nao consegui instalar a entrada no menu: %s", exc)


def _refresh_desktop_database(directory: Path) -> None:
    """Faz o GNOME reparar no .desktop novo sem esperar o proximo login."""
    if not shutil.which("update-desktop-database"):
        return
    try:
        subprocess.run(
            ["update-desktop-database", str(directory)], timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        pass


# --------------------------------------------------------------- autostart


def command() -> str:
    """Linha de comando que a sessao vai executar no login."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    # run.pyw insere a propria pasta no sys.path, entao roda de qualquer cwd -
    # que e o que importa aqui, porque .desktop nao define diretorio de trabalho.
    launcher = Path(__file__).resolve().parent.parent / "run.pyw"
    return f'"{Path(sys.executable)}" "{launcher}"'


def registered_command() -> str | None:
    path = _autostart_path()
    if not path.exists():
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("Exec="):
                return line[len("Exec="):].strip()
    except OSError:
        pass
    return None


def is_enabled() -> bool:
    return registered_command() is not None


def set_enabled(enabled: bool) -> None:
    path = _autostart_path()
    try:
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            install_icon()
            path.write_text(_entry_text(autostart=True), encoding="utf-8")
            log.info("Inicializacao automatica ligada: %s", path)
        else:
            path.unlink(missing_ok=True)
            log.info("Inicializacao automatica desligada.")
    except OSError as exc:
        raise ArtemisError(t("err.startup_write"), str(exc)) from exc


def sync(enabled: bool) -> None:
    """Aplica o valor do config, so escrevendo quando algo muda de fato."""
    if enabled == is_enabled():
        if enabled and registered_command() != command():
            set_enabled(True)  # mesmo estado, caminho antigo: corrige
        return
    set_enabled(enabled)
