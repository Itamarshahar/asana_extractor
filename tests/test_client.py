"""Unit tests for AsanaClient — auth, pagination, retry, and error classification.

Uses aioresponses to intercept aiohttp calls without hitting the real API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
import tenacity
from aioresponses import aioresponses as _aioresponses

from asana_extractor.client import BASE_URL, AsanaClient
from asana_extractor.exceptions import AsanaPermanentError, AsanaTransientError
from tests.conftest import FakePAT


def _url(path: str) -> str:
    """Build a full Asana API URL from a path (strips leading slash)."""
    return BASE_URL + path.lstrip("/")


class TestAsanaClientAuth:
    async def test_auth_header_sent_on_request(self, mock_api: _aioresponses) -> None:
        """Authorization: Bearer header is attached to every request."""
        mock_api.get(_url("/users/me"), payload={"data": {"gid": "me"}})
        async with AsanaClient(FakePAT()) as client:
            result = await client.get("/users/me")

        assert result == {"gid": "me"}
        from yarl import URL

        key = ("GET", URL(_url("/users/me")))
        calls = mock_api.requests[key]
        assert len(calls) == 1
        # Session-level headers are merged into request headers by aioresponses
        headers = calls[0].kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer fake-pat-token"

    async def test_runtime_error_outside_context_manager(self) -> None:
        """Calling get() without __aenter__ raises RuntimeError."""
        client = AsanaClient(FakePAT())
        with pytest.raises(RuntimeError, match="not initialized"):
            await client.get("/users/me")


class TestAsanaClientPagination:
    async def test_single_page_no_next(self, mock_api: _aioresponses) -> None:
        """Single-page response yields exactly the entities in 'data'."""
        # paginated_get adds limit=100 as query param; include it in the mocked URL
        mock_api.get(
            _url("/users") + "?limit=100",
            payload={
                "data": [{"gid": "u1"}, {"gid": "u2"}],
                "next_page": None,
            },
        )
        async with AsanaClient(FakePAT()) as client:
            entities = [e async for e in client.paginated_get("/users")]

        assert entities == [{"gid": "u1"}, {"gid": "u2"}]

    async def test_multi_page_follows_offset(self, mock_api: _aioresponses) -> None:
        """Multi-page response follows next_page.offset and yields all entities."""
        # Page 1 — returns next_page with offset
        mock_api.get(
            _url("/users") + "?limit=100",
            payload={
                "data": [{"gid": "u1"}],
                "next_page": {"offset": "abc", "uri": _url("/users?offset=abc")},
            },
        )
        # Page 2 — includes offset param in addition to limit
        mock_api.get(
            _url("/users") + "?limit=100&offset=abc",
            payload={
                "data": [{"gid": "u2"}],
                "next_page": None,
            },
        )
        async with AsanaClient(FakePAT()) as client:
            entities = [e async for e in client.paginated_get("/users")]

        assert entities == [{"gid": "u1"}, {"gid": "u2"}]

    async def test_empty_data_yields_nothing(self, mock_api: _aioresponses) -> None:
        """Empty 'data' array yields zero entities."""
        mock_api.get(
            _url("/users") + "?limit=100",
            payload={"data": [], "next_page": None},
        )
        async with AsanaClient(FakePAT()) as client:
            entities = [e async for e in client.paginated_get("/users")]

        assert entities == []


class TestAsanaClientErrors:
    async def test_5xx_retries_then_raises_transient(self, mock_api: _aioresponses) -> None:
        """5xx errors trigger tenacity retry; after 3 attempts raises AsanaTransientError."""
        # Register 3 failures (stop_after_attempt=3 means 3 total attempts)
        for _ in range(3):
            mock_api.get(_url("/test"), status=500, body="Server Error")

        with patch.object(tenacity.nap, "sleep", AsyncMock()):
            async with AsanaClient(FakePAT()) as client:
                with pytest.raises(AsanaTransientError) as exc_info:
                    await client.get("/test")

        assert exc_info.value.status_code == 500

    async def test_4xx_raises_permanent_no_retry(self, mock_api: _aioresponses) -> None:
        """4xx (non-429) raises AsanaPermanentError immediately with no retry."""
        mock_api.get(_url("/test"), status=403, body="Forbidden")

        with patch.object(tenacity.nap, "sleep", AsyncMock()):
            async with AsanaClient(FakePAT()) as client:
                with pytest.raises(AsanaPermanentError) as exc_info:
                    await client.get("/test")

        assert exc_info.value.status_code == 403
        from yarl import URL

        key = ("GET", URL(_url("/test")))
        # Only 1 request made — permanent errors are never retried
        assert len(mock_api.requests[key]) == 1

    async def test_429_raises_transient_not_retried_by_tenacity(
        self, mock_api: _aioresponses
    ) -> None:
        """429 raises AsanaTransientError immediately; tenacity does NOT retry it."""
        mock_api.get(_url("/test"), status=429, body="Too Many Requests")

        with patch.object(tenacity.nap, "sleep", AsyncMock()):
            async with AsanaClient(FakePAT()) as client:
                with pytest.raises(AsanaTransientError) as exc_info:
                    await client.get("/test")

        assert exc_info.value.status_code == 429
        from yarl import URL

        key = ("GET", URL(_url("/test")))
        # Only 1 request — 429 is excluded from _is_retryable
        assert len(mock_api.requests[key]) == 1

    async def test_connection_error_retried(self, mock_api: _aioresponses) -> None:
        """Connection errors trigger tenacity retry; after 3 attempts raises AsanaTransientError."""
        for _ in range(3):
            mock_api.get(
                _url("/test"),
                exception=aiohttp.ClientConnectionError("connection refused"),
            )

        with patch.object(tenacity.nap, "sleep", AsyncMock()):
            async with AsanaClient(FakePAT()) as client:
                with pytest.raises(AsanaTransientError):
                    await client.get("/test")
