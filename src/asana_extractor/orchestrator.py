"""WorkspaceOrchestrator — concurrent workspace extraction with isolation.

Runs extraction across all tenant workspaces concurrently using asyncio.gather.
Each workspace task runs inside its own try/except so one workspace's failure
never aborts other workspaces (requirement EXTR-07). A semaphore caps concurrent
workspace tasks at settings.max_concurrent_workspaces. run() always returns
OrchestratorResult and never raises.

Design notes:
- asyncio.gather(*tasks, return_exceptions=True) collects all results including
  failures without cancelling healthy tasks (NOT asyncio.TaskGroup, which cancels
  on first error — violates EXTR-07).
- try/except inside _run_workspace is the primary isolation mechanism. The
  return_exceptions=True is a safety net for BaseException subclasses.
- Each workspace gets its own RateLimitedClient for independent rate limiting.
- EntityWriter is shared across workspace tasks (writes to separate file paths
  per workspace — no conflict).
- extract_workspace is imported inside _run_workspace to avoid circular imports
  when extractors.py (Phase 5) is built.
"""

from __future__ import annotations

import asyncio
import traceback
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from asana_extractor.config import Settings
from asana_extractor.logging import get_logger
from asana_extractor.rate_limited_client import RateLimitedClient
from asana_extractor.rate_limiter import GlobalRequestSemaphore
from asana_extractor.secrets import SecretsProvider
from asana_extractor.state import ExtractionState, load_state, save_state
from asana_extractor.tenant import OrchestratorResult, TenantConfig, WorkspaceError
from asana_extractor.writer import EntityWriter

if TYPE_CHECKING:
    pass

__all__ = ["WorkspaceOrchestrator"]


class _PatSecretsProvider(SecretsProvider):
    """Internal SecretsProvider that returns a fixed PAT.

    Used to inject per-tenant PATs into RateLimitedClient without exposing
    the PAT in the orchestrator's public API. One instance per workspace task.
    """

    def __init__(self, pat: str) -> None:
        self._pat = pat

    def get_secret(self, key: str) -> str:
        """Return the PAT for ASANA_PAT key; raise ValueError for unknown keys."""
        if key == "ASANA_PAT":
            return self._pat
        raise ValueError(f"Unknown secret key: {key!r}")


class WorkspaceOrchestrator:
    """Runs extraction across all workspaces concurrently with isolation.

    One workspace's failure does not abort others. Each workspace gets:
    - Its own RateLimitedClient instance (independent rate limiting state)
    - Its own try/except wrapper (exceptions captured, not propagated)
    - Its own structured log context (workspace_gid bound)

    The orchestrator owns a semaphore limiting concurrent workspace tasks
    to settings.max_concurrent_workspaces (default: 10).

    Usage:
        orchestrator = WorkspaceOrchestrator(settings)
        result = await orchestrator.run(tenants)
        if result.has_failures:
            for err in result.failed:
                # handle err.workspace_gid, err.exception
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize orchestrator with application settings.

        Args:
            settings: Application configuration. max_concurrent_workspaces
                      controls the workspace concurrency semaphore.
        """
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_workspaces)
        self._global_request_semaphore = GlobalRequestSemaphore()
        self._log = get_logger(__name__)

    async def run(
        self, tenants: list[TenantConfig], *, cycle_start_iso: str | None = None
    ) -> OrchestratorResult:
        """Run extraction for all tenants concurrently.

        Launches one asyncio task per tenant. Tasks are concurrency-limited
        by the workspace semaphore. All results (successes and failures) are
        collected after all tasks complete.

        This method never raises. All failures are captured in the returned
        OrchestratorResult.failed list.

        Args:
            tenants: List of tenant configurations to extract. Empty list
                     returns an empty OrchestratorResult immediately.
            cycle_start_iso: Optional ISO 8601 UTC timestamp captured at
                cycle start. Used to set state file timestamps after
                successful extraction. If None, falls back to datetime.now(UTC).

        Returns:
            OrchestratorResult with succeeded GIDs and WorkspaceError objects
            for any failed workspaces.
        """
        if not tenants:
            self._log.info("orchestrator_run_skipped", reason="no_tenants")
            return OrchestratorResult(succeeded=[], failed=[])

        self._log.info("orchestrator_run_started", workspace_count=len(tenants))

        writer = EntityWriter(output_dir=self._settings.output_dir)

        # Launch all workspace tasks concurrently; gather collects all results
        # including exceptions (return_exceptions=True is a safety net — primary
        # isolation is the try/except inside _run_workspace).
        tasks = [
            self._run_workspace(tenant, writer, cycle_start_iso=cycle_start_iso)
            for tenant in tenants
        ]
        raw_results: list[WorkspaceError | None | BaseException] = list(
            await asyncio.gather(*tasks, return_exceptions=True)
        )

        succeeded: list[str] = []
        failed: list[WorkspaceError] = []

        for tenant, result in zip(tenants, raw_results, strict=True):
            if isinstance(result, BaseException):
                # Escaped exception — _run_workspace should never let this happen,
                # but handle defensively if it does.
                self._log.error(
                    "workspace_task_escaped_exception",
                    workspace_gid=tenant.workspace_gid,
                    exception_type=type(result).__name__,
                    exception=str(result),
                )
                failed.append(
                    WorkspaceError(
                        workspace_gid=tenant.workspace_gid,
                        exception=result
                        if isinstance(result, Exception)
                        else RuntimeError(str(result)),
                    )
                )
            elif isinstance(result, WorkspaceError):
                failed.append(result)
            else:
                succeeded.append(tenant.workspace_gid)

        orchestrator_result = OrchestratorResult(succeeded=succeeded, failed=failed)

        self._log.info(
            "orchestrator_run_complete",
            total=orchestrator_result.total,
            succeeded=len(succeeded),
            failed=len(failed),
            failed_workspace_gids=[e.workspace_gid for e in failed],
        )

        # Log one ERROR per failed workspace at orchestrator level
        for err in failed:
            self._log.error(
                "workspace_extraction_failed",
                workspace_gid=err.workspace_gid,
                exception_type=type(err.exception).__name__,
                exception=str(err.exception),
            )

        return orchestrator_result

    async def _run_workspace(
        self,
        tenant: TenantConfig,
        writer: EntityWriter,
        *,
        cycle_start_iso: str | None = None,
    ) -> WorkspaceError | None:
        """Run extraction for a single workspace with full isolation.

        Acquires the workspace semaphore before starting. Loads extraction
        state for incremental extraction (modified_since). On success, saves
        updated state with the cycle timestamp. On failure, state is left
        unchanged (all-or-nothing per workspace).

        Args:
            tenant: Tenant configuration with workspace_gid and PAT.
            writer: Shared atomic file writer (thread-safe for concurrent use).
            cycle_start_iso: Optional ISO 8601 UTC timestamp for state update.

        Returns:
            None on success, WorkspaceError on any failure.
        """
        from asana_extractor.extractors import (
            extract_workspace,
        )

        log = self._log.bind(workspace_gid=tenant.workspace_gid)

        async with self._semaphore:
            log.debug("workspace_task_started")
            try:
                # Load extraction state for incremental extraction.
                # Only tasks support modified_since (Asana API constraint);
                # users and projects always do a full refresh each cycle.
                existing_state = load_state(self._settings.output_dir, tenant.workspace_gid)
                modified_since: str | None = None
                if existing_state is not None:
                    modified_since = existing_state.last_cycle_start
                    log.info(
                        "incremental_extraction",
                        tasks_modified_since=modified_since,
                        cycle_count=existing_state.cycle_count,
                    )
                else:
                    log.info("full_extraction", reason="no_state_file")

                secrets_provider = _PatSecretsProvider(tenant.pat)
                async with RateLimitedClient(
                    secrets_provider,
                    global_semaphore=self._global_request_semaphore,
                ) as client:
                    await extract_workspace(
                        client=client,
                        writer=writer,
                        workspace_gid=tenant.workspace_gid,
                        modified_since=modified_since,
                    )

                # Save extraction state — only on success (all-or-nothing per workspace).
                # entity_timestamps records which entity types were extracted and when.
                # Currently all timestamps equal cycle_ts because the entire workspace
                # is extracted as one atomic unit.  The per-entity-type keys exist so
                # that future work can track partial-success scenarios (e.g. tasks
                # succeed but users fail) without changing the state file schema.
                cycle_ts = cycle_start_iso or datetime.now(UTC).isoformat()
                new_cycle_count = (existing_state.cycle_count + 1) if existing_state else 1
                new_state = ExtractionState(
                    workspace_gid=tenant.workspace_gid,
                    last_cycle_start=cycle_ts,
                    entity_timestamps={
                        "tasks": cycle_ts,
                        "projects": cycle_ts,
                        "users": cycle_ts,
                    },
                    cycle_count=new_cycle_count,
                )
                save_state(self._settings.output_dir, new_state)
                log.info("state_updated", cycle_count=new_cycle_count)

                log.info("workspace_task_succeeded")
                return None
            except Exception as exc:
                log.error(
                    "workspace_task_failed",
                    exception_type=type(exc).__name__,
                    exception=str(exc),
                    traceback=traceback.format_exc(),
                )
                return WorkspaceError(
                    workspace_gid=tenant.workspace_gid,
                    exception=exc,
                )
