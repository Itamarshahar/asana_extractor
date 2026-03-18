"""Rate-limited Asana API client — drop-in replacement for AsanaClient.

RateLimitedClient wraps AsanaClient with:
- Per-workspace token bucket rate limiting (~120 req/min per workspace)
- Global in-flight request semaphore (50 concurrent requests max)
- 429/Retry-After handling: pause workspace, reset bucket, retry request
- Workspace isolation: one workspace's 429 never delays other workspaces
- Fail-safe: raises AsanaTransientError after 3 consecutive 429s per workspace

Usage:
    async with RateLimitedClient(secrets_provider) as client:
        data = await client.get("/users/me", workspace_gid="12345")
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from asana_extractor.client import DEFAULT_PAGE_SIZE, AsanaClient
from asana_extractor.exceptions import AsanaTransientError
from asana_extractor.logging import get_logger
from asana_extractor.rate_limiter import (
    GlobalRequestSemaphore,
    RateLimiter429State,
    TokenBucket,
    WorkspaceRateLimiterRegistry,
)
from asana_extractor.secrets import SecretsProvider

__all__ = ["RateLimitedClient"]

_GLOBAL_WORKSPACE_KEY = "__global__"


class RateLimitedClient:
    """Rate-limited drop-in replacement for AsanaClient.

    Composes AsanaClient with:
    - WorkspaceRateLimiterRegistry: per-workspace TokenBucket (2 tokens/sec, burst 10)
    - GlobalRequestSemaphore: caps concurrent in-flight requests at 50
    - RateLimiter429State per workspace: handles 429 pause and consecutive limit

    Request flow for each call:
    1. check wait_if_paused() — skip wait if workspace not currently paused
    2. async with self._semaphore — acquire global slot (cap 50 concurrent)
    3. await bucket.acquire() — acquire workspace token (pacing)
    4. delegate to AsanaClient
    5. on success: record_success() to reset consecutive 429 counter
    6. on 429: record_429() (pauses + resets bucket), then retry once

    Args:
        secrets_provider: Provides the Asana PAT via get_secret("ASANA_PAT").
        global_semaphore: Optional shared semaphore for capping concurrent requests
            across multiple clients. If None, creates its own (backward compat).
    """

    def __init__(
        self,
        secrets_provider: SecretsProvider,
        global_semaphore: GlobalRequestSemaphore | None = None,
    ) -> None:
        self._client = AsanaClient(secrets_provider)
        self._registry = WorkspaceRateLimiterRegistry(rate=2.0, max_tokens=10.0)
        self._semaphore = global_semaphore or GlobalRequestSemaphore()
        self._429_states: dict[str, RateLimiter429State] = {}
        self._log = get_logger(__name__)

    def _get_429_state(self, workspace_key: str) -> RateLimiter429State:
        """Get or create RateLimiter429State for a workspace key."""
        if workspace_key not in self._429_states:
            bucket: TokenBucket = self._registry.get_limiter(workspace_key)
            self._429_states[workspace_key] = RateLimiter429State(
                bucket=bucket,
                workspace_gid=workspace_key,
            )
        return self._429_states[workspace_key]

    async def __aenter__(self) -> RateLimitedClient:
        await self._client.__aenter__()
        self._log.info("rate_limited_client_initialized")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self._client.__aexit__(exc_type, exc_val, exc_tb)
        self._log.info("rate_limited_client_closed")

    async def _execute_get_envelope(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        workspace_gid: str | None = None,
        workspace_key: str,
        is_retry: bool = False,
    ) -> dict[str, Any]:
        """Execute a single GET with rate limiting, returning the full Asana envelope.

        Unlike ``_execute_get`` (which delegates to ``AsanaClient.get()`` and
        returns only the unwrapped ``data`` field), this method calls
        ``AsanaClient._request()`` directly so the caller receives the full
        response including ``next_page`` — needed for manual pagination.
        """
        state = self._get_429_state(workspace_key)
        bucket = self._registry.get_limiter(workspace_key)

        await state.wait_if_paused()

        async with self._semaphore:
            await bucket.acquire()
            try:
                result: dict[str, Any] = await self._client._request(
                    endpoint, params=params, workspace_gid=workspace_gid
                )
                state.record_success()
                return result
            except AsanaTransientError as exc:
                if exc.status_code == 429 and not is_retry:
                    await state.record_429(endpoint=endpoint, retry_after=exc.retry_after)
                    return await self._execute_get_envelope(
                        endpoint,
                        params=params,
                        workspace_gid=workspace_gid,
                        workspace_key=workspace_key,
                        is_retry=True,
                    )
                raise

    async def _execute_get(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        workspace_gid: str | None = None,
        workspace_key: str,
        is_retry: bool = False,
    ) -> dict[str, Any]:
        """Execute a single GET with rate limiting. Used by get() and for retries."""
        state = self._get_429_state(workspace_key)
        bucket = self._registry.get_limiter(workspace_key)

        await state.wait_if_paused()

        async with self._semaphore:
            await bucket.acquire()
            try:
                result = await self._client.get(
                    endpoint, params=params, workspace_gid=workspace_gid
                )
                state.record_success()
                return result
            except AsanaTransientError as exc:
                if exc.status_code == 429 and not is_retry:
                    # Pause workspace, reset bucket, then retry once
                    await state.record_429(endpoint=endpoint, retry_after=exc.retry_after)
                    return await self._execute_get(
                        endpoint,
                        params=params,
                        workspace_gid=workspace_gid,
                        workspace_key=workspace_key,
                        is_retry=True,
                    )
                raise

    async def get(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        workspace_gid: str | None = None,
    ) -> dict[str, Any]:
        """Rate-limited GET request. Identical interface to AsanaClient.get().

        Applies per-workspace token bucket pacing and global semaphore before
        delegating to AsanaClient. Handles 429 responses with Retry-After pause
        and one retry. Raises AsanaTransientError after 3 consecutive 429s.

        Args:
            endpoint: API path relative to BASE_URL (e.g., "/users/me").
            params: Optional query parameters.
            workspace_gid: Workspace context for rate limiting and error logging.

        Returns:
            The "data" field from the Asana API response.

        Raises:
            RuntimeError: If called outside async context manager.
            AsanaTransientError: After retries exhausted or 3 consecutive 429s.
            AsanaPermanentError: On 4xx errors (except 429 which is retried).
        """
        workspace_key = workspace_gid or _GLOBAL_WORKSPACE_KEY
        return await self._execute_get(
            endpoint,
            params=params,
            workspace_gid=workspace_gid,
            workspace_key=workspace_key,
        )

    async def paginated_get(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        workspace_gid: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Rate-limited paginated GET. Identical interface to AsanaClient.paginated_get().

        Applies rate limiting **per page**: each page individually acquires the
        token bucket and semaphore before its HTTP call, preventing unbounded
        bursts from large entity sets.

        Args:
            endpoint: API path relative to BASE_URL (e.g., "/users").
            params: Optional query parameters (merged with pagination params).
            workspace_gid: Workspace context for rate limiting and error logging.

        Yields:
            Individual entity dicts from the "data" array, one at a time.

        Raises:
            RuntimeError: If called outside async context manager.
            AsanaTransientError: If retries exhausted on any page.
            AsanaPermanentError: On 4xx errors.
        """
        workspace_key = workspace_gid or _GLOBAL_WORKSPACE_KEY

        page_params = dict(params or {})
        page_params["limit"] = str(DEFAULT_PAGE_SIZE)

        total_items = 0
        page_count = 0

        self._log.info(
            "paginated_get_started",
            endpoint=endpoint,
            workspace_gid=workspace_gid,
        )

        while True:
            page_count += 1
            # Each page goes through the full rate limiting stack:
            # wait_if_paused → semaphore → bucket.acquire → HTTP → 429 handling
            response = await self._execute_get_envelope(
                endpoint,
                params=page_params,
                workspace_gid=workspace_gid,
                workspace_key=workspace_key,
            )

            entities: list[dict[str, Any]] = response.get("data", [])
            for entity in entities:
                total_items += 1
                yield entity

            # Check for next page
            next_page = response.get("next_page")
            if next_page is None:
                break

            offset = next_page.get("offset")
            if offset is None:
                break

            page_params["offset"] = offset

        self._log.info(
            "paginated_get_complete",
            endpoint=endpoint,
            workspace_gid=workspace_gid,
            total_items=total_items,
            pages=page_count,
        )
