"""Do audio ao texto final.

Um caminho unico para todos os modos. A diferenca entre "Transcrever" e
"Melhorar" e o campo `refine` do preset, nao um ramo de codigo:

    audio -> STT -> [ LLM com o system_prompt do preset ] -> texto

No modo Transcrever o passo do LLM simplesmente nao existe, o que economiza
~0.5-1s de latencia e evita o risco de o texto ser reescrito quando o
usuario pediu fidelidade.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .presets import Preset
from .providers.openai_provider import OpenAIProvider

log = logging.getLogger(__name__)


@dataclass
class Result:
    text: str
    raw_text: str
    stt_seconds: float
    refine_seconds: float

    @property
    def total_seconds(self) -> float:
        return self.stt_seconds + self.refine_seconds


def run(
    wav_bytes: bytes,
    preset: Preset,
    config: dict,
    provider: OpenAIProvider,
) -> Result:
    t0 = time.perf_counter()
    raw = provider.transcribe(
        wav_bytes,
        prompt=preset.stt_prompt,
        keywords=list(config.get("keywords", [])) + list(preset.keywords),
        language=config.get("language") or None,
    )
    stt_seconds = time.perf_counter() - t0

    if not preset.refine:
        return Result(raw, raw, stt_seconds, 0.0)

    t1 = time.perf_counter()
    final = provider.refine(
        raw, system_prompt=preset.system_prompt, model=preset.text_model
    )
    refine_seconds = time.perf_counter() - t1
    log.info(
        "%s: STT %.2fs + %s %.2fs",
        preset.name,
        stt_seconds,
        preset.text_model or config["text_model"],
        refine_seconds,
    )
    return Result(final, raw, stt_seconds, refine_seconds)
