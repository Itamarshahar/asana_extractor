"""Tests for rate_limiter module: TokenBucket, WorkspaceRateLimiterRegistry,
RateLimiter429State, and GlobalRequestSemaphore."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from asana_extractor.exceptions import AsanaTransientError
from asana_extractor.rate_limiter import (
    BUCKET_CAPACITY,
    RATE_PER_SECOND,
    GlobalRequestSemaphore,
    RateLimiter429State,
    TokenBucket,
    WorkspaceRateLimiterRegistry,
)

# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


class TestTokenBucket:
    def test_constants(self) -> None:
        assert RATE_PER_SECOND == 2.0
        assert BUCKET_CAPACITY == 10.0

    async def test_acquire_returns_immediately_when_full(self) -> None:
        """Bucket starts full — first acquire() should not sleep."""
        bucket = TokenBucket(rate=2.0, max_tokens=10.0)
        # Should complete without sleeping
        await asyncio.wait_for(bucket.acquire(), timeout=0.5)

    async def test_acquire_blocks_when_empty(self) -> None:
        """Empty bucket blocks until a token refills."""
        bucket = TokenBucket(rate=2.0, max_tokens=10.0)
        # Drain bucket completely
        for _ in range(10):
            await bucket.acquire()

        # Next acquire should block; we test it via asyncio.sleep mock
        sleep_durations: list[float] = []

        async def capturing_sleep(duration: float) -> None:
            sleep_durations.append(duration)
            # Don't actually sleep — just add tokens to unblock
            bucket._tokens = 1.0

        with patch("asana_extractor.rate_limiter.asyncio.sleep", capturing_sleep):
            await bucket.acquire()

        assert len(sleep_durations) == 1
        assert sleep_durations[0] > 0.0

    async def test_max_tokens_cap(self) -> None:
        """Bucket never exceeds max_tokens even after long idle."""
        bucket = TokenBucket(rate=100.0, max_tokens=5.0)
        # Force a large elapsed time by manipulating _last_refill
        bucket._last_refill = asyncio.get_event_loop().time() - 1000.0
        bucket._refill()
        assert bucket._tokens == pytest.approx(5.0, abs=0.01)

    async def test_concurrent_acquires_serialized(self) -> None:
        """Multiple concurrent acquires don't double-consume tokens."""
        bucket = TokenBucket(rate=2.0, max_tokens=3.0)
        # Drain to exactly 2 tokens
        await bucket.acquire()  # 10 -> 9 (starts full at max_tokens)
        # Reset to exactly 2 tokens for test control
        bucket._tokens = 2.0

        results: list[str] = []

        async def worker(name: str) -> None:
            await bucket.acquire()
            results.append(name)

        # Run 2 concurrent workers — both should succeed immediately
        await asyncio.gather(worker("a"), worker("b"))
        assert len(results) == 2
        # No tokens should remain (or very close to 0)
        assert bucket._tokens < 0.5

    def test_reset_tokens(self) -> None:
        """reset_tokens() zeroes the token count."""
        bucket = TokenBucket(rate=2.0, max_tokens=10.0)
        assert bucket._tokens > 0  # starts full
        bucket.reset_tokens()
        assert bucket._tokens == 0.0


# ---------------------------------------------------------------------------
# WorkspaceRateLimiterRegistry
# ---------------------------------------------------------------------------


class TestWorkspaceRateLimiterRegistry:
    def test_get_limiter_returns_token_bucket(self) -> None:
        registry = WorkspaceRateLimiterRegistry()
        bucket = registry.get_limiter("ws_123")
        assert isinstance(bucket, TokenBucket)

    def test_get_limiter_same_gid_returns_same_instance(self) -> None:
        registry = WorkspaceRateLimiterRegistry()
        b1 = registry.get_limiter("ws_123")
        b2 = registry.get_limiter("ws_123")
        assert b1 is b2

    def test_get_limiter_different_gids_return_different_instances(self) -> None:
        registry = WorkspaceRateLimiterRegistry()
        b1 = registry.get_limiter("ws_123")
        b2 = registry.get_limiter("ws_456")
        assert b1 is not b2

    def test_get_limiter_uses_configured_rate_and_capacity(self) -> None:
        registry = WorkspaceRateLimiterRegistry(rate=5.0, max_tokens=20.0)
        bucket = registry.get_limiter("ws_test")
        assert bucket._rate == 5.0
        assert bucket._max_tokens == 20.0

    def test_get_limiter_default_rate(self) -> None:
        registry = WorkspaceRateLimiterRegistry()
        bucket = registry.get_limiter("ws_default")
        assert bucket._rate == RATE_PER_SECOND
        assert bucket._max_tokens == BUCKET_CAPACITY


# ---------------------------------------------------------------------------
# RateLimiter429State
# ---------------------------------------------------------------------------


class TestRateLimiter429State:
    def _make_state(self, workspace_gid: str = "ws1") -> tuple[TokenBucket, RateLimiter429State]:
        bucket = TokenBucket(rate=2.0, max_tokens=10.0)
        state = RateLimiter429State(bucket=bucket, workspace_gid=workspace_gid)
        return bucket, state

    async def test_wait_if_paused_returns_immediately_when_not_paused(self) -> None:
        _, state = self._make_state()
        await asyncio.wait_for(state.wait_if_paused(), timeout=0.5)

    async def test_wait_if_paused_sleeps_for_remaining_duration(self) -> None:
        _, state = self._make_state()
        # Set pause_until to 5 seconds from now
        state._pause_until = asyncio.get_event_loop().time() + 5.0

        sleep_durations: list[float] = []

        async def capturing_sleep(duration: float) -> None:
            sleep_durations.append(duration)

        with patch("asana_extractor.rate_limiter.asyncio.sleep", capturing_sleep):
            await state.wait_if_paused()

        assert len(sleep_durations) == 1
        assert 4.0 < sleep_durations[0] <= 5.0

    async def test_record_429_increments_consecutive_count(self) -> None:
        _, state = self._make_state()
        assert state._consecutive_429s == 0

        async def fast_sleep(_: float) -> None:
            pass

        with patch("asana_extractor.rate_limiter.asyncio.sleep", fast_sleep):
            await state.record_429(endpoint="/test", retry_after=0.0)

        assert state._consecutive_429s == 1

    async def test_record_429_uses_retry_after_value(self) -> None:
        _, state = self._make_state()
        sleep_durations: list[float] = []

        async def capturing_sleep(duration: float) -> None:
            sleep_durations.append(duration)

        with patch("asana_extractor.rate_limiter.asyncio.sleep", capturing_sleep):
            await state.record_429(endpoint="/test", retry_after=7.5)

        # record_429 calls asyncio.sleep(pause_duration)
        assert 7.5 in sleep_durations

    async def test_record_429_uses_60s_fallback_when_none(self) -> None:
        _, state = self._make_state()
        sleep_durations: list[float] = []

        async def capturing_sleep(duration: float) -> None:
            sleep_durations.append(duration)

        with patch("asana_extractor.rate_limiter.asyncio.sleep", capturing_sleep):
            await state.record_429(endpoint="/test", retry_after=None)

        assert RateLimiter429State.DEFAULT_RETRY_AFTER_SECONDS in sleep_durations

    async def test_record_429_resets_bucket_after_pause(self) -> None:
        bucket, state = self._make_state()
        bucket._tokens = 8.0  # not empty

        async def fast_sleep(_: float) -> None:
            pass

        with patch("asana_extractor.rate_limiter.asyncio.sleep", fast_sleep):
            await state.record_429(endpoint="/test", retry_after=0.0)

        assert bucket._tokens == 0.0

    async def test_record_429_raises_after_max_consecutive(self) -> None:
        _, state = self._make_state()

        async def fast_sleep(_: float) -> None:
            pass

        with patch("asana_extractor.rate_limiter.asyncio.sleep", fast_sleep):
            # First two should succeed
            await state.record_429(endpoint="/test", retry_after=0.0)
            await state.record_429(endpoint="/test", retry_after=0.0)
            # Third should raise
            with pytest.raises(AsanaTransientError) as exc_info:
                await state.record_429(endpoint="/test", retry_after=0.0)

        assert exc_info.value.status_code == 429
        assert "ws1" in exc_info.value.message

    def test_record_success_resets_consecutive_count(self) -> None:
        _, state = self._make_state()
        state._consecutive_429s = 2
        state.record_success()
        assert state._consecutive_429s == 0


# ---------------------------------------------------------------------------
# GlobalRequestSemaphore
# ---------------------------------------------------------------------------


class TestGlobalRequestSemaphore:
    def test_default_max_concurrent(self) -> None:
        assert GlobalRequestSemaphore.DEFAULT_MAX_CONCURRENT == 50

    async def test_context_manager_acquires_and_releases(self) -> None:
        sem = GlobalRequestSemaphore(max_concurrent=2)
        async with sem:
            pass  # Should not raise

    async def test_blocks_when_all_slots_taken(self) -> None:
        """Third caller must wait when max_concurrent=2 and 2 slots are taken."""
        sem = GlobalRequestSemaphore(max_concurrent=2)
        order: list[str] = []

        async def worker_hold(name: str, hold_event: asyncio.Event) -> None:
            async with sem:
                order.append(f"enter-{name}")
                await hold_event.wait()
                order.append(f"exit-{name}")

        async def worker_quick(name: str) -> None:
            async with sem:
                order.append(f"enter-{name}")
                order.append(f"exit-{name}")

        hold1 = asyncio.Event()
        hold2 = asyncio.Event()

        # Start two long-running workers
        t1 = asyncio.create_task(worker_hold("a", hold1))
        t2 = asyncio.create_task(worker_hold("b", hold2))
        await asyncio.sleep(0.01)  # Let t1 and t2 acquire

        # Third worker should be blocked
        t3 = asyncio.create_task(worker_quick("c"))
        await asyncio.sleep(0.01)
        assert "enter-c" not in order  # t3 is blocked

        # Release one slot
        hold1.set()
        await asyncio.sleep(0.01)
        assert "enter-c" in order  # t3 can now proceed

        hold2.set()
        await asyncio.gather(t1, t2, t3)

    async def test_created_with_custom_max_concurrent(self) -> None:
        sem = GlobalRequestSemaphore(max_concurrent=5)
        assert sem._max_concurrent == 5
