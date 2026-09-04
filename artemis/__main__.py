"""Ponto de entrada do Artemis Dictation.

    python -m artemis              # roda o app (bandeja + atalhos globais)
    python -m artemis --set-key    # grava a API key no Windows (voce digita)
    python -m artemis --devices    # lista os microfones
    python -m artemis --debug      # log detalhado no console

Modelo de threads:
    main       -> Tkinter (overlay + janela de configuracao)
    tray       -> pystray, com seu proprio message loop
    hotkeys    -> hook de teclado do pynput
    artemis-0  -> chamadas de API (uma por vez)

Tudo que vem das outras threads entra na UI por root.after(0, ...).
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import subprocess
import sys
import tkinter as tk
from logging.handlers import RotatingFileHandler

from . import config as config_module
from . import i18n, secrets_store
from .app import AppController, Status
from .errors import ArtemisError
from .i18n import t
from .ui.overlay import Overlay
from .ui.settings_window import SettingsWindow
from .ui.tray import Tray

log = logging.getLogger("artemis")

_MUTEX_NAME = "Global\\ArtemisDictation.SingleInstance"
_ERROR_ALREADY_EXISTS = 183


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    try:
        log_path = config_module.config_dir() / "artemis.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path, maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root_logger.addHandler(file_handler)
    except Exception:
        pass  # sem log em arquivo o app ainda roda

    if debug or sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root_logger.addHandler(stream)


def claim_single_instance() -> bool:
    """False se ja houver um Artemis rodando.

    Dois hooks de teclado disputando o mesmo atalho geram gravacoes
    duplicadas e cobranca duplicada na API.
    """
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS
    except Exception:
        return True  # na duvida, deixa rodar


def cmd_set_key() -> int:
    """Grava a API key. A chave e digitada pelo usuario e nunca ecoa."""
    import getpass

    print("Cole a API key da OpenAI (nao aparece na tela) e tecle Enter.")
    print("Enter vazio cancela.\n")
    try:
        value = getpass.getpass("API key: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        return 130
    if not value:
        print("Cancelado, nada foi alterado.")
        return 1
    secrets_store.set_api_key(value)
    print(f"Salva no Gerenciador de Credenciais: {secrets_store.masked(value)}")
    return 0


def cmd_devices() -> int:
    from .audio import list_input_devices

    for device in list_input_devices():
        flag = t("cli.default_device") if device["default"] else ""
        print(f"[{device['index']}] {device['name']}{flag}")
    return 0


def open_config_folder() -> None:
    path = config_module.config_dir()
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except Exception:
        subprocess.Popen(["explorer", str(path)])


def run_app() -> int:
    root = tk.Tk()
    root.withdraw()
    root.title("Artemis Dictation")
    # Um erro dentro de um callback do Tk nao pode fechar a janela invisivel
    # que segura o app inteiro.
    root.report_callback_exception = lambda *args: log.exception(
        "Erro em callback do Tkinter", exc_info=args
    )

    overlay = Overlay(root)
    tray: Tray | None = None

    def apply_status(status: Status) -> None:
        """Roda sempre na main thread."""
        if tray is not None:
            tray.set_status(status.kind, status.message, status.detail)
        if _overlay_wanted(controller.config, status.kind):
            limit = int(controller.config.get("overlay_preview_chars", 120))
            overlay.show(
                status.kind,
                _title_for(status),
                _detail_for(status, limit),
                _duration_for(status, limit),
            )
        else:
            overlay.hide()

    def on_status(status: Status) -> None:
        """Chamado de qualquer thread; devolve o trabalho para a main."""
        try:
            root.after(0, apply_status, status)
        except RuntimeError:
            pass  # app ja esta fechando

    controller = AppController(on_status)
    settings = SettingsWindow(
        root,
        on_saved=controller.reload,
        on_reload=controller.reload,
        on_open_folder=open_config_folder,
    )

    def quit_app() -> None:
        log.info("Encerrando.")
        controller.shutdown()
        if tray is not None:
            tray.stop()
        try:
            root.quit()
        except Exception:
            pass

    tray = Tray(
        controller,
        on_settings=lambda: root.after(0, settings.open),
        on_quit=lambda: root.after(0, quit_app),
    )
    tray.run_detached()

    controller.start()
    log.info(
        "Artemis pronto. Modos: %s",
        ", ".join(f"{p.name} [{p.hotkey}]" for p in controller.presets),
    )

    if not secrets_store.get_api_key():
        root.after(400, settings.open)
        root.after(
            600,
            lambda: tray.notify(t("tray.tooltip"), t("tray.notify.no_key")),
        )

    try:
        root.mainloop()
    except KeyboardInterrupt:
        quit_app()
    return 0


def _overlay_wanted(config: dict, kind: str) -> bool:
    """O indicador flutuante deve aparecer para este estado?

    "idle" nunca aparece. Fora isso, quem manda e overlay_mode: "never"
    esconde tudo, "errors" deixa passar so os erros - o icone da bandeja
    continua mudando de cor nos tres casos.
    """
    if kind == "idle":
        return False
    mode = config.get("overlay_mode", "always")
    if mode == "never":
        return False
    if mode == "errors":
        return kind == "error"
    return True


def _title_for(status: Status) -> str:
    """Sempre a mensagem; quem monta o titulo e quem cria o Status."""
    if status.kind == "recording":
        return (
            t("status.recording_with", mode=status.message)
            if status.message
            else t("status.recording")
        )
    if status.kind == "processing":
        return (
            t("status.processing_with", mode=status.message)
            if status.message
            else t("status.processing")
        )
    if status.kind == "done":
        return status.message or t("status.done")
    return status.message or t("status.error")


def _detail_for(status: Status, limit: int) -> str:
    """A dica (quando ha) e, em 'done', uma previa do texto ditado.

    A previa serve para voce reconhecer o que saiu, nao para reler tudo - o
    texto inteiro esta no clipboard e em "Ultimos ditados". `limit` 0 desliga.
    """
    if not status.text or limit <= 0:
        return status.detail
    text = " ".join(status.text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    if not status.detail:
        return text
    return status.detail + "\n" + text


def _duration_for(status: Status, limit: int) -> int | None:
    """Previa maior fica na tela mais tempo, ate um teto de 6s."""
    if status.kind != "done" or not status.text or limit <= 0:
        return None
    shown = min(len(status.text), limit)
    return min(6000, 1800 + 18 * shown)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="artemis")
    parser.add_argument("--set-key", action="store_true", help="grava a API key da OpenAI")
    parser.add_argument("--devices", action="store_true", help="lista os microfones")
    parser.add_argument("--debug", action="store_true", help="log detalhado")
    args = parser.parse_args(argv)

    setup_logging(args.debug)

    # Le o config so para definir o idioma antes da primeira mensagem.
    # Se ele estiver quebrado, seguimos com o idioma do Windows.
    try:
        config_module.load_config()
    except ArtemisError:
        i18n.set_language(None)

    if args.set_key:
        return cmd_set_key()
    if args.devices:
        return cmd_devices()

    if not claim_single_instance():
        print(t("cli.already_running"))
        return 1

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
