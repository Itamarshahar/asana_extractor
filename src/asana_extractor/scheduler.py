"""Periodic extraction scheduler with skip-on-overlap and graceful shutdown.

ExtractionScheduler drives the extraction pipeline as a long-running service:
- Runs extraction cycles at fixed wall-clock intervals (t=0, t=interval, t=2*interval, ...)
- Skips a cycle if the previous one is still running (skip-on-overlap)
- Handles SIGTERM/SIGINT for graceful shutdown (in-flight cycle completes first)
- Enforces a shutdown timeout — if the cycle doesn't finish, cancels and exits

Usage:
    scheduler = ExtractionScheduler(settings, orchestrator, tenant_provider)
    await scheduler.run()       # Periodic loop (blocks until shutdown)
    await scheduler.run_once()  # Single cycle then return
"""

from __future__ import annotations

import asyncio
import signal
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from asana_extractor.logging import get_logger

if TYPE_CHECKING:
    from asana_extractor.config import Settings
    from asana_extractor.orchestrator import WorkspaceOrchestrator
    from asana_extractor.tenant import TenantProvider

__all__ = ["ExtractionScheduler"]


class ExtractionScheduler:
    """Periodic extraction scheduler with skip-on-overlap and graceful shutdown.

    Runs extraction cycles at fixed wall-clock intervals. If a cycle is still
    running when the next interval fires, the new cycle is skipped with a WARNING
    log. SIGTERM/SIGINT trigger graceful shutdown — the in-flight cycle completes
    before exit. If the cycle doesn't finish within shutdown_timeout_seconds, it
    is cancelled and the scheduler exits with a WARNING log.

    Attributes:
        _settings: Application configuration (extraction_interval, shutdown_timeout_seconds).
        _orchestrator: WorkspaceOrchestrator used to run each extraction cycle.
        _tenant_provider: TenantProvider used to get the list of tenants each cycle.
        _running: Boolean flag indicating if a cycle is currently in progress.
        _shutdown_event: asyncio.Event set by stop() or signal handler to trigger shutdown.
        _log: Structlog bound logger for lifecycle events.
    """

    def __init__(
        self,
        settings: Settings,
        orchestrator: WorkspaceOrchestrator,
        tenant_provider: TenantProvider,
    ) -> None:
        """Initialize the scheduler with its dependencies.

        Args:
            settings: Application configuration. extraction_interval controls
                      the scheduling interval; shutdown_timeout_seconds controls
                      how long to wait for in-flight cycle on shutdown.
            orchestrator: WorkspaceOrchestrator to call each extraction cycle.
            tenant_provider: TenantProvider to get tenants list each cycle.
        """
        self._settings = settings
        self._orchestrator = orchestrator
        self._tenant_provider = tenant_provider
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._log = get_logger(__name__)

    async def _run_cycle(self) -> None:
        """Run a single extraction cycle.

        Calls tenant_provider.list_tenants() then orchestrator.run(tenants).
        Sets _running=True for the duration of the cycle so skip-on-overlap
        detection works correctly. Logs cycle_started and cycle_complete with
        succeeded count, failed count, and duration_seconds.
        """
        self._running = True
        cycle_start_iso = datetime.now(UTC).isoformat()
        self._log.info("cycle_started", cycle_start_iso=cycle_start_iso)
        start = time.monotonic()

        tenants = self._tenant_provider.list_tenants()
        result = await self._orchestrator.run(tenants, cycle_start_iso=cycle_start_iso)

        duration = time.monotonic() - start
        self._log.info(
            "cycle_complete",
            succeeded=len(result.succeeded),
            failed=len(result.failed),
            duration_seconds=round(duration, 2),
        )
        self._running = False

    async def run_once(self) -> None:
        """Run a single extraction cycle and return.

        Used for the --run-once CLI flag. Runs exactly one cycle then returns.
        Does not install signal handlers or enter the periodic loop.
        """
        await self._run_cycle()

    async def run(self) -> None:
        """Run the periodic extraction loop until shutdown is requested.

        - Installs signal handlers for SIGTERM and SIGINT (both call _handle_signal)
        - Runs the first cycle immediately at t=0
        - Waits for extraction_interval seconds (or shutdown signal) between cycles
        - Skips a cycle if _running is True when the interval fires (skip-on-overlap)
        - On shutdown: waits up to shutdown_timeout_seconds for in-flight cycle
        - If timeout exceeded: cancels cycle and logs WARNING shutdown_timeout_exceeded
        - Removes signal handlers and logs shutdown_complete before returning

        This method blocks until shutdown is requested via signal or stop().
        """
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        # Run first cycle immediately at t=0
        cycle_task: asyncio.Task[None] = asyncio.create_task(self._run_cycle())

        # Main interval loop — wait for interval or shutdown, whichever comes first
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._settings.extraction_interval,
                )
            except TimeoutError:
                pass

            if self._shutdown_event.is_set():
                break

            if self._running:
                self._log.warning(
                    "cycle_skipped",
                    interval_seconds=self._settings.extraction_interval,
                    reason="previous_cycle_still_running",
                )
                continue

            cycle_task = asyncio.create_task(self._run_cycle())

        # Shutdown requested — wait for in-flight cycle to complete
        if self._running:
            self._log.info("waiting_for_cycle")
            try:
                await asyncio.wait_for(
                    cycle_task,
                    timeout=self._settings.shutdown_timeout_seconds,
                )
            except TimeoutError:
                self._log.warning("shutdown_timeout_exceeded")
                cycle_task.cancel()
                try:
                    await cycle_task
                except asyncio.CancelledError:
                    pass

        self._log.info("shutdown_complete")

        # Clean up signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)

    def _handle_signal(self) -> None:
        """Handle SIGTERM or SIGINT by requesting graceful shutdown.

        Sets the shutdown event so the run() loop exits after the current
        cycle completes. Called from the asyncio event loop's signal handler
        machinery — runs synchronously in the event loop thread.
        """
        self._log.info("shutdown_requested")
        self._shutdown_event.set()

    def stop(self) -> None:
        """Request graceful shutdown programmatically.

        Equivalent to receiving SIGTERM/SIGINT. Can be called from tests or
        other code to stop the scheduler loop. The run() method will exit after
        the current extraction cycle completes (or after shutdown_timeout_seconds).
        """
        self._log.info("shutdown_requested")
        self._shutdown_event.set()
