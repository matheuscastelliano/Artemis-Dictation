"""Captura do microfone.

Decisoes:
  - 16 kHz, mono, PCM16. Modelos de STT trabalham internamente em 16 kHz;
    gravar em 44.1 kHz so aumenta o upload sem ganho de precisao.
  - RawInputStream (buffers de bytes crus) em vez de InputStream: dispensa
    numpy e evita conversoes desnecessarias.
  - O WAV e montado em memoria (BytesIO). O audio nunca toca o disco.
  - O stream so existe enquanto grava, entao a CPU em repouso e ~0%.
"""

from __future__ import annotations

import io
import threading
import wave

import sounddevice as sd

from .errors import AudioError
from .i18n import t

CHANNELS = 1
DTYPE = "int16"
BYTES_PER_SAMPLE = 2


def list_input_devices() -> list[dict]:
    """Microfones disponiveis, na forma {index, name, default}."""
    try:
        devices = sd.query_devices()
        default_index = sd.default.device[0]
    except Exception as exc:  # PortAudio pode falhar de varias formas
        raise AudioError(t("err.mic_list"), str(exc)) from exc

    result = []
    for index, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) < 1:
            continue
        result.append(
            {
                "index": index,
                "name": dev["name"],
                "default": index == default_index,
            }
        )
    return result


class AudioRecorder:
    """Grava do microfone para memoria. Uma gravacao por vez."""

    def __init__(self, sample_rate: int = 16000, device: str | int | None = None):
        self.sample_rate = sample_rate
        self.device = device
        self._stream: sd.RawInputStream | None = None
        self._chunks: list[bytes] = []
        self._lock = threading.Lock()
        self._overflowed = False

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    @property
    def duration(self) -> float:
        with self._lock:
            total = sum(len(c) for c in self._chunks)
        return total / (self.sample_rate * CHANNELS * BYTES_PER_SAMPLE)

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            # Overflow = o callback nao deu conta; o audio fica com falhas.
            self._overflowed = True
        with self._lock:
            self._chunks.append(bytes(indata))

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._chunks = []
        self._overflowed = False
        try:
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()
        except sd.PortAudioError as exc:
            self._stream = None
            raise AudioError(t("err.mic_busy"), str(exc)) from exc
        except Exception as exc:
            self._stream = None
            raise AudioError(t("err.mic_open"), str(exc)) from exc

    def stop(self) -> bytes:
        """Encerra a gravacao e devolve o WAV completo em bytes."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass  # ja estamos encerrando; nao ha o que recuperar aqui
        with self._lock:
            pcm = b"".join(self._chunks)
            self._chunks = []
        return _to_wav(pcm, self.sample_rate)

    def cancel(self) -> None:
        """Descarta a gravacao em andamento sem produzir audio."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._chunks = []


def _to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(BYTES_PER_SAMPLE)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def wav_duration(wav_bytes: bytes, sample_rate: int) -> float:
    header = 44  # WAV PCM canonico
    return max(0.0, (len(wav_bytes) - header)) / (
        sample_rate * CHANNELS * BYTES_PER_SAMPLE
    )
