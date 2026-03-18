---
phase: 07-scheduler
plan: 01
subsystem: scheduler
tags: [asyncio, scheduler, graceful-shutdown, signal-handling, structlog]

# Dependency graph
requires:
  - phase: 06-workspace-orchestrator
    provides: WorkspaceOrchestrator.run() interface, OrchestratorResult, TenantProvider ABC
  - phase: 01-project-foundation
    provides: Settings model with extraction_interval, configure_logging, get_logger
provides:
  - ExtractionScheduler class with periodic loop, skip-on-overlap, graceful shutdown
  - shutdown_timeout_seconds field on Settings
  - scheduler.py module with full lifecycle management
affects: [07-02, 07-03, 07-04, 07-05, 08-testing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "asyncio signal handlers via loop.add_signal_handler() for SIGTERM/SIGINT"
    - "asyncio.Event for shutdown coordination between signal handler and run loop"
    - "asyncio.wait_for() with timeout for both interval wait and shutdown wait"
    - "Simple bool _running flag (safe in single-threaded asyncio)"
    - "time.monotonic() for cycle duration measurement"
    - "TYPE_CHECKING imports to avoid circular imports"

key-files:
  created: [src/asana_extractor/scheduler.py]
  modified: []

key-decisions:
  - "shutdown_timeout_seconds already existed in config.py from prior work — Task 1 was pre-completed"
  - "asyncio.TimeoutError aliased to builtin TimeoutError (ruff UP041) — fixed during implementation"
  - "Simple bool _running flag is safe because asyncio is single-threaded — no lock needed"
  - "cycle_task initialized before while loop (t=0 cycle) so shutdown handler always has a valid task reference"

patterns-established:
  - "Scheduler pattern: asyncio.wait_for(event.wait(), timeout=interval) for interval + shutdown"
  - "Lifecycle logging pattern: structured events for all state transitions"
  - "Signal cleanup: remove_signal_handler after shutdown to restore defaults"

requirements-completed: [SCHED-01, SCHED-02, SCHED-03]

# Metrics
duration: 7min
completed: 2026-03-18
---

# Phase 7 Plan 01: ExtractionScheduler Summary

**ExtractionScheduler with asyncio periodic loop, skip-on-overlap detection, SIGTERM/SIGINT graceful shutdown with configurable timeout, and structured lifecycle logging**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-18T07:16:12Z
- **Completed:** 2026-03-18T07:24:00Z
- **Tasks:** 2
- **Files modified:** 1 (scheduler.py created)

## Accomplishments
- ExtractionScheduler class with full lifecycle: run(), run_once(), _run_cycle(), stop(), _handle_signal()
- Periodic loop fires first cycle at t=0, then every extraction_interval seconds
- Skip-on-overlap: simple `_running` bool flag, logs WARNING `cycle_skipped` with fields
- SIGTERM/SIGINT signal handlers installed via asyncio loop.add_signal_handler()
- Graceful shutdown: waits up to shutdown_timeout_seconds for in-flight cycle; cancels with WARNING if exceeded
- All structured log events matching CONTEXT.md spec: cycle_started, cycle_complete, cycle_skipped, shutdown_requested, waiting_for_cycle, shutdown_complete, shutdown_timeout_exceeded

## Task Commits

Each task was committed atomically:

1. **Task 1: Add shutdown_timeout_seconds to Settings** - `c38831c` (feat) — pre-existing commit
2. **Task 2: Create ExtractionScheduler class** - `a07f48d` (feat)

**Plan metadata:** *(pending)*

## Files Created/Modified
- `src/asana_extractor/scheduler.py` - ExtractionScheduler: periodic loop, skip-on-overlap, graceful shutdown

## Decisions Made
- `shutdown_timeout_seconds` was already added to Settings in a prior execution (commit c38831c) — no re-work needed
- Used `TimeoutError` (builtin) instead of `asyncio.TimeoutError` (ruff UP041 fix applied during Task 2)
- `cycle_task` is initialized before the while loop from the t=0 cycle — ensures shutdown handler always has a valid task reference even if shutdown is requested before the first interval fires

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed asyncio.TimeoutError → TimeoutError (ruff UP041)**
- **Found during:** Task 2 (Create ExtractionScheduler class)
- **Issue:** ruff reported UP041: `asyncio.TimeoutError` is an alias; should use builtin `TimeoutError`
- **Fix:** Replaced both `except asyncio.TimeoutError:` occurrences with `except TimeoutError:`
- **Files modified:** src/asana_extractor/scheduler.py
- **Verification:** `ruff check src/asana_extractor/scheduler.py` passes
- **Committed in:** a07f48d (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug/lint fix)
**Impact on plan:** Minor lint fix — no behavior change, required for ruff compliance.

## Issues Encountered
None — both tasks executed cleanly. Task 1 was already committed from a prior partial execution; verified criteria met before proceeding.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ExtractionScheduler class is complete and passes all quality checks
- Ready for Task 2+ of 07-scheduler: __main__.py wiring, --run-once flag, integration with EnvTenantProvider
- Phase 8 (Testing) can mock the scheduler via run_once() for integration tests

## Self-Check: PASSED

- FOUND: src/asana_extractor/scheduler.py
- FOUND: .planning/phases/07-scheduler/07-01-SUMMARY.md
- FOUND commit: c38831c (feat(07-01): add shutdown_timeout_seconds to Settings)
- FOUND commit: a07f48d (feat(07-01): create ExtractionScheduler with periodic loop and graceful shutdown)

---
*Phase: 07-scheduler*
*Completed: 2026-03-18*
