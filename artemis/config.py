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

from . import i18n
from .errors import ConfigError
from .presets import Preset

APP_NAME = "ArtemisDictation"

# Como o indicador flutuante se comporta ao final de um ditado.
OVERLAY_MODES = ("always", "errors", "never")

DEFAULT_CONFIG: dict[str, Any] = {
    # None = microfone padrao do Windows. Caso contrario, o nome do device
    # (nao o indice: indices mudam quando voce pluga/despluga hardware).
    "input_device": None,
    "sample_rate": 16000,
    # gpt-transcribe e o modelo atual da OpenAI para STT (jul/2026).
    # whisper-1 e gpt-4o-transcribe estao deprecados (desligam em 26/02/2027).
    "stt_model": "gpt-transcribe",
    "text_model": "gpt-5.6-luna",
    # Idioma da FALA, enviado ao modelo de transcricao.
    "language": "pt",
    # Idioma da INTERFACE. "auto" segue o idioma do Windows.
    "ui_language": i18n.AUTO,
    # Termos que valem para todos os modos; cada preset pode somar os seus.
    "keywords": [],
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
    # always | errors | never - ver OVERLAY_MODES.
    "overlay_mode": "always",
    # Quanto do texto ditado aparece no indicador ao terminar.
    # 0 desliga a previa: o indicador so confirma que ficou pronto.
    "overlay_preview_chars": 120,
    # Iniciar junto com o Windows (chave Run do usuario atual).
    "start_with_windows": False,
}


def default_presets() -> list[dict[str, Any]]:
    """Os dois modos iniciais, no idioma da interface.

    Sao gerados na hora, e nao constantes de modulo, porque quem instala o
    Artemis com a interface em ingles deve receber prompts em ingles.
    """
    stt_prompt = i18n.t("preset.stt_prompt")
    return [
        {
            "id": "transcribe",
            "name": i18n.t("preset.transcribe.name"),
            "description": i18n.t("preset.transcribe.description"),
            "hotkey": "<ctrl>+<alt>+<space>",
            "trigger": "toggle",
            "stt_prompt": stt_prompt,
            "keywords": [],
            # Uma unica chamada de API: o gpt-transcribe ja pontua bem.
            "refine": False,
            "system_prompt": None,
            "text_model": None,
        },
        {
            "id": "improve",
            "name": i18n.t("preset.improve.name"),
            "description": i18n.t("preset.improve.description"),
            "hotkey": "<ctrl>+<alt>+1",
            "trigger": "toggle",
            "stt_prompt": stt_prompt,
            "keywords": [],
            "refine": True,
            "system_prompt": i18n.t("preset.improve.system_prompt"),
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
            i18n.t("err.config_read", file=path.name), str(exc)
        ) from exc


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    tmp.replace(path)  # atomico: nunca deixa um config pela metade


def load_config() -> dict[str, Any]:
    """Le config.json, completando com os defaults as chaves que faltarem.

    Define o idioma da interface como efeito colateral, para que tudo que
    vier depois - inclusive os presets padrao - ja saia traduzido.
    """
    path = config_path()
    existed = path.exists()  # antes do _read_json, que cria o arquivo
    data = _read_json(path, DEFAULT_CONFIG)
    if not isinstance(data, dict):
        raise ConfigError(i18n.t("err.config_object"))
    config = {**DEFAULT_CONFIG, **data}

    # Instalacao anterior ao suporte a idiomas: a interface era portugues.
    # Deixar cair no "auto" mudaria o idioma de quem ja usava o app so
    # porque o Windows esta em ingles. Grava a escolha uma unica vez.
    if existed and "ui_language" not in data:
        config["ui_language"] = "pt"
        save_config(config)

    i18n.set_language(config.get("ui_language"))
    if config.get("overlay_mode") not in OVERLAY_MODES:
        config["overlay_mode"] = "always"
    return config


def save_config(config: dict[str, Any]) -> None:
    _write_json(config_path(), config)


def load_presets() -> list[Preset]:
    data = _read_json(presets_path(), default_presets())
    if not isinstance(data, list) or not data:
        raise ConfigError(i18n.t("err.presets_list"))
    presets = []
    for raw in data:
        try:
            presets.append(Preset.from_dict(raw))
        except (TypeError, ValueError) as exc:
            raise ConfigError(i18n.t("err.preset_invalid"), str(exc)) from exc
    return presets


def save_presets(presets: list[Preset]) -> None:
    _write_json(presets_path(), [p.to_dict() for p in presets])
