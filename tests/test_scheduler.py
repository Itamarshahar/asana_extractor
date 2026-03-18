"""Tests for ExtractionScheduler: run_once, skip-on-overlap, graceful shutdown,
and shutdown timeout.

Mocking strategy: AsyncMock for WorkspaceOrchestrator.run() and a fake
TenantProvider. Signal handlers are patched out because loop.add_signal_handler()
only works from the main thread (pytest may run tests in worker threads).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import structlog.testing

from asana_extractor.config import Settings
from asana_extractor.orchestrator import WorkspaceOrchestrator
from asana_extractor.scheduler import ExtractionScheduler
from asana_extractor.tenant import OrchestratorResult, TenantConfig, TenantProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_settings(
    interval: int = 30,
    shutdown_timeout: int = 5,
) -> Settings:
    """Create a Settings with test-friendly defaults."""
    return Settings(
        extraction_interval=interval,  # type: ignore[arg-type]
        shutdown_timeout_seconds=shutdown_timeout,
    )


class FakeTenantProvider(TenantProvider):
    """Returns a fixed list of tenants."""

    def __init__(self, tenants: list[TenantConfig] | None = None) -> None:
        self._tenants = tenants or [TenantConfig(workspace_gid="ws-1", pat="fake-pat")]

    def list_tenants(self) -> list[TenantConfig]:
        return self._tenants


def _make_orchestrator_mock(
    run_duration: float = 0.0,
) -> MagicMock:
    """Create a mock WorkspaceOrchestrator whose run() takes *run_duration* seconds."""
    mock = MagicMock(spec=WorkspaceOrchestrator)
    result = OrchestratorResult(succeeded=["ws-1"], failed=[])

    async def fake_run(tenants: list[TenantConfig]) -> OrchestratorResult:
        if run_duration > 0:
            await asyncio.sleep(run_duration)
        return result

    mock.run = AsyncMock(side_effect=fake_run)
    return mock


# ---------------------------------------------------------------------------
# TestSchedulerRunOnce
# ---------------------------------------------------------------------------


class TestSchedulerRunOnce:
    async def test_run_once_calls_orchestrator(self) -> None:
        """run_once() calls tenant_provider.list_tenants() and orchestrator.run()."""
        settings = make_settings()
        provider = FakeTenantProvider()
        orchestrator = _make_orchestrator_mock()

        scheduler = ExtractionScheduler(settings, orchestrator, provider)
        await scheduler.run_once()

        orchestrator.run.assert_awaited_once_with(provider.list_tenants())
        assert scheduler._running is False

    async def test_run_once_logs_cycle_events(self) -> None:
        """run_once() logs cycle_started and cycle_complete with expected keys."""
        settings = make_settings()
        provider = FakeTenantProvider()
        orchestrator = _make_orchestrator_mock()

        scheduler = ExtractionScheduler(settings, orchestrator, provider)

        with structlog.testing.capture_logs() as logs:
            await scheduler.run_once()

        events = [log["event"] for log in logs]
        assert "cycle_started" in events
        assert "cycle_complete" in events

        complete_log = next(log for log in logs if log["event"] == "cycle_complete")
        assert "succeeded" in complete_log
        assert "failed" in complete_log
        assert "duration_seconds" in complete_log

    async def test_run_once_sets_running_flag(self) -> None:
        """_running is True during the cycle and False after."""
        settings = make_settings()
        provider = FakeTenantProvider()

        running_during_cycle = False

        async def capture_running(tenants: list[TenantConfig]) -> OrchestratorResult:
            nonlocal running_during_cycle
            running_during_cycle = scheduler._running
            return OrchestratorResult(succeeded=["ws-1"], failed=[])

        orchestrator = MagicMock(spec=WorkspaceOrchestrator)
        orchestrator.run = AsyncMock(side_effect=capture_running)

        scheduler = ExtractionScheduler(settings, orchestrator, provider)
        await scheduler.run_once()

        assert running_during_cycle is True
        assert scheduler._running is False


# ---------------------------------------------------------------------------
# TestSchedulerSkipOnOverlap
# ---------------------------------------------------------------------------


class TestSchedulerSkipOnOverlap:
    async def test_cycle_skipped_when_previous_still_running(self) -> None:
        """When _running is True at interval fire time, scheduler logs cycle_skipped.

        Strategy: Use a slow orchestrator (run_duration=999) so the first cycle
        stays running. Patch the _shutdown_event so the interval wait returns
        immediately (simulating interval elapsed), triggering the overlap check.
        On the second iteration, trigger shutdown to exit cleanly.
        """
        settings = make_settings(interval=30, shutdown_timeout=2)
        provider = FakeTenantProvider()
        orchestrator = _make_orchestrator_mock(run_duration=999)

        scheduler = ExtractionScheduler(settings, orchestrator, provider)

        # We need the scheduler's while-loop to iterate without actually waiting
        # for 30 seconds. The loop does:
        #   await asyncio.wait_for(self._shutdown_event.wait(), timeout=interval)
        #
        # We replace the _shutdown_event with a custom one whose wait() never
        # resolves (so wait_for always hits TimeoutError, simulating interval elapsed).
        # After the overlap is detected, we set the real event to trigger shutdown.

        never_set_event = asyncio.Event()  # never gets set
        iteration = 0

        async def counting_wait() -> None:
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                # Second wait: trigger shutdown and return (set causes is_set() = True)
                scheduler._shutdown_event = real_shutdown_event
                real_shutdown_event.set()
                return
            # First wait: just never resolve (let wait_for timeout)
            await asyncio.sleep(999)

        never_set_event.wait = counting_wait  # type: ignore[assignment]
        real_shutdown_event = scheduler._shutdown_event

        # Replace the shutdown event used in the while-loop condition check
        # We need is_set() to return False until we want shutdown
        scheduler._shutdown_event = never_set_event

        loop = asyncio.get_running_loop()
        with (
            patch.object(loop, "add_signal_handler"),
            patch.object(loop, "remove_signal_handler"),
            # Make the interval tiny so wait_for times out fast
            patch.object(scheduler._settings, "extraction_interval", 0.01),
            structlog.testing.capture_logs() as logs,
        ):
            task = asyncio.create_task(scheduler.run())
            await asyncio.wait_for(task, timeout=5)

        events = [log["event"] for log in logs]
        assert "cycle_skipped" in events

        skipped_log = next(log for log in logs if log["event"] == "cycle_skipped")
        assert skipped_log["reason"] == "previous_cycle_still_running"


# ---------------------------------------------------------------------------
# TestSchedulerGracefulShutdown
# ---------------------------------------------------------------------------


class TestSchedulerGracefulShutdown:
    async def test_stop_exits_run_loop(self) -> None:
        """Calling stop() causes run() to exit after the current cycle completes."""
        settings = make_settings(interval=30, shutdown_timeout=5)
        provider = FakeTenantProvider()
        orchestrator = _make_orchestrator_mock(run_duration=0.0)

        scheduler = ExtractionScheduler(settings, orchestrator, provider)

        loop = asyncio.get_running_loop()
        with (
            patch.object(loop, "add_signal_handler"),
            patch.object(loop, "remove_signal_handler"),
            structlog.testing.capture_logs() as logs,
        ):
            task = asyncio.create_task(scheduler.run())
            # Wait for first cycle to complete
            await asyncio.sleep(0.1)
            scheduler.stop()
            await asyncio.wait_for(task, timeout=3)

        events = [log["event"] for log in logs]
        assert "shutdown_complete" in events

    async def test_shutdown_waits_for_inflight_cycle(self) -> None:
        """If a cycle is running when shutdown is requested, scheduler waits for it."""
        settings = make_settings(interval=30, shutdown_timeout=5)
        provider = FakeTenantProvider()
        orchestrator = _make_orchestrator_mock(run_duration=0.3)

        scheduler = ExtractionScheduler(settings, orchestrator, provider)

        loop = asyncio.get_running_loop()
        with (
            patch.object(loop, "add_signal_handler"),
            patch.object(loop, "remove_signal_handler"),
            structlog.testing.capture_logs() as logs,
        ):
            task = asyncio.create_task(scheduler.run())
            # Wait for cycle to start but not finish
            await asyncio.sleep(0.05)
            assert scheduler._running is True

            scheduler.stop()
            await asyncio.wait_for(task, timeout=5)

        events = [log["event"] for log in logs]
        assert "waiting_for_cycle" in events
        assert "shutdown_complete" in events
        assert scheduler._running is False


# ---------------------------------------------------------------------------
# TestSchedulerShutdownTimeout
# ---------------------------------------------------------------------------


class TestSchedulerShutdownTimeout:
    async def test_shutdown_timeout_cancels_stuck_cycle(self) -> None:
        """If in-flight cycle exceeds shutdown_timeout, it's cancelled."""
        settings = make_settings(interval=30, shutdown_timeout=1)
        provider = FakeTenantProvider()
        orchestrator = _make_orchestrator_mock(run_duration=999)

        scheduler = ExtractionScheduler(settings, orchestrator, provider)

        loop = asyncio.get_running_loop()
        with (
            patch.object(loop, "add_signal_handler"),
            patch.object(loop, "remove_signal_handler"),
            structlog.testing.capture_logs() as logs,
        ):
            task = asyncio.create_task(scheduler.run())
            # Wait for cycle to start
            await asyncio.sleep(0.05)
            assert scheduler._running is True

            scheduler.stop()
            # Should take ~1 second (shutdown_timeout) then cancel
            await asyncio.wait_for(task, timeout=5)

        events = [log["event"] for log in logs]
        assert "shutdown_timeout_exceeded" in events
        assert "shutdown_complete" in events
