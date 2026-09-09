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

Supressao (por que existe EVIOCGRAB aqui):
  Ler o evdev nao esconde a tecla de ninguem: a combinacao tambem chega na
  aplicacao em foco. Para <ctrl>+<alt>+<space> isso e inofensivo, mas a tecla
  de ditado do MX Keys Mini manda Super+H - e o 'h' aparecia digitado no meio
  do texto. A unica forma de impedir isso no Linux e o grab exclusivo do
  dispositivo (EVIOCGRAB), que tira TODOS os eventos dele do compositor.
  Entao, com o grab ligado, este modulo passa a ser responsavel por devolver
  ao sistema tudo que nao for atalho - e o que _Writer faz, por /dev/uinput.
  So sao capturados os teclados capazes de disparar algum atalho registrado,
  e o kernel desfaz o grab sozinho se o processo morrer.

O formato das specs e o mesmo do pynput ('<ctrl>+<alt>+<space>', '<cmd>+h'),
porque e o que ja esta gravado em presets.json e o que a captura de atalho da
janela de configuracoes produz. A traducao para keycodes acontece aqui.
"""

from __future__ import annotations

import logging
import os
import queue
import selectors
import struct
import threading
import time
from typing import Callable

from evdev import InputDevice, ecodes, list_devices

from .errors import HotkeyError
from .i18n import t

log = logging.getLogger(__name__)

EventCallback = Callable[[str, str], None]

# Prefixo dos teclados virtuais criados pelo proprio Artemis (o de colar, em
# linux.py, e o de reemissao aqui embaixo). Ler os proprios eventos criaria
# um laco: o que reemitimos voltaria como tecla nova.
VIRTUAL_PREFIX = "Artemis Dictation"
WRITER_NAME = "Artemis Dictation keyboard"

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

_LED_CODES = [
    ecodes.LED_NUML,
    ecodes.LED_CAPSL,
    ecodes.LED_SCROLLL,
    ecodes.LED_COMPOSE,
    ecodes.LED_KANA,
]

# Tudo que o teclado virtual sabe emitir. Declaramos a faixa inteira de teclas
# (e nao a capacidade do teclado capturado) porque um teclado novo pode entrar
# depois que o dispositivo virtual ja existe, e o que ele nao declarar o kernel
# descarta em silencio. BTN_* fica de fora: botao de mouse num teclado faria o
# libinput classificar o virtual como ponteiro.
def _is_button(name) -> bool:
    """BTN_LEFT e companhia. Alguns codigos tem mais de um nome (KEY_MUTE)."""
    names = (name,) if isinstance(name, str) else tuple(name)
    return any(n.startswith("BTN_") for n in names)


_PASSTHROUGH_KEYS = sorted(
    code for code, name in ecodes.KEY.items() if code < 0x300 and not _is_button(name)
)

# struct input_event, para ler os LEDs que o compositor manda ao virtual.
_EVENT_FORMAT = "llHHi"
_EVENT_SIZE = struct.calcsize(_EVENT_FORMAT)


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

    def reachable_on(self, keys) -> bool:
        """Este teclado tem teclas suficientes para disparar a combinacao?"""
        return all(any(code in keys for code in group) for group in self.groups)


class _Writer:
    """Teclado virtual que devolve ao sistema o que o grab exclusivo engoliu.

    Enquanto ha grab, o compositor nao ve mais nada do teclado fisico: cada
    tecla que nao for atalho precisa sair daqui. Um dispositivo so, comum a
    todos os teclados capturados - o compositor mantem um estado de
    modificadores por seat, entao nao faz diferenca de qual device veio.
    """

    def __init__(self):
        from evdev import UInput

        self._ui = UInput(
            {ecodes.EV_KEY: _PASSTHROUGH_KEYS, ecodes.EV_LED: _LED_CODES},
            name=WRITER_NAME,
        )
        # O compositor leva um instante para reconhecer um dispositivo novo;
        # sem esta pausa a primeira tecla depois do grab se perde.
        time.sleep(0.3)
        log.info("Teclado virtual de reemissao: %s", self._ui.device.path)

    def key(self, code: int, value: int) -> None:
        self._ui.write(ecodes.EV_KEY, code, value)
        self._ui.syn()

    def release(self, codes) -> None:
        for code in codes:
            try:
                self.key(code, 0)
            except Exception:
                pass

    def read_led(self, timeout: float = 0.5):
        """Proximo (code, value) de LED vindo do compositor, ou None."""
        import select

        ready, _, _ = select.select([self._ui.fd], [], [], timeout)
        if not ready:
            return None
        data = os.read(self._ui.fd, _EVENT_SIZE * 8)
        out = []
        for offset in range(0, len(data) - _EVENT_SIZE + 1, _EVENT_SIZE):
            _, _, etype, code, value = struct.unpack_from(
                _EVENT_FORMAT, data, offset
            )
            if etype == ecodes.EV_LED:
                out.append((code, value))
        return out or None

    def close(self) -> None:
        try:
            self._ui.close()
        except Exception:
            pass


class HotkeyManager:
    """Mesma API do HotkeyManager do Windows; so o backend muda."""

    # Intervalo do rescan de dispositivos. Teclado sem fio que dorme e acorda
    # (o MX Keys Mini faz isso) reaparece como um /dev/input novo.
    _RESCAN_SECONDS = 3.0

    def __init__(self, on_event: EventCallback, *, suppress: bool = True):
        self._on_event = on_event
        self._bindings: list[_Binding] = []
        self._pressed: set[int] = set()
        # O que o compositor enxerga pressionado. Igual a _pressed sem grab;
        # com grab, so o que reemitimos - as teclas do atalho ficam de fora.
        self._visible: set[int] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        # Mesma razao do Windows: o trabalho pesado (abrir o PortAudio leva
        # ~200 ms) nao pode acontecer na thread que le o teclado, senao os
        # eventos se acumulam no buffer do evdev.
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._pump: threading.Thread | None = None

        self._suppress = suppress
        self._writer: _Writer | None = None
        self._grabbed: set[str] = set()
        # Modificadores segurados: participam de algum atalho, entao so vao
        # para o compositor quando ficar claro que aquilo NAO era o atalho.
        self._held_back: list[int] = []
        # Teclas engolidas por terem completado um atalho: o release delas
        # tambem nao pode vazar.
        self._consumed: set[int] = set()
        self.suppress_error: str | None = None

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

    def set_suppression(self, enabled: bool) -> None:
        """Liga/desliga o grab exclusivo. O read_loop aplica no proximo scan."""
        self._suppress = bool(enabled)
        # Zerar o erro aqui e o que da uma segunda chance a quem corrigiu a
        # permissao de /dev/uinput: basta salvar as configuracoes de novo.
        self.suppress_error = None

    @property
    def suppressing(self) -> bool:
        return bool(self._grabbed)

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
        known: dict[str, InputDevice] = {}
        for device in devices:
            selector.register(device, selectors.EVENT_READ)
            known[device.path] = device
        self._apply_grabs(known)
        last_scan = time.monotonic()

        try:
            while not self._stop.is_set():
                for key, _ in selector.select(timeout=1.0):
                    device = key.fileobj
                    grabbed = device.path in self._grabbed
                    try:
                        for event in device.read():
                            if event.type == ecodes.EV_KEY:
                                self._on_key(event.code, event.value, grabbed)
                    except BlockingIOError:
                        continue  # nada pronto; NAO e dispositivo perdido
                    except OSError:
                        # Teclado desconectado (sem fio dormindo, USB removido).
                        log.info("Teclado sumiu: %s", device.path)
                        selector.unregister(device)
                        known.pop(device.path, None)
                        if device.path in self._grabbed:
                            self._grabbed.discard(device.path)
                            # Sumir segurando uma tecla deixaria ela presa no
                            # dispositivo virtual, e nao ha mais release para
                            # vir. O estado ficou incerto: zera tudo.
                            self._panic_release()
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
                    # Reavalia tambem os ja abertos: os atalhos podem ter
                    # mudado nas configuracoes desde o ultimo scan.
                    self._apply_grabs(known)
        finally:
            self._release_grabs(known)
            for device in known.values():
                try:
                    selector.unregister(device)
                    device.close()
                except Exception:
                    pass
            selector.close()
            if self._writer is not None:
                self._writer.close()
                self._writer = None

    # ------------------------------------------------------------- grab

    def _apply_grabs(self, known: dict[str, InputDevice]) -> None:
        """Captura com exclusividade os teclados que disparam algum atalho."""
        with self._lock:
            bindings = list(self._bindings)
        wanted = set()
        if self._suppress and bindings and self.suppress_error is None:
            for path, device in known.items():
                keys = set(device.capabilities().get(ecodes.EV_KEY, []))
                if any(b.reachable_on(keys) for b in bindings):
                    wanted.add(path)

        for path in wanted - self._grabbed:
            device = known.get(path)
            if device is None:
                continue
            try:
                self._ensure_writer()
                device.grab()
            except Exception as exc:
                # Sem supressao o app continua util - so volta a vazar a tecla.
                self.suppress_error = str(exc)
                log.warning("Nao consegui capturar %s: %s", path, exc)
                return
            self._grabbed.add(path)
            log.info("Capturando com exclusividade: %s [%s]", device.name, path)

        for path in self._grabbed - wanted:
            device = known.get(path)
            self._grabbed.discard(path)
            if device is not None:
                try:
                    device.ungrab()
                except Exception:
                    pass
                log.info("Liberado: %s", path)
        if not self._grabbed:
            self._forget_held()

    def _release_grabs(self, known: dict[str, InputDevice]) -> None:
        for path in list(self._grabbed):
            device = known.get(path)
            if device is not None:
                try:
                    device.ungrab()
                except Exception:
                    pass
        self._grabbed.clear()
        # Nao deixa tecla presa no compositor por causa do dispositivo virtual.
        if self._writer is not None:
            self._writer.release(list(self._visible))
        self._visible.clear()
        self._forget_held()

    def _panic_release(self) -> None:
        """Solta tudo que o dispositivo virtual pode estar segurando."""
        if self._writer is not None and self._visible:
            log.info("Soltando teclas presas: %s", sorted(self._visible))
            self._writer.release(list(self._visible))
        self._visible.clear()
        with self._lock:
            self._pressed.clear()
            for binding in self._bindings:
                binding.active = False
        self._forget_held()

    def _ensure_writer(self) -> _Writer:
        if self._writer is None:
            self._writer = _Writer()
            threading.Thread(
                target=self._mirror_leds, name="artemis-hotkeys-leds", daemon=True
            ).start()
        return self._writer

    def _mirror_leds(self) -> None:
        """Espelha Caps/Num Lock do teclado virtual de volta no fisico.

        Com o grab, quem o compositor enxerga e o dispositivo virtual: e nele
        que ele acende o LED do Caps Lock. Sem este espelho, a luz da tecla
        no teclado de verdade nunca mais acenderia.
        """
        writer = self._writer
        while writer is not None and not self._stop.is_set():
            try:
                leds = writer.read_led()
            except Exception:
                log.debug("Espelho de LED encerrado", exc_info=True)
                return
            if not leds:
                continue
            for path in list(self._grabbed):
                try:
                    device = InputDevice(path)
                    for code, value in leds:
                        device.set_led(code, value)
                    device.close()
                except Exception:
                    pass

    # ------------------------------------------------------------- teclas

    def _on_key(self, code: int, value: int, grabbed: bool = False) -> None:
        if value == 2:
            # Auto-repeat: o press ja foi tratado, e o compositor gera o
            # proprio repeat a partir do estado da tecla.
            return
        fire: list[tuple[str, str]] = []
        combo_codes: set[int] = set()
        with self._lock:
            if value == 1:
                if code in self._pressed:
                    return
                self._pressed.add(code)
                for binding in self._bindings:
                    if not binding.active and binding.satisfied_by(self._pressed):
                        binding.active = True
                        fire.append((binding.id, "activate"))
                        combo_codes |= binding.all_codes
            else:
                self._pressed.discard(code)
                for binding in self._bindings:
                    if binding.active and code in binding.all_codes:
                        binding.active = False
                        fire.append((binding.id, "deactivate"))
            binding_codes = set().union(
                *(b.all_codes for b in self._bindings)
            ) if self._bindings else set()

        if grabbed:
            self._passthrough(code, value, bool(fire), combo_codes, binding_codes)
        elif value == 1:
            self._visible.add(code)
        else:
            self._visible.discard(code)

        for item in fire:
            self._events.put(item)  # so enfileira; ver comentario no __init__

    def _passthrough(
        self,
        code: int,
        value: int,
        fired: bool,
        combo_codes: set[int],
        binding_codes: set[int],
    ) -> None:
        """Decide o que devolver ao compositor de uma tecla capturada."""
        writer = self._writer
        if writer is None:
            return

        if value == 1:
            if fired:
                # Completou um atalho: nem esta tecla nem os modificadores
                # que ela usou podem chegar na aplicacao em foco.
                self._consumed.add(code)
                for held in list(self._held_back):
                    if held in combo_codes:
                        self._held_back.remove(held)
                        self._consumed.add(held)
                self._flush_held(writer)
                return
            if code in binding_codes and code in _MODIFIER_CODES:
                # Ainda pode virar atalho: segura. Modificador sozinho nao
                # digita nada, entao adiar nao muda o que o usuario ve.
                self._held_back.append(code)
                return
            self._flush_held(writer)
            self._emit(writer, code, 1)
            return

        if code in self._consumed:
            self._consumed.discard(code)
            return
        if code in self._held_back:
            # Modificador segurado que nao virou atalho: o toque precisa
            # existir inteiro (dar um tap no Super abre o panorama do GNOME).
            self._held_back.remove(code)
            self._emit(writer, code, 1)
            self._emit(writer, code, 0)
            return
        self._emit(writer, code, 0)

    def _emit(self, writer: _Writer, code: int, value: int) -> None:
        try:
            writer.key(code, value)
        except Exception:
            log.debug("Falha ao reemitir a tecla %s", code, exc_info=True)
            return
        if value == 1:
            self._visible.add(code)
        else:
            self._visible.discard(code)

    def _flush_held(self, writer: _Writer) -> None:
        """Solta os modificadores segurados, na ordem em que foram apertados."""
        for held in self._held_back:
            self._emit(writer, held, 1)
        self._held_back.clear()

    def _forget_held(self) -> None:
        self._held_back.clear()
        self._consumed.clear()

    # ------------------------------------------------- estado do teclado

    def is_any_pressed(self, keys: set) -> bool:
        with self._lock:
            return bool(self._pressed & set(keys))

    def modifiers_held(self) -> bool:
        """True se algum modificador que o COMPOSITOR ve ainda esta baixo.

        Usado antes de injetar Ctrl+V: se o usuario ainda segura Ctrl+Alt, o
        Ctrl+V injetado vira Ctrl+Alt+V e nao cola nada. Com a supressao
        ligada os modificadores do atalho nunca chegaram no compositor, entao
        eles nao entram nesta conta - e a colagem sai na hora.
        """
        return bool(self._visible & _MODIFIER_CODES)

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
        if _is_keyboard(device) and not device.name.startswith(VIRTUAL_PREFIX):
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
