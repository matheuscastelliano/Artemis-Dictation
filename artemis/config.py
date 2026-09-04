r"""Configuracao persistente, fora do codigo.

Fica em %APPDATA%\ArtemisDictation\ com dois arquivos:
  config.json   -> microfone, modelos, idioma, keywords globais
  presets.json  -> os modos de ditado

Ambos sao criados a partir dos defaults abaixo na primeira execucao.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .presets import Preset

APP_NAME = "ArtemisDictation"

DEFAULT_CONFIG: dict[str, Any] = {
    # None = microfone padrao do Windows. Caso contrario, o nome do device
    # (nao o indice: indices mudam quando voce pluga/despluga hardware).
    "input_device": None,
    "sample_rate": 16000,
    # gpt-transcribe e o modelo atual da OpenAI para STT (jul/2026).
    # whisper-1 e gpt-4o-transcribe estao deprecados (desligam em 26/02/2027).
    "stt_model": "gpt-transcribe",
    "text_model": "gpt-5.6-luna",
    "language": "pt",
    # Termos que valem para todos os modos; cada preset pode somar os seus.
    "keywords": [
        "Azure DevOps",
        "Red Hat",
        "backlog",
        "sprint",
        "epico",
        "PBI",
        "deploy",
        "pipeline",
    ],
    "request_timeout": 30,
    # Abaixo disto o audio e considerado toque acidental e nem chega na API.
    "min_recording_seconds": 0.4,
    # Trava de seguranca: 25 MB / 32 KB por segundo ~= 13 min.
    "max_recording_seconds": 600,
    # Beep curto ao comecar e ao terminar de gravar.
    "sound_feedback": True,
    # Devolver o clipboard anterior depois de colar? Padrao: nao.
    # Injetar Ctrl+V nao garante que algo recebeu o texto (pode nao haver
    # campo em foco). Restaurar o clipboard nesse caso apaga o ditado.
    "restore_clipboard": False,
    # Quantos ditados ficam no menu da bandeja. So em memoria.
    "history_size": 10,
    # Quanto do texto ditado aparece no indicador ao terminar.
    # 0 desliga a previa: o indicador so confirma que ficou pronto.
    "overlay_preview_chars": 120,
}

_TRANSCREVER_STT_PROMPT = (
    "Ditado em portugues brasileiro, registro informal e coloquial, com "
    "termos tecnicos de desenvolvimento de software e gestao de produto em "
    "ingles no meio das frases. Transcreva exatamente o que foi dito, "
    "preservando giria, palavrao e o jeito de falar da pessoa. Adicione "
    "pontuacao e quebras de paragrafo onde fizer sentido. Nao reescreva, "
    "nao resuma e nao formalize."
)

_MELHORAR_SYSTEM_PROMPT = (
    "Voce recebe a transcricao de uma fala em portugues brasileiro e devolve "
    "o mesmo conteudo com melhor qualidade de escrita.\n\n"
    "Faca: corrigir erros de gramatica e de transcricao; remover repeticoes, "
    "hesitacoes e vicios de linguagem ('tipo', 'ne', 'entao assim'); melhorar "
    "a clareza e a estrutura das frases; organizar em paragrafos.\n\n"
    "Nao faca: inventar informacao que nao estava na fala; mudar o tom "
    "(se estava informal, continua informal); formalizar; adicionar saudacao, "
    "despedida ou comentario seu; explicar o que voce fez.\n\n"
    "Responda apenas com o texto final, sem aspas e sem preambulo."
)

DEFAULT_PRESETS: list[dict[str, Any]] = [
    {
        "id": "transcrever",
        "name": "Transcrever",
        "description": "Fiel a fala. So pontuacao e correcoes obvias.",
        "hotkey": "<ctrl>+<alt>+<space>",
        "trigger": "toggle",
        "stt_prompt": _TRANSCREVER_STT_PROMPT,
        "keywords": [],
        # Uma unica chamada de API: o gpt-transcribe ja pontua bem.
        "refine": False,
        "system_prompt": None,
        "text_model": None,
    },
    {
        "id": "melhorar",
        "name": "Melhorar",
        "description": "Transcreve e limpa o texto sem mudar o tom.",
        "hotkey": "<ctrl>+<alt>+1",
        "trigger": "toggle",
        "stt_prompt": _TRANSCREVER_STT_PROMPT,
        "keywords": [],
        "refine": True,
        "system_prompt": _MELHORAR_SYSTEM_PROMPT,
        "text_model": None,
    },
]


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def presets_path() -> Path:
    return config_dir() / "presets.json"


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, fallback)
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigError(
            f"Nao consegui ler {path.name}. Corrija ou apague o arquivo.",
            str(exc),
        ) from exc


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    tmp.replace(path)  # atomico: nunca deixa um config pela metade


def load_config() -> dict[str, Any]:
    """Le config.json, completando com os defaults as chaves que faltarem."""
    data = _read_json(config_path(), DEFAULT_CONFIG)
    if not isinstance(data, dict):
        raise ConfigError("config.json deveria conter um objeto JSON.")
    return {**DEFAULT_CONFIG, **data}


def save_config(config: dict[str, Any]) -> None:
    _write_json(config_path(), config)


def load_presets() -> list[Preset]:
    data = _read_json(presets_path(), DEFAULT_PRESETS)
    if not isinstance(data, list) or not data:
        raise ConfigError("presets.json deveria conter uma lista nao vazia.")
    presets = []
    for raw in data:
        try:
            presets.append(Preset.from_dict(raw))
        except (TypeError, ValueError) as exc:
            raise ConfigError("Preset invalido em presets.json.", str(exc)) from exc
    return presets


def save_presets(presets: list[Preset]) -> None:
    _write_json(presets_path(), [p.to_dict() for p in presets])
