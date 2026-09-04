"""Ponte com a API da OpenAI: speech-to-text e pos-processamento de texto.

Este e o unico modulo que sabe que o provedor e a OpenAI. Trocar de provedor
ou de modelo depois significa mexer aqui, e so aqui.

Sobre os modelos (pesquisa em set/2026):
  gpt-transcribe  -> STT recomendado. Metade do word error rate do whisper-1
                     e mais barato ($0.0045/min). Aceita `prompt`, `keywords`
                     e `languages`.
  whisper-1       -> deprecado, desliga em 26/02/2027. So aceita `language`
                     (singular) e `prompt`.
  gpt-5.6-luna    -> modelo de texto barato, usado nos modos que refinam.

Como os parametros novos (`keywords`, `languages`) nao existem em SDKs
antigos nem nos modelos legados, as chamadas degradam sozinhas: tenta o
conjunto completo e vai removendo o que o servidor/SDK recusar.
"""

from __future__ import annotations

import logging

import openai

from ..errors import CredentialsError, TranscriptionError

log = logging.getLogger(__name__)

# Modelos que ainda usam `language` (singular) em vez de `languages`.
_LEGACY_STT_MODELS = {"whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"}


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        stt_model: str = "gpt-transcribe",
        text_model: str = "gpt-5.6-luna",
        timeout: float = 30.0,
    ):
        self.stt_model = stt_model
        self.text_model = text_model
        self._client = openai.OpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=1,  # o usuario esta esperando: falhar rapido e melhor
        )
        # Lembra o que este modelo aceitou da ultima vez, para nao pagar o
        # custo da degradacao a cada ditado.
        self._unsupported: set[str] = set()

    # ---------------------------------------------------------------- STT

    def transcribe(
        self,
        wav_bytes: bytes,
        *,
        prompt: str = "",
        keywords: list[str] | None = None,
        language: str | None = "pt",
    ) -> str:
        base = {
            "model": self.stt_model,
            "file": ("audio.wav", wav_bytes, "audio/wav"),
            "response_format": "text",
        }
        extras: dict[str, object] = {}
        if prompt:
            extras["prompt"] = prompt
        if keywords:
            extras["keywords"] = list(keywords)
        if language:
            if self.stt_model in _LEGACY_STT_MODELS:
                extras["language"] = language
            else:
                extras["languages"] = [language]

        result = self._call_with_degradation(base, extras)
        text = result if isinstance(result, str) else getattr(result, "text", "")
        text = (text or "").strip()
        if not text:
            raise TranscriptionError(
                "Nao entendi nada no audio.",
                "A transcricao voltou vazia. Fale mais perto do microfone.",
            )
        return text

    def _call_with_degradation(self, base: dict, extras: dict):
        """Chama a API removendo os parametros que ela recusar.

        Mantem o registro do que nao funcionou para os proximos ditados.
        """
        optional = [k for k in extras if k not in self._unsupported]
        while True:
            params = {**base, **{k: extras[k] for k in optional}}
            try:
                return self._client.audio.transcriptions.create(**params)
            except TypeError as exc:
                # O SDK instalado nao conhece o parametro.
                dropped = self._drop_offender(optional, str(exc))
                if dropped is None:
                    raise self._wrap(exc)
                log.warning("SDK nao aceita '%s' no STT; seguindo sem ele.", dropped)
            except openai.BadRequestError as exc:
                # O modelo nao aceita o parametro.
                dropped = self._drop_offender(optional, str(exc))
                if dropped is None:
                    raise self._wrap(exc)
                log.warning(
                    "Modelo %s nao aceita '%s'; seguindo sem ele.",
                    base["model"],
                    dropped,
                )
            except Exception as exc:
                raise self._wrap(exc)

    def _drop_offender(self, optional: list[str], message: str) -> str | None:
        """Remove da lista o parametro citado no erro; senao, o ultimo."""
        for name in optional:
            if name in message:
                optional.remove(name)
                self._unsupported.add(name)
                return name
        if optional:
            name = optional.pop()
            self._unsupported.add(name)
            return name
        return None

    # ------------------------------------------------------ pos-processo

    def refine(self, text: str, *, system_prompt: str, model: str | None = None) -> str:
        try:
            response = self._client.chat.completions.create(
                model=model or self.text_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
            )
        except Exception as exc:
            raise self._wrap(exc)

        content = (response.choices[0].message.content or "").strip()
        if not content:
            # Melhor devolver o texto bruto do que devolver nada ao usuario.
            log.warning("Pos-processamento voltou vazio; usando o texto do STT.")
            return text
        return content

    # ------------------------------------------------------------ erros

    @staticmethod
    def _wrap(exc: Exception) -> Exception:
        """Traduz erros da OpenAI em mensagens que cabem num toast."""
        if isinstance(exc, openai.AuthenticationError):
            return CredentialsError(
                "API key da OpenAI invalida ou revogada.",
                "Confira a chave nas configuracoes do Artemis.",
            )
        if isinstance(exc, openai.PermissionDeniedError):
            return CredentialsError(
                "Sua conta nao tem acesso a este modelo.", str(exc)
            )
        if isinstance(exc, openai.RateLimitError):
            return TranscriptionError(
                "Limite de uso da OpenAI atingido. Tente de novo em instantes."
            )
        if isinstance(exc, openai.APITimeoutError):
            return TranscriptionError(
                "A OpenAI demorou demais para responder.",
                "Ditado muito longo ou conexao lenta.",
            )
        if isinstance(exc, openai.APIConnectionError):
            return TranscriptionError(
                "Sem conexao com a OpenAI.", "Verifique sua internet."
            )
        if isinstance(exc, openai.APIStatusError):
            return TranscriptionError(
                f"A OpenAI retornou erro {exc.status_code}.", str(exc)
            )
        return TranscriptionError("Falha inesperada ao processar o audio.", str(exc))
