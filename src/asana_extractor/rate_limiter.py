"""Token bucket rate limiter and workspace registry for per-workspace rate limiting.

Provides:
- TokenBucket: async token bucket with continuous refill, blocking acquire()
- WorkspaceRateLimiterRegistry: per-workspace TokenBucket isolation
- RateLimiter429State: 429 pause coordination and consecutive 429 fail-fast
- GlobalRequestSemaphore: global cap on concurrent in-flight HTTP requests
"""

from __future__ import annotations

import asyncio

from asana_extractor.exceptions import AsanaTransientError
from asana_extractor.logging import get_logger

__all__ = [
    "BUCKET_CAPACITY",
    "RATE_PER_SECOND",
    "GlobalRequestSemaphore",
    "RateLimiter429State",
    "TokenBucket",
    "WorkspaceRateLimiterRegistry",
]

RATE_PER_SECOND: float = 2.0  # 120 req/min (~80% of Asana's 150 req/min limit)
BUCKET_CAPACITY: float = 10.0  # max burst tokens when idle


class TokenBucket:
    """Async token bucket rate limiter with continuous refill.

    Paces requests by requiring callers to acquire() a token before proceeding.
    Tokens refill continuously at `rate` tokens per second, capped at `max_tokens`.
    Callers block (asyncio.sleep) until a token is available — transparent to caller.

    Args:
        rate: Token refill rate in tokens per second. Default: 2.0 (120 req/min).
        max_tokens: Maximum token capacity (burst cap). Default: 10.
    """

    def __init__(
        self,
        rate: float = RATE_PER_SECOND,
        max_tokens: float = BUCKET_CAPACITY,
    ) -> None:
        self._rate = rate
        self._max_tokens = max_tokens
        self._tokens: float = max_tokens  # Start full — first requests not throttled
        self._last_refill: float = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()
        self._log = get_logger(__name__)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since last refill (called under lock)."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_refill
        self._tokens = min(self._max_tokens, self._tokens + elapsed * self._rate)
        self._last_refill = now

    async def acquire(self) -> None:
        """Acquire one token, blocking (via asyncio.sleep) until a token is available.

        Multiple concurrent callers are serialized via asyncio.Lock.
        """
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Calculate how long to wait for 1 token
                wait_time = (1.0 - self._tokens) / self._rate

            # Sleep outside lock so other coroutines can run
            await asyncio.sleep(wait_time)

    def reset_tokens(self) -> None:
        """Reset token count to 0.

        Called after a 429 Retry-After pause ends to prevent a burst of
        queued requests all firing at once after the pause.
        """
        self._tokens = 0.0
        self._last_refill = asyncio.get_event_loop().time()


class WorkspaceRateLimiterRegistry:
    """Registry of per-workspace TokenBucket instances.

    Auto-creates a TokenBucket on first request for a workspace_gid.
    Each workspace gets an independent rate limiter, so Workspace A
    hitting its limit does not affect Workspace B (RATE-06).

    Args:
        rate: Token refill rate passed to each TokenBucket. Default: RATE_PER_SECOND.
        max_tokens: Burst capacity passed to each TokenBucket. Default: BUCKET_CAPACITY.
    """

    def __init__(
        self,
        rate: float = RATE_PER_SECOND,
        max_tokens: float = BUCKET_CAPACITY,
    ) -> None:
        self._rate = rate
        self._max_tokens = max_tokens
        self._limiters: dict[str, TokenBucket] = {}
        self._log = get_logger(__name__)

    def get_limiter(self, workspace_gid: str) -> TokenBucket:
        """Get or create a TokenBucket for the given workspace.

        First call for a workspace_gid creates a new TokenBucket.
        Subsequent calls return the cached instance.

        Args:
            workspace_gid: Workspace identifier used as the registry key.

        Returns:
            The TokenBucket for this workspace (created on first call, cached after).
        """
        if workspace_gid not in self._limiters:
            self._limiters[workspace_gid] = TokenBucket(
                rate=self._rate,
                max_tokens=self._max_tokens,
            )
            self._log.info(
                "workspace_limiter_created",
                workspace_gid=workspace_gid,
                rate=self._rate,
                max_tokens=self._max_tokens,
            )
        return self._limiters[workspace_gid]


class RateLimiter429State:
    """Tracks 429 response state for a single workspace.

    Coordinates the Retry-After pause: all callers awaiting the same workspace
    will block in wait_if_paused() until the pause duration expires.
    After the pause, resets the token bucket to 0 to prevent request bursts.
    Fails the workspace (raises AsanaTransientError) after MAX_CONSECUTIVE_429S.

    Args:
        bucket: The TokenBucket for this workspace (reset after each pause).
        workspace_gid: Workspace identifier for logging and error context.
    """

    MAX_CONSECUTIVE_429S: int = 3
    DEFAULT_RETRY_AFTER_SECONDS: float = 60.0

    def __init__(self, bucket: TokenBucket, workspace_gid: str) -> None:
        self._bucket = bucket
        self._workspace_gid = workspace_gid
        self._consecutive_429s: int = 0
        self._pause_until: float = 0.0  # monotonic time when pause ends
        self._lock = asyncio.Lock()
        self._log = get_logger(__name__)

    async def wait_if_paused(self) -> None:
        """Wait if this workspace is currently in a Retry-After pause.

        Multiple concurrent callers all observe the same _pause_until time
        and sleep for the remaining duration. Returns immediately if not paused.
        """
        now = asyncio.get_event_loop().time()
        remaining = self._pause_until - now
        if remaining > 0:
            self._log.debug(
                "workspace_pause_waiting",
                workspace_gid=self._workspace_gid,
                remaining_seconds=round(remaining, 2),
            )
            await asyncio.sleep(remaining)

    async def record_429(
        self,
        *,
        endpoint: str,
        retry_after: float | None,
    ) -> None:
        """Record a 429 response and enforce the Retry-After pause.

        Increments the consecutive 429 counter and sets the pause duration.
        After the pause ends, resets the token bucket to prevent bursts.

        Args:
            endpoint: The API endpoint that returned 429 (for logging/error context).
            retry_after: Retry-After header value in seconds, or None for 60s fallback.

        Raises:
            AsanaTransientError: After MAX_CONSECUTIVE_429S consecutive 429s without
                a successful request in between.
        """
        pause_duration = (
            retry_after if retry_after is not None else self.DEFAULT_RETRY_AFTER_SECONDS
        )

        async with self._lock:
            self._consecutive_429s += 1
            self._log.warning(
                "workspace_rate_limited",
                workspace_gid=self._workspace_gid,
                endpoint=endpoint,
                retry_after=pause_duration,
                consecutive_429s=self._consecutive_429s,
            )

            if self._consecutive_429s >= self.MAX_CONSECUTIVE_429S:
                raise AsanaTransientError(
                    status_code=429,
                    endpoint=endpoint,
                    message=(
                        f"Workspace {self._workspace_gid} received "
                        f"{self._consecutive_429s} consecutive 429s — "
                        "failing workspace for this extraction cycle"
                    ),
                    workspace_gid=self._workspace_gid,
                )

            now = asyncio.get_event_loop().time()
            self._pause_until = now + pause_duration

        # Sleep outside lock so wait_if_paused() callers can see _pause_until
        await asyncio.sleep(pause_duration)

        # After pause ends: reset bucket to 0 to prevent burst of queued requests
        self._bucket.reset_tokens()
        self._log.info(
            "workspace_pause_ended",
            workspace_gid=self._workspace_gid,
            pause_seconds=pause_duration,
        )

    def record_success(self) -> None:
        """Reset consecutive 429 counter after a successful request."""
        self._consecutive_429s = 0


class GlobalRequestSemaphore:
    """Global cap on concurrent in-flight HTTP requests across all workspaces.

    Prevents overwhelming the Asana API when many workspace rate limiters
    are firing simultaneously. Cap is hardcoded at DEFAULT_MAX_CONCURRENT.

    Used as an async context manager:
        async with semaphore:
            response = await http_call()

    Args:
        max_concurrent: Maximum concurrent in-flight requests. Default: 50.
    """

    DEFAULT_MAX_CONCURRENT: int = 50

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._log = get_logger(__name__)

    async def __aenter__(self) -> GlobalRequestSemaphore:
        await self._semaphore.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self._semaphore.release()
