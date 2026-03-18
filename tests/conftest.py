"""Shared pytest fixtures for asana_extractor tests."""

from __future__ import annotations

import pytest
from aioresponses import aioresponses as _aioresponses

from asana_extractor.client import AsanaClient
from asana_extractor.secrets import SecretsProvider


class FakePAT(SecretsProvider):
    """Fake secrets provider returning a static PAT token for tests."""

    def get_secret(self, key: str) -> str:
        return "fake-pat-token"


@pytest.fixture
def fake_pat() -> FakePAT:
    """Return a FakePAT secrets provider."""
    return FakePAT()


@pytest.fixture
def mock_api() -> _aioresponses:
    """Yield an aioresponses context that intercepts all aiohttp requests."""
    with _aioresponses() as m:
        yield m  # type: ignore[misc]


@pytest.fixture
async def asana_client(fake_pat: FakePAT) -> AsanaClient:
    """Yield an entered AsanaClient using FakePAT credentials."""
    async with AsanaClient(fake_pat) as client:
        yield client  # type: ignore[misc]
