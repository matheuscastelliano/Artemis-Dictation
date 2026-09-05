"""Hotkeys globais no Linux, lendo /dev/input direto via evdev.

Por que nao pynput, como no Windows:
  No Linux o pynput so tem backend X11 - ele bisbilhota o servidor X via
  XRecord. Sob Wayland o compositor so entrega ao XWayland os eventos
  destinados a janelas X, entao com um app Wayland nativo em foco (Firefox,
  quase tudo do GNOME 50) o listener simplesmente nao recebe nada. Ler o
  evdev fica ABAIXO do compositor, entao funciona igual em Wayland, X11,
  GNOME e KDE - e, ao contrario de um atalho registrado no compositor,
  entrega press E release, que e o que o modo push-to-talk precisa.

Preco: exige acesso de leitura a /dev/input/event*, ou seja, estar no grupo
'input'. Sem isso o start() levanta HotkeyError com a instrucao.

Assim como no Windows, os eventos NAO sao capturados com exclusividade (nada
de EVIOCGRAB): a combinacao tambem chega na aplicacao em foco. Escolha
combinacoes que o app de destino ignore.

O formato das specs e o mesmo do pynput ('<ctrl>+<alt>+<space>', '<cmd>+h'),
porque e o que ja esta gravado em presets.json e o que a captura de atalho da
janela de configuracoes produz. A traducao para keycodes acontece aqui.
"""

from __future__ import annotations

import logging
import queue
import selectors
import threading
import time
from typing import Callable

from evdev import InputDevice, ecodes, list_devices

from .errors import HotkeyError
from .i18n import t

log = logging.getLogger(__name__)

EventCallback = Callable[[str, str], None]

# Um token da spec vira um GRUPO de keycodes aceitos, nao um keycode so:
# '<ctrl>' tem de casar com o Ctrl da esquerda ou o da direita, que e o
# equivalente ao canonical() do pynput (ctrl_l/ctrl_r -> ctrl).
_NAMED: dict[str, tuple[int, ...]] = {
    "ctrl": (ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL),
    "ctrl_l": (ecodes.KEY_LEFTCTRL,),
    "ctrl_r": (ecodes.KEY_RIGHTCTRL,),
    "alt": (ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT),
    "alt_l": (ecodes.KEY_LEFTALT,),
    "alt_r": (ecodes.KEY_RIGHTALT,),
    "alt_gr": (ecodes.KEY_RIGHTALT,),
    "shift": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT),
    "shift_l": (ecodes.KEY_LEFTSHIFT,),
    "shift_r": (ecodes.KEY_RIGHTSHIFT,),
    # <cmd> e o nome do pynput para a tecla Super/Meta - a tecla Windows.
    "cmd": (ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA),
    "cmd_l": (ecodes.KEY_LEFTMETA,),
    "cmd_r": (ecodes.KEY_RIGHTMETA,),
    "space": (ecodes.KEY_SPACE,),
    "enter": (ecodes.KEY_ENTER,),
    "return": (ecodes.KEY_ENTER,),
    "tab": (ecodes.KEY_TAB,),
    "esc": (ecodes.KEY_ESC,),
    "escape": (ecodes.KEY_ESC,),
    "backspace": (ecodes.KEY_BACKSPACE,),
    "delete": (ecodes.KEY_DELETE,),
    "insert": (ecodes.KEY_INSERT,),
    "home": (ecodes.KEY_HOME,),
    "end": (ecodes.KEY_END,),
    "page_up": (ecodes.KEY_PAGEUP,),
    "page_down": (ecodes.KEY_PAGEDOWN,),
    "up": (ecodes.KEY_UP,),
    "down": (ecodes.KEY_DOWN,),
    "left": (ecodes.KEY_LEFT,),
    "right": (ecodes.KEY_RIGHT,),
    "caps_lock": (ecodes.KEY_CAPSLOCK,),
    "menu": (ecodes.KEY_COMPOSE,),
    "pause": (ecodes.KEY_PAUSE,),
    "print_screen": (ecodes.KEY_SYSRQ,),
}

# A tecla de ditado dedicada (HUTRR99, 0x24a). O MX Keys Mini manda Super+H em
# vez disto, mas outros teclados mandam o codigo real - aceitar os dois sai de
# graca. getattr porque o ecodes do python-evdev e gerado dos headers do
# kernel na compilacao: em build antigo a constante pode nao existir.
KEY_DICTATE = getattr(ecodes, "KEY_DICTATE", 0x24A)
_NAMED["dictate"] = (KEY_DICTATE,)

for _n in range(1, 25):  # F1..F24
    _code = getattr(ecodes, f"KEY_F{_n}", None)
    if _code is not None:
        _NAMED[f"f{_n}"] = (_code,)

_MODIFIER_CODES = frozenset(
    {
        ecodes.KEY_LEFTCTRL,
        ecodes.KEY_RIGHTCTRL,
        ecodes.KEY_LEFTALT,
        ecodes.KEY_RIGHTALT,
        ecodes.KEY_LEFTSHIFT,
        ecodes.KEY_RIGHTSHIFT,
        ecodes.KEY_LEFTMETA,
        ecodes.KEY_RIGHTMETA,
    }
)


def _codes_for(token: str) -> tuple[int, ...]:
    """Um token da spec -> os keycodes que o satisfazem."""
    name = token.strip()
    if name.startswith("<") and name.endswith(">"):
        key = name[1:-1].lower()
        if key in _NAMED:
            return _NAMED[key]
        raise KeyError(name)

    if len(name) == 1:
        char = name.lower()
        if char.isalpha():
            return (ecodes.ecodes[f"KEY_{char.upper()}"],)
        if char.isdigit():
            return (ecodes.ecodes[f"KEY_{char}"],)
        symbol = {
            "-": ecodes.KEY_MINUS,
            "=": ecodes.KEY_EQUAL,
            "[": ecodes.KEY_LEFTBRACE,
            "]": ecodes.KEY_RIGHTBRACE,
            ";": ecodes.KEY_SEMICOLON,
            "'": ecodes.KEY_APOSTROPHE,
            "`": ecodes.KEY_GRAVE,
            "\\": ecodes.KEY_BACKSLASH,
            ",": ecodes.KEY_COMMA,
            ".": ecodes.KEY_DOT,
            "/": ecodes.KEY_SLASH,
        }.get(char)
        if symbol is not None:
            return (symbol,)
    raise KeyError(name)


class _Binding:
    def __init__(self, binding_id: str, spec: str, trigger: str):
        self.id = binding_id
        self.spec = spec
        self.trigger = trigger
        try:
            groups = [_codes_for(token) for token in spec.split("+") if token.strip()]
        except KeyError as exc:
            raise HotkeyError(
                t("err.hotkey_invalid", spec=spec), t("err.hotkey_invalid.detail")
            ) from exc
        if not groups:
            raise HotkeyError(t("err.hotkey_empty", mode=binding_id))
        self.groups: list[frozenset[int]] = [frozenset(g) for g in groups]
        # Todos os codigos que participam da combinacao, para saber se um
        # release qualquer deve desativa-la.
        self.all_codes: frozenset[int] = frozenset().union(*self.groups)
        self.active = False

    def satisfied_by(self, pressed: set[int]) -> bool:
        """Cada grupo precisa de pelo menos um representante pressionado."""
        return all(group & pressed for group in self.groups)

    def same_combo(self, other: "_Binding") -> bool:
        return sorted(self.groups, key=sorted) == sorted(other.groups, key=sorted)


class HotkeyManager:
    """Mesma API do HotkeyManager do Windows; so o backend muda."""

    # Intervalo do rescan de dispositivos. Teclado sem fio que dorme e acorda
    # (o MX Keys Mini faz isso) reaparece como um /dev/input novo.
    _RESCAN_SECONDS = 3.0

    def __init__(self, on_event: EventCallback):
        self._on_event = on_event
        self._bindings: list[_Binding] = []
        self._pressed: set[int] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        # Mesma razao do Windows: o trabalho pesado (abrir o PortAudio leva
        # ~200 ms) nao pode acontecer na thread que le o teclado, senao os
        # eventos se acumulam no buffer do evdev.
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._pump: threading.Thread | None = None

    # ---------------------------------------------------------- registro

    def register(self, binding_id: str, spec: str, trigger: str) -> None:
        binding = _Binding(binding_id, spec, trigger)
        with self._lock:
            for other in self._bindings:
                if other.same_combo(binding):
                    raise HotkeyError(
                        t(
                            "err.hotkey_conflict",
                            spec=spec,
                            first=other.id,
                            second=binding_id,
                        )
                    )
            self._bindings.append(binding)

    def clear(self) -> None:
        with self._lock:
            self._bindings.clear()

    # ------------------------------------------------------ ciclo de vida

    def start(self) -> None:
        if self._reader is not None:
            return
        devices = _open_keyboards()
        if not devices:
            raise HotkeyError(
                t("err.hotkey_problems"),
                "nao consegui ler nenhum teclado em /dev/input. "
                "Rode: sudo usermod -aG input $USER, depois logout/login.",
            )
        log.info(
            "Lendo teclado(s): %s", ", ".join(f"{d.name} [{d.path}]" for d in devices)
        )

        self._stop.clear()
        self._pump = threading.Thread(
            target=self._pump_events, name="artemis-hotkeys-pump", daemon=True
        )
        self._pump.start()
        self._reader = threading.Thread(
            target=self._read_loop, args=(devices,), name="artemis-hotkeys", daemon=True
        )
        self._reader.start()

    def stop(self) -> None:
        self._stop.set()
        self._reader = None
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

    # -------------------------------------------------------------- leitura

    def _read_loop(self, devices: list[InputDevice]) -> None:
        selector = selectors.DefaultSelector()
        known = {}
        for device in devices:
            selector.register(device, selectors.EVENT_READ)
            known[device.path] = device
        last_scan = time.monotonic()

        try:
            while not self._stop.is_set():
                for key, _ in selector.select(timeout=1.0):
                    device = key.fileobj
                    try:
                        for event in device.read():
                            if event.type == ecodes.EV_KEY:
                                self._on_key(event.code, event.value)
                    except BlockingIOError:
                        continue  # nada pronto; NAO e dispositivo perdido
                    except OSError:
                        # Teclado desconectado (sem fio dormindo, USB removido).
                        log.info("Teclado sumiu: %s", device.path)
                        selector.unregister(device)
                        known.pop(device.path, None)
                        try:
                            device.close()
                        except Exception:
                            pass

                now = time.monotonic()
                if now - last_scan >= self._RESCAN_SECONDS:
                    last_scan = now
                    for device in _open_keyboards(skip=set(known)):
                        log.info("Teclado novo: %s [%s]", device.name, device.path)
                        selector.register(device, selectors.EVENT_READ)
                        known[device.path] = device
        finally:
            for device in known.values():
                try:
                    selector.unregister(device)
                    device.close()
                except Exception:
                    pass
            selector.close()

    def _on_key(self, code: int, value: int) -> None:
        if value == 2:
            return  # auto-repeat: ja tratamos o press
        fire: list[tuple[str, str]] = []
        with self._lock:
            if value == 1:
                if code in self._pressed:
                    return
                self._pressed.add(code)
                for binding in self._bindings:
                    if not binding.active and binding.satisfied_by(self._pressed):
                        binding.active = True
                        fire.append((binding.id, "activate"))
            else:
                self._pressed.discard(code)
                for binding in self._bindings:
                    if binding.active and code in binding.all_codes:
                        binding.active = False
                        fire.append((binding.id, "deactivate"))
        for item in fire:
            self._events.put(item)  # so enfileira; ver comentario no __init__

    # ------------------------------------------------- estado do teclado

    def is_any_pressed(self, keys: set) -> bool:
        with self._lock:
            return bool(self._pressed & set(keys))

    def modifiers_held(self) -> bool:
        """True se algum modificador ainda esta fisicamente pressionado.

        Usado antes de injetar Ctrl+V: se o usuario ainda segura Ctrl+Alt, o
        Ctrl+V injetado vira Ctrl+Alt+V e nao cola nada. Vale mesmo com a
        injecao vindo de um uinput proprio: o compositor junta o estado dos
        modificadores de todos os dispositivos.
        """
        return self.is_any_pressed(_MODIFIER_CODES)

    def wait_modifiers_released(self, timeout: float = 1.5) -> bool:
        deadline = time.monotonic() + timeout
        while self.modifiers_held():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)
        return True


def _open_keyboards(skip: set[str] | None = None) -> list[InputDevice]:
    """Todos os teclados legiveis de /dev/input, pulando os ja abertos."""
    skip = skip or set()
    found = []
    for path in list_devices():
        if path in skip:
            continue
        try:
            device = InputDevice(path)
        except (OSError, PermissionError):
            continue  # sem permissao ou sumiu no meio do scan
        if _is_keyboard(device):
            found.append(device)
        else:
            device.close()
    return found


def _is_keyboard(device: InputDevice) -> bool:
    """Teclado de verdade, nao mouse nem sensor.

    Aceita tambem um 'Consumer Control' que carregue a tecla de ditado: em
    varios teclados as teclas de midia sao um dispositivo separado do
    alfanumerico.
    """
    keys = device.capabilities().get(ecodes.EV_KEY, [])
    if not keys:
        return False
    return ecodes.KEY_A in keys or ecodes.KEY_ESC in keys or KEY_DICTATE in keys


def describe(spec: str) -> str:
    """'<ctrl>+<alt>+<space>' -> 'Ctrl + Alt + Space', para exibir na UI."""
    parts = []
    for token in spec.split("+"):
        token = token.strip().strip("<>")
        parts.append(token.capitalize() if len(token) > 1 else token.upper())
    return " + ".join(parts)
