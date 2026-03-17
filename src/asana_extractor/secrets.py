"""Secrets interface for loading sensitive credentials.

SecretsProvider is an ABC. Implement get_secret() to add new providers
(AWS Secrets Manager, GCP Secret Manager, etc.) without changing any
extraction code. All extraction code depends only on SecretsProvider.
"""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from dotenv import load_dotenv


class SecretsProvider(ABC):
    """Abstract interface for secrets retrieval.

    To add a new provider:
        1. Subclass SecretsProvider
        2. Implement get_secret(key: str) -> str
        3. Pass your provider to the components that need it

    No changes to extraction code required.
    """

    @abstractmethod
    def get_secret(self, key: str) -> str:
        """Retrieve a secret by key.

        Args:
            key: Secret identifier (e.g., "ASANA_PAT")

        Returns:
            The secret value as a string.

        Raises:
            SystemExit: If the secret is not found (missing required credential).
        """


class EnvSecretsProvider(SecretsProvider):
    """Loads secrets from a .env file using python-dotenv.

    Looks for the .env file in the current working directory by default.
    Set env_file to override (useful in tests).
    """

    def __init__(self, env_file: str | Path = ".env") -> None:
        self._env_file = Path(env_file)
        load_dotenv(self._env_file, override=False)

    def get_secret(self, key: str) -> str:
        value = os.environ.get(key)
        if value is None:
            print(
                f"ERROR: Required secret '{key}' not found.\n"
                f"Set {key} in your .env file at: {self._env_file.resolve()}",
                file=sys.stderr,
            )
            sys.exit(1)
        return value


def get_default_secrets_provider() -> SecretsProvider:
    """Return the default secrets provider (EnvSecretsProvider with .env)."""
    return EnvSecretsProvider()
