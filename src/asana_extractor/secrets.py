"""Secrets interface for loading sensitive credentials.

SecretsProvider is an ABC. Implement get_secret() to add new providers
(AWS Secrets Manager, GCP Secret Manager, etc.) without changing any
extraction code. All extraction code depends only on SecretsProvider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


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
