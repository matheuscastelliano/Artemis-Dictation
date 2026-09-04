"""Erros do Artemis.

Regra do projeto: tudo que pode dar errado durante um ditado vira um
`ArtemisError` com uma mensagem curta em portugues, pronta para ser exibida
no overlay/tray. Nada de traceback na cara do usuario, e nada derruba o app.
"""


class ArtemisError(Exception):
    """Erro esperado, com mensagem amigavel para exibir ao usuario."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        if self.detail:
            return f"{self.message} ({self.detail})"
        return self.message


class ConfigError(ArtemisError):
    """config.json / presets.json invalido ou ilegivel."""


class CredentialsError(ArtemisError):
    """API key ausente ou rejeitada pela OpenAI."""


class AudioError(ArtemisError):
    """Microfone indisponivel, ocupado ou audio invalido."""


class TranscriptionError(ArtemisError):
    """Falha na chamada de speech-to-text ou de pos-processamento."""


class OutputError(ArtemisError):
    """Falha ao copiar para o clipboard ou ao colar na aplicacao ativa."""


class HotkeyError(ArtemisError):
    """Combinacao de teclas invalida ou em conflito."""
