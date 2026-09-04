"""Armazenamento da API key da OpenAI.

Usa o Windows Credential Manager (via keyring, que por baixo usa DPAPI e
amarra o segredo a conta do Windows). Nada em texto plano, nada no repo.

Leitura tem fallback para a variavel de ambiente OPENAI_API_KEY, o que e
pratico durante o desenvolvimento.
"""

from __future__ import annotations

import os

import keyring

from .errors import CredentialsError

SERVICE = "ArtemisDictation"
USERNAME = "openai_api_key"


def get_api_key() -> str | None:
    """Retorna a API key, ou None se nao houver nenhuma configurada."""
    try:
        key = keyring.get_password(SERVICE, USERNAME)
    except keyring.errors.KeyringError:
        key = None
    return key or os.environ.get("OPENAI_API_KEY") or None


def require_api_key() -> str:
    key = get_api_key()
    if not key:
        raise CredentialsError(
            "API key da OpenAI nao configurada.",
            "Abra as configuracoes do Artemis ou defina OPENAI_API_KEY.",
        )
    return key


def set_api_key(value: str) -> None:
    try:
        keyring.set_password(SERVICE, USERNAME, value.strip())
    except keyring.errors.KeyringError as exc:
        raise CredentialsError(
            "Nao consegui salvar a API key no Gerenciador de Credenciais.",
            str(exc),
        ) from exc


def delete_api_key() -> None:
    try:
        keyring.delete_password(SERVICE, USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.KeyringError:
        pass


def masked(key: str | None) -> str:
    """Versao segura para exibir na UI: sk-...a1b2."""
    if not key:
        return "(nenhuma)"
    return f"{key[:3]}...{key[-4:]}" if len(key) > 12 else "(definida)"
