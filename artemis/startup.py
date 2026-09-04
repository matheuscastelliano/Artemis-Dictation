"""Iniciar o Artemis junto com o Windows.

Usa a chave Run do usuario atual no registro:

    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run

E o mecanismo mais simples que existe para isso no Windows e, por ser HKCU e
nao HKLM, nao pede privilegio de administrador. A alternativa seria criar um
atalho .lnk em shell:startup, o que exigiria COM so para escrever um arquivo.

O comando registrado aponta para o run.pyw (e nao para `-m artemis`), porque
a chave Run nao define diretorio de trabalho e `-m` depende dele. O run.pyw
insere a propria pasta no sys.path, entao funciona de onde for chamado.
"""

from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path

from .errors import ArtemisError
from .i18n import t

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ArtemisDictation"


def command() -> str:
    """Linha de comando que o Windows vai executar no logon."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'  # empacotado com PyInstaller

    # Rodando do codigo: pythonw.exe (sem console) + run.pyw.
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = interpreter
    launcher = Path(__file__).resolve().parent.parent / "run.pyw"
    return f'"{pythonw}" "{launcher}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        log.debug("Nao consegui ler a chave Run", exc_info=True)
        return False


def registered_command() -> str | None:
    """O que esta registrado hoje, ou None. Util para a UI e para diagnostico."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value
    except (FileNotFoundError, OSError):
        return None


def set_enabled(enabled: bool) -> None:
    """Liga ou desliga a inicializacao automatica.

    Sempre reescreve o comando quando liga: se voce mover a pasta do projeto
    ou trocar de venv, marcar a opcao de novo conserta o caminho.
    """
    try:
        if enabled:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
            log.info("Inicializacao automatica ligada: %s", command())
        else:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, VALUE_NAME)
                log.info("Inicializacao automatica desligada.")
            except FileNotFoundError:
                pass  # ja nao estava registrado
    except OSError as exc:
        raise ArtemisError(t("err.startup_write"), str(exc)) from exc


def sync(enabled: bool) -> None:
    """Aplica o valor do config, sem escrever se ja estiver como se quer.

    Escrever no registro a cada save seria inofensivo, mas assim o registro
    so e tocado quando a opcao realmente muda.
    """
    if enabled == is_enabled():
        if enabled and registered_command() != command():
            set_enabled(True)  # mesmo estado, caminho antigo: corrige
        return
    set_enabled(enabled)
