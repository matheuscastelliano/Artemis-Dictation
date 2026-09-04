"""Presets = os "modos" de ditado.

Um modo nao e codigo: e uma entrada em presets.json. O nucleo do app so
enxerga estes campos, entao criar "Formal", "Resumir" ou "E-mail" depois e
editar um arquivo, nao mexer no pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

TRIGGERS = ("toggle", "hold")


@dataclass
class Preset:
    id: str
    name: str
    hotkey: str
    description: str = ""
    # "toggle": aperta para gravar, aperta de novo para parar.
    # "hold": grava enquanto a tecla estiver pressionada.
    trigger: str = "toggle"
    # Contexto livre passado ao modelo de transcricao (estilo, dominio).
    stt_prompt: str = ""
    # Termos que o STT costuma errar. Somados aos keywords globais do config.
    keywords: list[str] = field(default_factory=list)
    # False = o texto do STT vai direto para o clipboard (uma chamada so).
    # True  = passa por um LLM com o system_prompt abaixo.
    refine: bool = False
    system_prompt: str | None = None
    # None = usa o text_model global do config.json.
    text_model: str | None = None

    def __post_init__(self) -> None:
        if self.trigger not in TRIGGERS:
            raise ValueError(
                f"preset '{self.id}': trigger '{self.trigger}' invalido; "
                f"use um de {TRIGGERS}"
            )
        if self.refine and not self.system_prompt:
            raise ValueError(
                f"preset '{self.id}': refine=true exige um system_prompt"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Preset":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
