"""Tests for RateLimitedClient — rate-limited drop-in replacement for AsanaClient."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from asana_extractor.exceptions import AsanaPermanentError
from asana_extractor.rate_limited_client import RateLimitedClient
from asana_extractor.secrets import SecretsProvider


class FakePAT(SecretsProvider):
    def get_secret(self, key: str) -> str:
        return "fake-pat-token"


def make_mock_response(
    status: int,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock aiohttp response context manager."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=body or {})
    mock_resp.text = AsyncMock(return_value="error body")
    mock_resp.headers = headers or {}
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


async def make_client() -> RateLimitedClient:
    """Create and enter a RateLimitedClient (caller must __aexit__ manually)."""
    client = RateLimitedClient(FakePAT())
    await client.__aenter__()
    return client


class TestRateLimitedClientLifecycle:
    async def test_context_manager_enters_and_exits(self) -> None:
        async with RateLimitedClient(FakePAT()) as client:
            assert client._client._session is not None
        assert client._client._session is None

    async def test_delegates_to_inner_client_on_success(self) -> None:
        async with RateLimitedClient(FakePAT()) as client:
            mock_resp = make_mock_response(200, {"data": {"gid": "123", "name": "Test"}})
            with patch.object(client._client._session, "get", return_value=mock_resp):
                result = await client.get("/users/me", workspace_gid="ws1")

        assert result == {"gid": "123", "name": "Test"}


class TestRateLimitedClientRateLimiting:
    async def test_get_acquires_semaphore_and_workspace_token(self) -> None:
        """Verify semaphore and workspace token are acquired before request."""
        from asana_extractor.rate_limiter import GlobalRequestSemaphore

        async with RateLimitedClient(FakePAT()) as client:
            # Override rate so bucket is empty immediately
            bucket = client._registry.get_limiter("ws1")
            bucket._tokens = 0.0

            semaphore_entered = False
            token_acquired = False

            # Capture original methods before patching
            original_semaphore_enter = GlobalRequestSemaphore.__aenter__
            original_acquire = bucket.acquire

            async def track_semaphore_enter(self_: object) -> object:
                nonlocal semaphore_entered
                semaphore_entered = True
                return await original_semaphore_enter(self_)  # type: ignore[arg-type]

            async def track_acquire() -> None:
                nonlocal token_acquired
                # Give it a token so it doesn't block
                bucket._tokens = 1.0
                await original_acquire()
                token_acquired = True

            mock_resp = make_mock_response(200, {"data": {"gid": "u1"}})
            with patch.object(client._client._session, "get", return_value=mock_resp):
                with patch.object(GlobalRequestSemaphore, "__aenter__", track_semaphore_enter):
                    with patch.object(bucket, "acquire", track_acquire):
                        await client.get("/users/me", workspace_gid="ws1")

        assert semaphore_entered
        assert token_acquired

    async def test_record_success_called_after_successful_get(self) -> None:
        async with RateLimitedClient(FakePAT()) as client:
            state = client._get_429_state("ws1")
            state._consecutive_429s = 1  # Set non-zero to verify reset

            mock_resp = make_mock_response(200, {"data": {"gid": "u1"}})
            with patch.object(client._client._session, "get", return_value=mock_resp):
                await client.get("/users/me", workspace_gid="ws1")

        assert state._consecutive_429s == 0

    async def test_workspace_none_uses_global_key(self) -> None:
        """workspace_gid=None should not crash — uses __global__ key."""
        async with RateLimitedClient(FakePAT()) as client:
            mock_resp = make_mock_response(200, {"data": {"gid": "u1"}})
            with patch.object(client._client._session, "get", return_value=mock_resp):
                result = await client.get("/users/me")  # no workspace_gid

        assert result == {"gid": "u1"}


class TestRateLimitedClient429Handling:
    async def test_429_triggers_record_429_and_retry(self) -> None:
        """On 429, client pauses via record_429 then retries once."""
        async with RateLimitedClient(FakePAT()) as client:
            call_count = 0

            def make_resp(call: int) -> MagicMock:
                if call == 1:
                    return make_mock_response(429, {})
                return make_mock_response(200, {"data": {"gid": "ok"}})

            def fake_get(url: str, **kwargs: object) -> MagicMock:
                nonlocal call_count
                call_count += 1
                return make_resp(call_count)

            record_429_called = False
            state = client._get_429_state("ws1")

            async def tracking_record_429(**kwargs: object) -> None:
                nonlocal record_429_called
                record_429_called = True
                # Don't actually sleep
                state._bucket.reset_tokens()
                state._consecutive_429s += 1

            with patch.object(client._client._session, "get", side_effect=fake_get):
                with patch.object(state, "record_429", tracking_record_429):
                    result = await client.get("/test", workspace_gid="ws1")

        assert record_429_called
        assert call_count == 2
        assert result == {"gid": "ok"}

    async def test_429_with_retry_after_header_passes_value_to_record_429(self) -> None:
        """When API returns 429 with Retry-After: 30, record_429 receives retry_after=30."""
        async with RateLimitedClient(FakePAT()) as client:
            call_count = 0

            def make_resp(call: int) -> MagicMock:
                if call == 1:
                    return make_mock_response(429, {}, headers={"Retry-After": "30"})
                return make_mock_response(200, {"data": {"gid": "ok"}})

            def fake_get(url: str, **kwargs: object) -> MagicMock:
                nonlocal call_count
                call_count += 1
                return make_resp(call_count)

            captured_retry_after: list[float | None] = []
            state = client._get_429_state("ws1")

            async def tracking_record_429(**kwargs: object) -> None:
                captured_retry_after.append(kwargs.get("retry_after"))
                state._bucket.reset_tokens()
                state._consecutive_429s += 1

            with patch.object(client._client._session, "get", side_effect=fake_get):
                with patch.object(state, "record_429", tracking_record_429):
                    await client.get("/test", workspace_gid="ws1")

        assert len(captured_retry_after) == 1
        assert captured_retry_after[0] == 30.0

    async def test_429_without_retry_after_header_passes_none_to_record_429(self) -> None:
        """When API returns 429 without Retry-After, record_429 receives retry_after=None."""
        async with RateLimitedClient(FakePAT()) as client:
            call_count = 0

            def make_resp(call: int) -> MagicMock:
                if call == 1:
                    return make_mock_response(429, {})
                return make_mock_response(200, {"data": {"gid": "ok"}})

            def fake_get(url: str, **kwargs: object) -> MagicMock:
                nonlocal call_count
                call_count += 1
                return make_resp(call_count)

            captured_retry_after: list[float | None] = []
            state = client._get_429_state("ws1")

            async def tracking_record_429(**kwargs: object) -> None:
                captured_retry_after.append(kwargs.get("retry_after"))
                state._bucket.reset_tokens()
                state._consecutive_429s += 1

            with patch.object(client._client._session, "get", side_effect=fake_get):
                with patch.object(state, "record_429", tracking_record_429):
                    await client.get("/test", workspace_gid="ws1")

        assert len(captured_retry_after) == 1
        assert captured_retry_after[0] is None

    async def test_429_with_malformed_retry_after_passes_none_to_record_429(self) -> None:
        """When API returns 429 with malformed Retry-After, record_429 receives retry_after=None."""
        async with RateLimitedClient(FakePAT()) as client:
            call_count = 0

            def make_resp(call: int) -> MagicMock:
                if call == 1:
                    return make_mock_response(429, {}, headers={"Retry-After": "abc"})
                return make_mock_response(200, {"data": {"gid": "ok"}})

            def fake_get(url: str, **kwargs: object) -> MagicMock:
                nonlocal call_count
                call_count += 1
                return make_resp(call_count)

            captured_retry_after: list[float | None] = []
            state = client._get_429_state("ws1")

            async def tracking_record_429(**kwargs: object) -> None:
                captured_retry_after.append(kwargs.get("retry_after"))
                state._bucket.reset_tokens()
                state._consecutive_429s += 1

            with patch.object(client._client._session, "get", side_effect=fake_get):
                with patch.object(state, "record_429", tracking_record_429):
                    await client.get("/test", workspace_gid="ws1")

        assert len(captured_retry_after) == 1
        assert captured_retry_after[0] is None

    async def test_permanent_error_propagates_without_retry(self) -> None:
        """4xx errors (not 429) propagate immediately without retry."""
        async with RateLimitedClient(FakePAT()) as client:
            call_count = 0

            def fake_get(url: str, **kwargs: object) -> MagicMock:
                nonlocal call_count
                call_count += 1
                return make_mock_response(404, {})

            import tenacity

            async def instant_sleep(s: float) -> None:
                pass

            with patch.object(client._client._session, "get", side_effect=fake_get):
                with patch.object(tenacity.nap, "sleep", instant_sleep):
                    with pytest.raises(AsanaPermanentError) as exc_info:
                        await client.get("/missing", workspace_gid="ws1")

        assert exc_info.value.status_code == 404
        assert call_count == 1  # no retry for permanent errors

    async def test_workspace_isolation(self) -> None:
        """Workspace A being paused does not delay Workspace B."""
        async with RateLimitedClient(FakePAT()) as client:
            # Pause workspace A for 60 seconds
            state_a = client._get_429_state("ws_a")
            state_a._pause_until = asyncio.get_event_loop().time() + 60.0

            # Workspace B should complete without waiting
            mock_resp = make_mock_response(200, {"data": {"gid": "ws_b_result"}})
            with patch.object(client._client._session, "get", return_value=mock_resp):
                result = await asyncio.wait_for(
                    client.get("/users/me", workspace_gid="ws_b"),
                    timeout=1.0,  # Would timeout if blocked by ws_a's pause
                )

        assert result == {"gid": "ws_b_result"}


class TestRateLimitedClientPaginatedGet:
    async def test_paginated_get_yields_entities(self) -> None:
        """paginated_get yields entities across multiple pages."""
        # Mock the HTTP session to return envelope responses with pagination.
        # Page 1 returns next_page with offset; page 2 terminates.
        import json

        page1_body = json.dumps(
            {
                "data": [{"gid": "1"}],
                "next_page": {"offset": "abc", "uri": "/users?offset=abc"},
            }
        )
        page2_body = json.dumps(
            {
                "data": [{"gid": "2"}],
                "next_page": None,
            }
        )
        call_idx = 0

        def fake_session_get(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_idx
            body = page1_body if call_idx == 0 else page2_body
            call_idx += 1
            resp = MagicMock()
            resp.status = 200
            resp.json = AsyncMock(return_value=json.loads(body))
            resp.text = AsyncMock(return_value=body)
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        async with RateLimitedClient(FakePAT()) as client:
            with patch.object(client._client._session, "get", side_effect=fake_session_get):
                results = []
                async for entity in client.paginated_get("/users", workspace_gid="ws1"):
                    results.append(entity)

        assert results == [{"gid": "1"}, {"gid": "2"}]

    async def test_paginated_get_acquires_bucket_per_page(self) -> None:
        """bucket.acquire() is called once per page, not once per paginated_get call.

        For a 3-page result set, acquire() must be called 3 times — proving
        per-page rate limiting (not per-call).
        """
        import json

        # 3-page response: page1 → page2 → page3
        pages = [
            {"data": [{"gid": "1"}], "next_page": {"offset": "off1", "uri": "/u?offset=off1"}},
            {"data": [{"gid": "2"}], "next_page": {"offset": "off2", "uri": "/u?offset=off2"}},
            {"data": [{"gid": "3"}], "next_page": None},
        ]
        call_idx = 0

        def fake_session_get(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_idx
            body = pages[call_idx]
            call_idx += 1
            resp = MagicMock()
            resp.status = 200
            resp.json = AsyncMock(return_value=body)
            resp.text = AsyncMock(return_value=json.dumps(body))
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        async with RateLimitedClient(FakePAT()) as client:
            bucket = client._registry.get_limiter("ws1")
            original_acquire = bucket.acquire
            acquire_count = 0

            async def counting_acquire() -> None:
                nonlocal acquire_count
                acquire_count += 1
                await original_acquire()

            with patch.object(client._client._session, "get", side_effect=fake_session_get):
                with patch.object(bucket, "acquire", counting_acquire):
                    results = []
                    async for entity in client.paginated_get("/users", workspace_gid="ws1"):
                        results.append(entity)

        # 3 pages → 3 acquire() calls
        assert acquire_count == 3
        assert results == [{"gid": "1"}, {"gid": "2"}, {"gid": "3"}]


class TestSharedGlobalSemaphore:
    """Tests verifying GlobalRequestSemaphore is shared across clients."""

    async def test_shared_semaphore_is_same_object(self) -> None:
        """Two clients with the same semaphore share one object (identity check)."""
        from asana_extractor.rate_limiter import GlobalRequestSemaphore

        shared = GlobalRequestSemaphore()
        client_a = RateLimitedClient(FakePAT(), global_semaphore=shared)
        client_b = RateLimitedClient(FakePAT(), global_semaphore=shared)

        assert client_a._semaphore is client_b._semaphore
        assert client_a._semaphore is shared

    async def test_default_creates_independent_semaphore(self) -> None:
        """Without explicit semaphore, each client gets its own (backward compat)."""
        client_a = RateLimitedClient(FakePAT())
        client_b = RateLimitedClient(FakePAT())

        assert client_a._semaphore is not client_b._semaphore

    async def test_orchestrator_shares_semaphore_across_workspace_clients(
        self,
    ) -> None:
        """WorkspaceOrchestrator injects the same semaphore into all clients."""
        from asana_extractor.config import Settings
        from asana_extractor.orchestrator import WorkspaceOrchestrator
        from asana_extractor.rate_limiter import GlobalRequestSemaphore
        from asana_extractor.tenant import TenantConfig

        settings = Settings(
            output_dir="output",
            extraction_interval=300,
            max_concurrent_workspaces=5,
        )
        orchestrator = WorkspaceOrchestrator(settings)

        # Capture semaphore args passed to RateLimitedClient during run()
        captured_semaphores: list[GlobalRequestSemaphore | None] = []
        original_init = RateLimitedClient.__init__

        def capturing_init(
            self: RateLimitedClient,
            secrets_provider: object,
            global_semaphore: GlobalRequestSemaphore | None = None,
        ) -> None:
            captured_semaphores.append(global_semaphore)
            original_init(self, secrets_provider, global_semaphore=global_semaphore)  # type: ignore[arg-type]

        tenants = [
            TenantConfig(workspace_gid="ws1", pat="pat1"),
            TenantConfig(workspace_gid="ws2", pat="pat2"),
            TenantConfig(workspace_gid="ws3", pat="pat3"),
        ]

        with patch.object(RateLimitedClient, "__init__", capturing_init):
            with patch(
                "asana_extractor.extractors.extract_workspace",
                new_callable=AsyncMock,
            ):
                with patch.object(
                    RateLimitedClient, "__aenter__", AsyncMock(return_value=MagicMock())
                ):
                    with patch.object(
                        RateLimitedClient, "__aexit__", AsyncMock(return_value=False)
                    ):
                        await orchestrator.run(tenants)

        # All 3 clients got a semaphore
        assert len(captured_semaphores) == 3
        # All are the same object (the orchestrator's shared semaphore)
        assert all(s is captured_semaphores[0] for s in captured_semaphores)
        # And it's the orchestrator's own instance
        assert captured_semaphores[0] is orchestrator._global_request_semaphore
