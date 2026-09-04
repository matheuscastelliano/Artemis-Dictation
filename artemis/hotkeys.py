"""Hotkeys globais, com suporte a toggle e a push-to-talk.

Por que pynput e nao `keyboard` nem RegisterHotKey:
  - RegisterHotKey (Win32) so avisa quando a combinacao e ativada; nao ha
    evento de release, entao push-to-talk fica impossivel.
  - pynput instala um hook WH_KEYBOARD_LL e entrega press E release, que e
    exatamente o que falta.

Limitacao conhecida do WH_KEYBOARD_LL: ele nao recebe eventos enquanto a
janela em foco roda elevada (como admin) e o Artemis nao. Se voce usa o VS
Code ou um terminal como administrador, rode o Artemis elevado tambem.

O listener NAO suprime as teclas: a combinacao tambem chega na aplicacao em
foco. Escolha combinacoes que o app de destino ignore.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable

from pynput import keyboard

from .errors import HotkeyError

log = logging.getLogger(__name__)

# Chamado como on_event(binding_id, "activate" | "deactivate").
EventCallback = Callable[[str, str], None]


class _Binding:
    def __init__(self, binding_id: str, spec: str, trigger: str):
        self.id = binding_id
        self.spec = spec
        self.trigger = trigger
        try:
            self.keys = set(keyboard.HotKey.parse(spec))
        except ValueError as exc:
            raise HotkeyError(
                f"Atalho invalido: '{spec}'.",
                "Use o formato do pynput, ex: <ctrl>+<alt>+<space> ou <ctrl>+<alt>+1.",
            ) from exc
        if not self.keys:
            raise HotkeyError(f"Atalho vazio para '{binding_id}'.")
        self.active = False


class HotkeyManager:
    """Um unico hook para todos os atalhos."""

    def __init__(self, on_event: EventCallback):
        self._on_event = on_event
        self._bindings: list[_Binding] = []
        self._pressed: set = set()
        self._lock = threading.Lock()
        self._listener: keyboard.Listener | None = None
        # Os callbacks do pynput rodam DENTRO do hook WH_KEYBOARD_LL, e o
        # Windows descarta hooks que demoram mais que LowLevelHooksTimeout
        # (300 ms por padrao). Abrir o PortAudio leva ~200 ms, entao o
        # trabalho sai do hook por esta fila e o hook so enfileira.
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._pump: threading.Thread | None = None

    def register(self, binding_id: str, spec: str, trigger: str) -> None:
        binding = _Binding(binding_id, spec, trigger)
        with self._lock:
            for other in self._bindings:
                if other.keys == binding.keys:
                    raise HotkeyError(
                        f"O atalho '{spec}' esta em dois modos "
                        f"('{other.id}' e '{binding_id}')."
                    )
            self._bindings.append(binding)

    def clear(self) -> None:
        with self._lock:
            self._bindings.clear()

    def start(self) -> None:
        if self._listener is not None:
            return
        self._pump = threading.Thread(
            target=self._pump_events, name="artemis-hotkeys", daemon=True
        )
        self._pump.start()
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.stop()
        if self._pump is not None:
            self._events.put(None)  # sentinela: encerra a thread de despacho
            self._pump = None

    def _pump_events(self) -> None:
        while True:
            item = self._events.get()
            if item is None:
                return
            binding_id, event = item
            # Um erro no callback nao pode matar o pump: sem pump, sem atalho.
            try:
                self._on_event(binding_id, event)
            except Exception:
                log.exception("Erro no callback do atalho '%s'", binding_id)

    # ------------------------------------------------------------ eventos

    def _canonical(self, key):
        try:
            return self._listener.canonical(key)  # ctrl_l/ctrl_r -> ctrl
        except Exception:
            return key

    def _on_press(self, key) -> None:
        key = self._canonical(key)
        fire: list[str] = []
        with self._lock:
            if key in self._pressed:
                return  # auto-repeat do Windows: ignorar
            self._pressed.add(key)
            for binding in self._bindings:
                if not binding.active and binding.keys <= self._pressed:
                    binding.active = True
                    fire.append(binding.id)
        for binding_id in fire:
            self._dispatch(binding_id, "activate")

    def _on_release(self, key) -> None:
        key = self._canonical(key)
        fire: list[str] = []
        with self._lock:
            self._pressed.discard(key)
            for binding in self._bindings:
                if binding.active and key in binding.keys:
                    binding.active = False
                    fire.append(binding.id)
        for binding_id in fire:
            self._dispatch(binding_id, "deactivate")

    def _dispatch(self, binding_id: str, event: str) -> None:
        """So enfileira. O hook do teclado precisa retornar em microssegundos."""
        self._events.put((binding_id, event))

    # ------------------------------------------------- estado do teclado

    def is_any_pressed(self, keys: set) -> bool:
        with self._lock:
            return bool(self._pressed & keys)

    def modifiers_held(self) -> bool:
        """True se algum modificador ainda esta fisicamente pressionado.

        Usado antes de injetar Ctrl+V: se o usuario ainda segura Ctrl+Alt,
        o Ctrl+V injetado vira Ctrl+Alt+V e nao cola nada.
        """
        return self.is_any_pressed(_MODIFIERS)

    def wait_modifiers_released(self, timeout: float = 1.5) -> bool:
        deadline = time.monotonic() + timeout
        while self.modifiers_held():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)
        return True


_MODIFIERS = {
    keyboard.Key.ctrl,
    keyboard.Key.ctrl_l,
    keyboard.Key.ctrl_r,
    keyboard.Key.alt,
    keyboard.Key.alt_l,
    keyboard.Key.alt_r,
    keyboard.Key.alt_gr,
    keyboard.Key.shift,
    keyboard.Key.shift_l,
    keyboard.Key.shift_r,
    keyboard.Key.cmd,
    keyboard.Key.cmd_l,
    keyboard.Key.cmd_r,
}


def describe(spec: str) -> str:
    """'<ctrl>+<alt>+<space>' -> 'Ctrl + Alt + Space', para exibir na UI."""
    parts = []
    for token in spec.split("+"):
        token = token.strip().strip("<>")
        parts.append(token.capitalize() if len(token) > 1 else token.upper())
    return " + ".join(parts)
