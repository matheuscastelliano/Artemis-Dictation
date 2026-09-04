"""Teste de fumaca da Etapa 1: microfone + OpenAI, sem hotkey e sem UI.

    python -m artemis.smoketest            # grava 5s e transcreve
    python -m artemis.smoketest --devices  # so lista os microfones
    python -m artemis.smoketest --seconds 8 --preset melhorar
"""

from __future__ import annotations

import argparse
import sys
import time

from .audio import AudioRecorder, list_input_devices, wav_duration
from .config import load_config, load_presets, config_dir
from .errors import ArtemisError
from .providers.openai_provider import OpenAIProvider
from .secrets_store import require_api_key, masked, get_api_key


def main() -> int:
    parser = argparse.ArgumentParser(prog="artemis.smoketest")
    parser.add_argument("--devices", action="store_true", help="lista microfones e sai")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--preset", default="transcrever")
    args = parser.parse_args()

    try:
        print(f"Config em: {config_dir()}")
        config = load_config()
        presets = {p.id: p for p in load_presets()}

        print("\nMicrofones de entrada:")
        for dev in list_input_devices():
            flag = "  <- padrao" if dev["default"] else ""
            print(f"  [{dev['index']}] {dev['name']}{flag}")
        if args.devices:
            return 0

        preset = presets.get(args.preset)
        if preset is None:
            print(f"\nPreset '{args.preset}' nao existe. Ha: {list(presets)}")
            return 2

        print(f"\nAPI key: {masked(get_api_key())}")
        api_key = require_api_key()

        recorder = AudioRecorder(
            sample_rate=config["sample_rate"], device=config["input_device"]
        )
        print(f"\nGravando {args.seconds:.0f}s. Fale agora...")
        recorder.start()
        time.sleep(args.seconds)
        wav = recorder.stop()
        seconds = wav_duration(wav, config["sample_rate"])
        print(f"Capturado: {len(wav)/1024:.0f} KB / {seconds:.1f}s")

        provider = OpenAIProvider(
            api_key=api_key,
            stt_model=config["stt_model"],
            text_model=config["text_model"],
            timeout=config["request_timeout"],
        )

        t0 = time.perf_counter()
        raw = provider.transcribe(
            wav,
            prompt=preset.stt_prompt,
            keywords=config["keywords"] + preset.keywords,
            language=config["language"],
        )
        t_stt = time.perf_counter() - t0
        print(f"\n--- STT ({config['stt_model']}, {t_stt:.2f}s) ---\n{raw}")

        if preset.refine:
            t0 = time.perf_counter()
            final = provider.refine(
                raw,
                system_prompt=preset.system_prompt,
                model=preset.text_model,
            )
            t_llm = time.perf_counter() - t0
            model = preset.text_model or config["text_model"]
            print(f"\n--- {preset.name} ({model}, {t_llm:.2f}s) ---\n{final}")

        return 0

    except ArtemisError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
