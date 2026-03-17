"""Tests for the secrets interface."""

from pathlib import Path

import pytest

from asana_extractor.secrets import (
    EnvSecretsProvider,
    SecretsProvider,
    get_default_secrets_provider,
)


def test_env_provider_reads_secret(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ASANA_PAT=test-pat-value-123\n")
    provider = EnvSecretsProvider(env_file=env_file)
    assert provider.get_secret("ASANA_PAT") == "test-pat-value-123"


def test_env_provider_missing_secret_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("")  # empty — no PAT
    monkeypatch.delenv("ASANA_PAT", raising=False)
    provider = EnvSecretsProvider(env_file=env_file)
    with pytest.raises(SystemExit) as exc_info:
        provider.get_secret("ASANA_PAT")
    assert exc_info.value.code == 1


def test_secrets_provider_is_abstract() -> None:
    """Cannot instantiate SecretsProvider directly."""
    with pytest.raises(TypeError):
        SecretsProvider()  # type: ignore[abstract]


def test_custom_provider_subclass_works() -> None:
    """New providers just subclass SecretsProvider."""

    class HardcodedProvider(SecretsProvider):
        def get_secret(self, key: str) -> str:
            return f"hardcoded-{key}"

    provider = HardcodedProvider()
    assert isinstance(provider, SecretsProvider)
    assert provider.get_secret("ASANA_PAT") == "hardcoded-ASANA_PAT"


def test_get_default_secrets_provider_returns_env_provider() -> None:
    provider = get_default_secrets_provider()
    assert isinstance(provider, SecretsProvider)
    assert isinstance(provider, EnvSecretsProvider)
