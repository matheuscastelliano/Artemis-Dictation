"""Icone na bandeja do sistema.

pystray roda seu proprio message loop, entao vai para uma thread propria
(run_detached). O Tkinter fica com a main thread. Todo callback daqui que
mexa em UI precisa voltar para a main thread via root.after().
"""

from __future__ import annotations

import logging
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from ..hotkeys import describe

log = logging.getLogger(__name__)

_COLORS = {
    "idle": (120, 120, 128),
    "recording": (229, 72, 77),
    "processing": (245, 165, 36),
    "done": (48, 164, 108),
    "error": (229, 72, 77),
}

_LABELS = {
    "idle": "Pronto",
    "recording": "Gravando...",
    "processing": "Processando...",
    "done": "Pronto",
    "error": "Erro",
}


def _preview(text: str, limit: int = 64) -> str:
    """Uma linha do ditado, para caber num item de menu."""
    flat = " ".join(text.split())
    if len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    # No menu do Windows, "&" vira marcador de atalho e some da tela.
    return flat.replace("&", "&&")


def _make_icon(color: tuple[int, int, int], size: int = 64) -> Image.Image:
    """Um circulo cheio da cor do estado, com respiro nas bordas."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pad = 6
    draw.ellipse([pad, pad, size - pad, size - pad], fill=(*color, 255))
    return image


class Tray:
    def __init__(
        self,
        controller,
        *,
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self._controller = controller
        self._status_kind = "idle"
        self._status_text = "Pronto"
        self._icons = {kind: _make_icon(color) for kind, color in _COLORS.items()}

        self._on_settings = on_settings
        self._on_quit = on_quit

        # O menu inteiro e um callable: pystray o reavalia a cada abertura,
        # entao mudar presets.json e recarregar ja muda o menu.
        self._icon = pystray.Icon(
            "artemis",
            icon=self._icons["idle"],
            title="Artemis Dictation",
            menu=pystray.Menu(self._menu_items),
        )

    def _menu_items(self):
        yield pystray.MenuItem(self._status_text, None, enabled=False)
        yield pystray.Menu.SEPARATOR
        for preset in self._controller.presets:
            label = f"{preset.name}   ({describe(preset.hotkey)})"
            yield pystray.MenuItem(label, self._make_trigger(preset))
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Ultimos ditados", pystray.Menu(self._history_items))
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Configuracoes...", self._on_settings, default=True)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Sair", self._on_quit)

    def _make_trigger(self, preset):
        def handler(icon=None, item=None):
            self._controller.trigger(preset)

        return handler

    def _history_items(self):
        """Os ultimos ditados. Clicar num deles devolve o texto ao clipboard.

        Serve para o caso em que voce dita sem ter clicado num campo de
        texto: o Ctrl+V injetado nao encontra destino, mas o texto continua
        aqui. Fica so na memoria; nada e gravado em disco.
        """
        history = list(self._controller.history)
        if not history:
            yield pystray.MenuItem("(nenhum ainda)", None, enabled=False)
            return
        for text in history:
            yield pystray.MenuItem(_preview(text), self._make_recall(text))
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Limpar", lambda: self._controller.clear_history())

    def _make_recall(self, text):
        def handler(icon=None, item=None):
            self._controller.recall(text)

        return handler

    def run_detached(self) -> None:
        self._icon.run_detached()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass

    def set_status(self, kind: str, message: str = "", detail: str = "") -> None:
        self._status_kind = kind
        label = _LABELS.get(kind, "Pronto")
        self._status_text = f"{label} - {message}" if message else label

        try:
            self._icon.icon = self._icons.get(kind, self._icons["idle"])
            self._icon.title = f"Artemis - {self._status_text}"[:127]  # limite do Windows
            self._icon.update_menu()
        except Exception:
            log.debug("Nao consegui atualizar o icone da bandeja", exc_info=True)

    def notify(self, title: str, message: str) -> None:
        try:
            self._icon.notify(message, title)
        except Exception:
            log.debug("Notificacao nao suportada nesta plataforma", exc_info=True)
