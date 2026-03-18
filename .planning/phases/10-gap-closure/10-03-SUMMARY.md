---
phase: 10-gap-closure
plan: 03
subsystem: rate-limiting
tags: [asyncio, semaphore, dependency-injection, rate-limiting]

# Dependency graph
requires:
  - phase: 03-rate-limiter
    provides: "GlobalRequestSemaphore class and RateLimitedClient wrapper"
  - phase: 06-workspace-orchestrator
    provides: "WorkspaceOrchestrator creating RateLimitedClient per workspace"
provides:
  - "Single shared GlobalRequestSemaphore injected from orchestrator into all RateLimitedClient instances"
  - "Total in-flight requests capped at 50 regardless of workspace count"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: ["constructor injection of shared semaphore for global rate limiting"]

key-files:
  created: []
  modified:
    - "src/asana_extractor/orchestrator.py"
    - "src/asana_extractor/rate_limited_client.py"
    - "tests/test_rate_limited_client.py"

key-decisions:
  - "Semaphore injection via constructor parameter with None default for backward compatibility"
  - "Orchestrator owns the single GlobalRequestSemaphore instance, created in __init__"

patterns-established:
  - "Constructor injection for shared resources: optional parameter with fallback to independent instance"

requirements-completed: [RATE-05]

# Metrics
duration: 8min
completed: 2026-03-18
---

# Phase 10 Plan 03: Global Semaphore Summary

**Single GlobalRequestSemaphore created in orchestrator and injected into all RateLimitedClient instances, capping total in-flight requests at 50 across all workspaces**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-18T19:32:52Z
- **Completed:** 2026-03-18T19:40:24Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Orchestrator creates one `GlobalRequestSemaphore` and passes it to all `RateLimitedClient` instances via constructor injection
- With N concurrent workspaces, total in-flight requests are now capped at 50 (not N×50)
- `RateLimitedClient` accepts optional `global_semaphore` parameter with backward-compatible default (creates own if None)
- Three tests verify shared semaphore behavior: identity check, backward compat, and orchestrator integration

## Task Commits

Each task was committed atomically:

1. **Task 1: Inject shared semaphore into RateLimitedClient** - `87b4056` (feat)
2. **Task 1 fix: Fix paginated_get test mock** - `7059ce5` (fix)
3. **Task 2: Add test verifying shared semaphore** - `2da4508` (test)

**Plan metadata:** (pending)

## Files Created/Modified
- `src/asana_extractor/orchestrator.py` - Import GlobalRequestSemaphore, create in `__init__`, pass to all RateLimitedClient instances
- `src/asana_extractor/rate_limited_client.py` - Accept optional `global_semaphore` parameter (committed in 10-02, used by this plan)
- `tests/test_rate_limited_client.py` - TestSharedGlobalSemaphore class (3 tests) + fixed paginated_get mock

## Decisions Made
- Semaphore injection via constructor parameter with `None` default preserves backward compatibility — existing tests and standalone usage work without changes
- Orchestrator creates the semaphore in `__init__` (not `run()`) so it persists across multiple `run()` calls

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed paginated_get test mock incompatible with tenacity retry**
- **Found during:** Task 1 verification (pytest run)
- **Issue:** `test_paginated_get_yields_entities` mocked `client._client.paginated_get` but 10-02 refactored `paginated_get()` to use `_execute_get_envelope()` → `_request()`. Patching `_request` also failed because tenacity's `@retry` decorator wraps the class method, not the instance method.
- **Fix:** Mocked at `session.get` level instead (the HTTP layer), which tenacity calls through normally
- **Files modified:** `tests/test_rate_limited_client.py`
- **Verification:** All 99 tests pass
- **Committed in:** `7059ce5`

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Necessary for test suite to pass after 10-02 refactor. No scope creep.

## Issues Encountered
- `extract_workspace` is imported inside `_run_workspace()` (deferred import to avoid circular imports), so `patch("asana_extractor.orchestrator.extract_workspace")` fails — had to patch at source module `asana_extractor.extractors.extract_workspace` instead

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All 3 gap closure plans (10-01, 10-02, 10-03) are now complete
- Phase 10 is fully done — all rate limiting gaps closed
- RATE-02 (Retry-After parsing), RATE-01 (per-page rate limiting), and RATE-05 (global semaphore) are now fully implemented

---
*Phase: 10-gap-closure*
*Completed: 2026-03-18*

## Self-Check: PASSED

All files found, all commits verified.
