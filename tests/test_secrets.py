"""Tests for the secrets interface."""

import pytest

from asana_extractor.secrets import SecretsProvider


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
