---
phase: 06-workspace-orchestrator
plan: "02"
subsystem: orchestration
tags: [asyncio, concurrency, isolation, workspace, semaphore, structlog]

# Dependency graph
requires:
  - phase: 06-01
    provides: TenantConfig, WorkspaceError, OrchestratorResult dataclasses in tenant.py
  - phase: 03-rate-limiter
    provides: RateLimitedClient async context manager
  - phase: 01-project-foundation
    provides: Settings.max_concurrent_workspaces, get_logger, SecretsProvider ABC
  - phase: 02-api-client
    provides: AsanaClient (wrapped by RateLimitedClient)
provides:
  - WorkspaceOrchestrator class with run(tenants) method
  - _PatSecretsProvider inline helper for per-tenant PAT injection
  - Concurrent workspace extraction with semaphore-limited parallelism
  - Per-workspace error isolation (one failure never aborts others)
affects: [07-scheduler, 08-entry-point, 09-testing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "asyncio.gather with return_exceptions=True for concurrent task collection without cancellation"
    - "Deferred import inside method body to break potential circular imports"
    - "Inline SecretsProvider subclass (_PatSecretsProvider) to inject per-tenant PATs"
    - "try/except inside workspace coroutine as primary isolation — return_exceptions=True is safety net"

key-files:
  created:
    - src/asana_extractor/orchestrator.py
  modified: []

key-decisions:
  - "asyncio.gather NOT asyncio.TaskGroup — TaskGroup cancels on first error, violating EXTR-07"
  - "try/except is primary isolation inside _run_workspace, not return_exceptions=True"
  - "Each workspace gets its own RateLimitedClient for independent rate limiting state"
  - "EntityWriter shared across workspace tasks (writes to separate file paths per workspace)"
  - "extract_workspace imported inside _run_workspace to avoid circular imports with extractors.py"
  - "_PatSecretsProvider private inline class injects per-tenant PAT without exposing it in public API"

patterns-established:
  - "Inline private SecretsProvider subclass: inject per-tenant PAT into RateLimitedClient without changing orchestrator interface"
  - "Defensive gather result handling: check isinstance(result, BaseException) as safety net for escaped exceptions"

requirements-completed: [EXTR-06, EXTR-07]

# Metrics
duration: 2min
completed: 2026-03-18
---

# Phase 06 Plan 02: WorkspaceOrchestrator Summary

**WorkspaceOrchestrator with asyncio.gather-based concurrent extraction, per-workspace try/except isolation, and semaphore-capped parallelism delivering EXTR-06 and EXTR-07**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-18T06:01:13Z
- **Completed:** 2026-03-18T06:03:28Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- WorkspaceOrchestrator.run() launches all workspace tasks concurrently via asyncio.gather
- Each workspace task isolated in try/except — one failure never aborts others (EXTR-07)
- Semaphore caps concurrent workspace extraction at settings.max_concurrent_workspaces
- run() always returns OrchestratorResult and never raises (EXTR-06)
- Per-workspace RateLimitedClient via _PatSecretsProvider inline helper
- Structured logging with workspace_gid context: DEBUG on start, INFO on success, ERROR on failure with full traceback

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement WorkspaceOrchestrator with concurrent isolation** - `82265e6` (feat)

**Plan metadata:** *(pending docs commit)*

## Files Created/Modified
- `src/asana_extractor/orchestrator.py` - WorkspaceOrchestrator class with run(), _run_workspace(), and _PatSecretsProvider

## Decisions Made
- Used `asyncio.gather(*tasks, return_exceptions=True)` NOT `asyncio.TaskGroup` — TaskGroup cancels all tasks on first error, which would violate workspace isolation requirement EXTR-07
- `try/except` inside `_run_workspace` is the primary isolation mechanism; `return_exceptions=True` is a defensive safety net for `BaseException` subclasses that escape the `except Exception`
- Each workspace gets its own `RateLimitedClient` instance so each workspace has independent rate limiting state (bucket, 429 tracking) — no cross-workspace interference
- `EntityWriter` is shared across workspace tasks because it writes to separate file paths per workspace (no conflict), and creating one instance per workspace would be wasteful
- `extract_workspace` imported inside `_run_workspace` (deferred import) to avoid potential circular imports when Phase 5's `extractors.py` is built
- `_PatSecretsProvider` private class injects per-tenant PAT into `RateLimitedClient` without exposing the PAT in the orchestrator's public API
- Return type of `_run_workspace` changed from `Any` to `WorkspaceError | None` to satisfy ruff ANN401 (disallow `Any` in return types)
- Removed `noqa: PLC0415` (pylint import-outside-toplevel) — PLC0415 is not enabled in this project's ruff config

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed return type annotation on `_run_workspace`**
- **Found during:** Task 1 (ruff check after implementation)
- **Issue:** Plan specified `-> Any` return type on `_run_workspace`, but ruff ANN401 disallows dynamically typed expressions in signatures
- **Fix:** Changed return type to `WorkspaceError | None` (the two actual return values), removed `Any` import, changed `raw_results` list annotation to `list[WorkspaceError | None | BaseException]`
- **Files modified:** src/asana_extractor/orchestrator.py
- **Verification:** `ruff check src/asana_extractor/orchestrator.py` passes
- **Committed in:** 82265e6 (Task 1 commit)

**2. [Rule 1 - Bug] Removed invalid `noqa: PLC0415` directive**
- **Found during:** Task 1 (ruff check after implementation)
- **Issue:** Plan included `# noqa: PLC0415` comment on deferred import, but PLC0415 (pylint's import-outside-toplevel) is not enabled in this project's ruff config — ruff flagged it as `RUF100: Unused noqa directive`
- **Fix:** Replaced with a plain descriptive comment
- **Files modified:** src/asana_extractor/orchestrator.py
- **Verification:** `ruff check src/asana_extractor/orchestrator.py` passes
- **Committed in:** 82265e6 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — ruff compliance fixes from plan template code)
**Impact on plan:** Both fixes are cosmetic/type-annotation corrections. No logic or behavior changes. No scope creep.

## Issues Encountered
None — plan executed cleanly after fixing the two ruff violations in the provided code template.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- WorkspaceOrchestrator is complete and ready for Phase 06-03 (entry point / __main__ wiring)
- extract_workspace (Phase 5) is imported via deferred import — will resolve at runtime once Phase 5 is complete
- Phase 7 (Scheduler) can call `orchestrator.run(tenants)` and inspect `OrchestratorResult`

---
*Phase: 06-workspace-orchestrator*
*Completed: 2026-03-18*

## Self-Check: PASSED
