"""Async HTTP client for the Asana API with authentication, retry, and error handling.

AsanaClient wraps aiohttp with:
- PAT-based authentication via SecretsProvider
- Connection pooling via managed ClientSession
- Exponential backoff + jitter retry for transient errors (3 attempts)
- Error classification: AsanaTransientError (5xx, connection) vs AsanaPermanentError (4xx)
- Structured logging of all errors with workspace_gid context
"""

from __future__ import annotations

import logging
import platform
import ssl
import subprocess
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from asana_extractor.exceptions import AsanaPermanentError, AsanaTransientError
from asana_extractor.logging import get_logger
from asana_extractor.secrets import SecretsProvider

__all__ = ["BASE_URL", "DEFAULT_PAGE_SIZE", "AsanaClient"]

BASE_URL = "https://app.asana.com/api/1.0/"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_PAGE_SIZE = 100

# Standard library logger for tenacity's before_sleep_log
_std_logger = logging.getLogger(__name__)


def _build_ssl_context() -> ssl.SSLContext:
    """Build an SSL context that trusts the system CA store.

    On macOS, also loads certificates from the system keychain so that
    corporate proxy / self-signed CAs installed via MDM are trusted.
    """
    ctx = ssl.create_default_context()
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["security", "find-certificate", "-a", "-p", "/Library/Keychains/System.keychain"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                ctx.load_verify_locations(cadata=result.stdout)
        except Exception:
            pass  # Fall back to default CAs if keychain access fails
    return ctx


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the exception should trigger a tenacity retry.

    429 (rate limit) is excluded — RateLimitedClient handles it via its own
    Retry-After logic. Retrying 429 inside AsanaClient would fight the rate limiter.
    """
    if isinstance(exc, AsanaTransientError) and exc.status_code == 429:
        return False
    return isinstance(
        exc,
        (
            aiohttp.ClientConnectionError,
            aiohttp.ServerDisconnectedError,
            TimeoutError,
            AsanaTransientError,
        ),
    )


class AsanaClient:
    """Async HTTP client for the Asana REST API.

    Usage:
        async with AsanaClient(secrets_provider) as client:
            data = await client.get("/users/me")

    The client handles:
    - Bearer token authentication via SecretsProvider.get_secret("ASANA_PAT")
    - Connection pooling (max 100 connections)
    - Automatic retry on transient errors (3 attempts, exponential backoff + jitter)
    - Error classification into AsanaTransientError / AsanaPermanentError
    """

    def __init__(self, secrets_provider: SecretsProvider) -> None:
        self._secrets_provider = secrets_provider
        self._session: aiohttp.ClientSession | None = None
        self._log = get_logger(__name__)

    async def __aenter__(self) -> AsanaClient:
        pat = self._secrets_provider.get_secret("ASANA_PAT")
        self._session = aiohttp.ClientSession(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_SECONDS),
            connector=aiohttp.TCPConnector(
                limit=100,
                enable_cleanup_closed=True,
                ssl=_build_ssl_context(),
            ),
        )
        self._log.info("asana_client_initialized")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._log.info("asana_client_closed")

    async def get(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        workspace_gid: str | None = None,
    ) -> dict[str, Any]:
        """Make a GET request to the Asana API with retry and error handling.

        Args:
            endpoint: API path relative to BASE_URL (e.g., "/users/me").
            params: Optional query parameters.
            workspace_gid: Workspace context for error logging and exceptions.

        Returns:
            The "data" field from the Asana API response, or the full response
            if no "data" key is present.

        Raises:
            RuntimeError: If called outside async context manager.
            AsanaTransientError: On 5xx errors, rate limits (429), or connection
                failures after all retry attempts are exhausted.
            AsanaPermanentError: On 4xx client errors (except 429).
        """
        if self._session is None:
            raise RuntimeError(
                "Client not initialized. Use 'async with AsanaClient(...) as client:'"
            )

        try:
            raw = await self._request(endpoint, params=params, workspace_gid=workspace_gid)
            result = raw.get("data", raw)
            return result if isinstance(result, dict) else raw
        except (
            aiohttp.ClientConnectionError,
            aiohttp.ServerDisconnectedError,
            TimeoutError,
        ) as exc:
            self._log.error(
                "request_failed_after_retries",
                endpoint=endpoint,
                workspace_gid=workspace_gid,
                error_type=type(exc).__name__,
            )
            raise AsanaTransientError(
                status_code=None,
                endpoint=endpoint,
                message=f"Connection failed after retries: {exc}",
                workspace_gid=workspace_gid,
            ) from exc

    async def paginated_get(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        workspace_gid: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Auto-paginate through a list endpoint, yielding entities one at a time.

        Follows next_page.offset until None. Each page requests limit=100 (Asana maximum).
        Retries are handled per-page by the underlying _request() method.
        Aborts on exhausted retries — no silent data gaps.

        Args:
            endpoint: API path relative to BASE_URL (e.g., "/users").
            params: Optional additional query parameters (merged with pagination params).
            workspace_gid: Workspace context for error logging and exceptions.

        Yields:
            Individual entity dicts from the "data" array, one at a time across all pages.

        Raises:
            RuntimeError: If called outside async context manager.
            AsanaTransientError: If retries are exhausted on any page (pagination aborts).
            AsanaPermanentError: On 4xx client errors.

        Usage:
            async for entity in client.paginated_get("/users", params={"workspace": gid}):
                process(entity)
        """
        if self._session is None:
            raise RuntimeError(
                "Client not initialized. Use 'async with AsanaClient(...) as client:'"
            )

        page_params = dict(params or {})
        page_params["limit"] = str(DEFAULT_PAGE_SIZE)

        total_items = 0
        page_count = 0

        self._log.info(
            "pagination_started",
            endpoint=endpoint,
            workspace_gid=workspace_gid,
        )

        while True:
            page_count += 1
            # _request returns full Asana envelope (retries handled inside)
            response = await self._request(
                endpoint, params=page_params, workspace_gid=workspace_gid
            )

            entities = response.get("data", [])
            for entity in entities:
                total_items += 1
                yield entity

            # Check for next page
            next_page = response.get("next_page")
            if next_page is None:
                break

            # Asana pagination uses offset parameter
            offset = next_page.get("offset")
            if offset is None:
                break

            page_params["offset"] = offset

        self._log.info(
            "pagination_complete",
            endpoint=endpoint,
            workspace_gid=workspace_gid,
            total_items=total_items,
            pages=page_count,
        )

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=1, max=30) + wait_random(0, 1),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(_std_logger, logging.WARNING),
        reraise=True,
    )
    async def _request(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        workspace_gid: str | None = None,
    ) -> dict[str, Any]:
        """Internal request method wrapped with tenacity retry logic."""
        assert self._session is not None  # guarded by public get()

        # Strip leading slash so aiohttp resolves relative to base_url correctly.
        # aiohttp treats "/foo" as absolute (drops base path), "foo" as relative.
        url = endpoint.lstrip("/")
        async with self._session.get(url, params=params) as response:
            if response.status >= 500:
                body = await response.text()
                self._log.warning(
                    "transient_api_error",
                    status=response.status,
                    endpoint=endpoint,
                    workspace_gid=workspace_gid,
                    body=body[:500],
                )
                raise AsanaTransientError(
                    status_code=response.status,
                    endpoint=endpoint,
                    message=f"Server error: {body[:200]}",
                    workspace_gid=workspace_gid,
                )

            if response.status == 429:
                # 429 is NOT retried by tenacity — RateLimitedClient handles
                # Retry-After and workspace isolation. AsanaClient raises
                # immediately so the caller can apply its own back-off strategy.
                await response.text()

                # Parse Retry-After header (seconds). Gracefully handle
                # missing or malformed values — None triggers 60s fallback
                # in RateLimiter429State.record_429().
                retry_after: float | None = None
                raw_retry_after = response.headers.get("Retry-After")
                if raw_retry_after is not None:
                    try:
                        retry_after = float(raw_retry_after)
                    except (ValueError, OverflowError):
                        retry_after = None

                self._log.warning(
                    "rate_limited_429",
                    status=429,
                    endpoint=endpoint,
                    workspace_gid=workspace_gid,
                    retry_after=retry_after,
                )
                raise AsanaTransientError(
                    status_code=429,
                    endpoint=endpoint,
                    message="Rate limited (429) — RateLimitedClient handles Retry-After.",
                    workspace_gid=workspace_gid,
                    retry_after=retry_after,
                )

            if response.status >= 400:
                body = await response.text()
                self._log.error(
                    "permanent_api_error",
                    status=response.status,
                    endpoint=endpoint,
                    workspace_gid=workspace_gid,
                    body=body[:500],
                )
                raise AsanaPermanentError(
                    status_code=response.status,
                    endpoint=endpoint,
                    message=f"Client error: {body[:200]}",
                    workspace_gid=workspace_gid,
                )

            raw: dict[str, Any] = await response.json()
            return raw
