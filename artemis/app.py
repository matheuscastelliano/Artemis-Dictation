"""AppController: a maquina de estados do ditado.

    IDLE --(hotkey)--> RECORDING --(hotkey/release)--> PROCESSING --> IDLE

Regra que atravessa o arquivo inteiro: nenhuma excecao pode derrubar o app.
Ele fica ligado o dia todo; um erro vira um aviso no overlay e volta para
IDLE.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from . import config as config_module
from . import output, pipeline, startup
from .audio import AudioRecorder, wav_duration
from .errors import ArtemisError, CredentialsError
from .hotkeys import HotkeyManager
from .i18n import t
from .presets import Preset
from .providers.openai_provider import OpenAIProvider
from .secrets_store import get_api_key

log = logging.getLogger(__name__)


class State(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"


@dataclass
class Status:
    """O que a UI precisa saber. O campo kind escolhe o icone e a cor."""

    kind: str  # idle | recording | processing | done | error
    message: str = ""
    detail: str = ""
    # Preenchido em "done": o texto ditado, para o overlay mostrar. Assim
    # voce ve o que saiu mesmo quando a colagem nao encontrou campo nenhum.
    text: str = ""


StatusCallback = Callable[[Status], None]


class AppController:
    def __init__(self, on_status: StatusCallback):
        self._on_status = on_status
        self._state = State.IDLE
        self._lock = threading.Lock()
        self._active_preset: Preset | None = None
        self._target_hwnd = None
        self._max_timer: threading.Timer | None = None

        self.config: dict = {}
        self.presets: list[Preset] = []
        # Ultimos ditados, para reaproveitar pelo menu da bandeja quando a
        # colagem nao encontra campo em foco. Vive so na memoria: nada vai
        # para disco, e some quando o app fecha.
        self.history: deque[str] = deque(maxlen=10)
        self._recorder: AudioRecorder | None = None
        self._provider: OpenAIProvider | None = None
        self._hotkeys = HotkeyManager(self._on_hotkey_event)
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="artemis")

    # ------------------------------------------------------- ciclo de vida

    def start(self) -> None:
        self.reload()
        self._hotkeys.start()

    def reload(self) -> None:
        """Recarrega config/presets e reprograma os atalhos.

        Chamado no boot e sempre que as configuracoes mudam. Erros aqui sao
        reportados na UI, mas o app continua de pe com o que ja tinha.
        """
        try:
            self.config = config_module.load_config()
            self.presets = config_module.load_presets()
        except ArtemisError as exc:
            self._emit(Status("error", exc.message, exc.detail or ""))
            return

        # A inicializacao com o Windows mora no registro, nao no config:
        # aplicar aqui mantem os dois em sincronia a cada recarga.
        try:
            startup.sync(bool(self.config.get("start_with_windows", False)))
        except ArtemisError as exc:
            self._emit(Status("error", exc.message, exc.detail or ""))

        size = int(self.config.get("history_size", 10))
        if size != self.history.maxlen:
            self.history = deque(self.history, maxlen=max(0, size))

        self._recorder = AudioRecorder(
            sample_rate=self.config["sample_rate"],
            device=self.config["input_device"],
        )
        self._provider = None  # recriado sob demanda, com a key/modelos atuais

        self._hotkeys.clear()
        problems = []
        for preset in self.presets:
            try:
                self._hotkeys.register(preset.id, preset.hotkey, preset.trigger)
            except ArtemisError as exc:
                problems.append(f"{preset.name}: {exc.message}")
        if problems:
            self._emit(Status("error", t("err.hotkey_problems"), "; ".join(problems)))
        else:
            self._emit(Status("idle"))

    def shutdown(self) -> None:
        self._cancel_max_timer()
        self._hotkeys.stop()
        if self._recorder is not None:
            self._recorder.cancel()
        self._worker.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------ atalhos

    def preset_by_id(self, preset_id: str) -> Preset | None:
        return next((p for p in self.presets if p.id == preset_id), None)

    def _on_hotkey_event(self, preset_id: str, event: str) -> None:
        preset = self.preset_by_id(preset_id)
        if preset is None:
            return
        if preset.trigger == "hold":
            if event == "activate":
                self.begin(preset)
            else:
                self.finish()
        elif event == "activate":  # toggle
            if self._state is State.RECORDING:
                self.finish()
            else:
                self.begin(preset)

    def trigger(self, preset: Preset) -> None:
        """Aciona um modo pelo menu do tray (sempre em toggle)."""
        if self._state is State.RECORDING:
            self.finish()
        else:
            self.begin(preset)

    # --------------------------------------------------------- gravacao

    def begin(self, preset: Preset) -> None:
        with self._lock:
            if self._state is not State.IDLE:
                return  # ja gravando ou ainda processando o anterior
            if self._recorder is None:
                return
            self._state = State.RECORDING
            self._active_preset = preset

        # Guardado ANTES de gravar: e a janela onde o texto deve aparecer.
        self._target_hwnd = output.foreground_window()

        try:
            self._recorder.start()
        except ArtemisError as exc:
            with self._lock:
                self._state = State.IDLE
                self._active_preset = None
            self._emit(Status("error", exc.message, exc.detail or ""))
            return

        self._beep(1000)
        self._arm_max_timer()
        self._emit(Status("recording", preset.name))

    def finish(self) -> None:
        with self._lock:
            if self._state is not State.RECORDING:
                return
            self._state = State.PROCESSING
            preset = self._active_preset

        self._cancel_max_timer()
        self._beep(700)
        try:
            wav = self._recorder.stop()
        except Exception as exc:
            log.exception("Falha ao encerrar a gravacao")
            self._reset(Status("error", t("err.recording_stop"), str(exc)))
            return

        seconds = wav_duration(wav, self.config["sample_rate"])
        if seconds < self.config["min_recording_seconds"]:
            # Toque acidental no atalho: nem gasta chamada de API.
            self._reset(Status("idle", t("status.too_short")))
            return

        self._emit(Status("processing", preset.name))
        self._worker.submit(self._process, wav, preset, self._target_hwnd)

    def cancel(self) -> None:
        """Aborta a gravacao em andamento sem enviar nada para a API."""
        with self._lock:
            if self._state is not State.RECORDING:
                return
            self._state = State.IDLE
            self._active_preset = None
        self._cancel_max_timer()
        if self._recorder is not None:
            self._recorder.cancel()
        self._emit(Status("idle", t("status.cancelled")))

    # -------------------------------------------------------- processamento

    def _process(self, wav: bytes, preset: Preset, hwnd) -> None:
        try:
            provider = self._ensure_provider()
            result = pipeline.run(wav, preset, self.config, provider)

            # Antes de tentar colar: se a colagem falhar, ou cair fora de um
            # campo de texto, o ditado ainda esta aqui.
            self.remember(result.text)

            pasted = output.deliver(
                result.text,
                hwnd,
                wait_modifiers=self._hotkeys.wait_modifiers_released,
                restore_previous=bool(self.config.get("restore_clipboard", False)),
            )
            if pasted:
                self._reset(
                    Status(
                        "done",
                        f"{preset.name} - {result.total_seconds:.1f}s",
                        text=result.text,
                    )
                )
            else:
                self._reset(
                    Status(
                        "done",
                        t("status.clipboard_only"),
                        t("status.clipboard_only.detail"),
                        text=result.text,
                    )
                )
        except ArtemisError as exc:
            self._reset(Status("error", exc.message, exc.detail or ""))
        except Exception as exc:
            log.exception("Falha inesperada no processamento")
            self._reset(Status("error", t("err.unexpected"), str(exc)))

    def _ensure_provider(self) -> OpenAIProvider:
        if self._provider is None:
            api_key = get_api_key()
            if not api_key:
                raise CredentialsError(
                    t("err.no_api_key"), t("err.no_api_key.detail")
                )
            self._provider = OpenAIProvider(
                api_key=api_key,
                stt_model=self.config["stt_model"],
                text_model=self.config["text_model"],
                timeout=self.config["request_timeout"],
            )
        return self._provider

    # --------------------------------------------------------- historico

    def remember(self, text: str) -> None:
        if not text or self.history.maxlen == 0:
            return
        if self.history and self.history[0] == text:
            return  # mesmo ditado duas vezes seguidas: nao duplica
        self.history.appendleft(text)

    def recall(self, text: str) -> None:
        """Devolve um ditado antigo para o clipboard.

        Nao tenta colar: quando o usuario recorre ao historico e porque a
        colagem automatica ja falhou uma vez. Ele clica no campo e da Ctrl+V.
        """
        try:
            output.copy(text)
            self._emit(
                Status("done", t("status.copied"), t("status.copied.detail"), text=text)
            )
        except ArtemisError as exc:
            self._emit(Status("error", exc.message, exc.detail or ""))

    def clear_history(self) -> None:
        self.history.clear()

    # ------------------------------------------------------------ helpers

    def _reset(self, status: Status) -> None:
        with self._lock:
            self._state = State.IDLE
            self._active_preset = None
        self._emit(status)

    def _emit(self, status: Status) -> None:
        try:
            self._on_status(status)
        except Exception:
            log.exception("Erro ao atualizar a interface")

    def _arm_max_timer(self) -> None:
        limit = float(self.config.get("max_recording_seconds", 600))
        self._max_timer = threading.Timer(limit, self._on_max_duration)
        self._max_timer.daemon = True
        self._max_timer.start()

    def _cancel_max_timer(self) -> None:
        timer, self._max_timer = self._max_timer, None
        if timer is not None:
            timer.cancel()

    def _on_max_duration(self) -> None:
        log.warning("Limite de gravacao atingido; encerrando sozinho.")
        self.finish()

    def _beep(self, frequency: int) -> None:
        if not self.config.get("sound_feedback", True):
            return

        def play() -> None:
            try:
                import winsound

                winsound.Beep(frequency, 70)
            except Exception:
                pass  # sem som e um detalhe; nao vale um erro

        threading.Thread(target=play, daemon=True).start()

    @property
    def state(self) -> State:
        return self._state
