---
phase: 01-project-foundation
plan: "04"
subsystem: logging
tags: [structlog, json-logging, structured-logging, python]

# Dependency graph
requires:
  - phase: 01-project-foundation
    provides: package scaffold with src layout and installed dependencies (structlog available)
provides:
  - configure_logging() function wiring structlog JSON processor chain
  - get_logger() function returning bound logger for any module
  - Structured JSON log output with timestamp, level, event fields
  - Context binding via log.bind(workspace_gid=...) for workspace propagation
affects:
  - All subsequent phases that emit logs (all extraction/API phases)

# Tech tracking
tech-stack:
  added: [structlog>=24.0]
  patterns:
    - structlog processor chain with JSONRenderer
    - stdlib logging wrapped by structlog
    - cache_logger_on_first_use=False for test predictability

key-files:
  created:
    - src/asana_extractor/logging.py
    - tests/test_logging.py
  modified: []

key-decisions:
  - "cache_logger_on_first_use=False for test predictability (avoids stale cached loggers across test runs)"
  - "Root logger level updated via setLevel() directly — basicConfig() is no-op after first call"
  - "structlog.stdlib.BoundLogger as wrapper_class for full stdlib compatibility"

patterns-established:
  - "TDD RED→GREEN cycle: tests written and committed before implementation"
  - "configure_logging() called once at startup; get_logger(__name__) in each module"

requirements-completed:
  - CONF-01

# Metrics
duration: 1min
completed: 2026-03-17
---

# Phase 1 Plan 4: Structured Logging Setup Summary

**structlog JSON logging with configure_logging() + get_logger() via stdlib wrapper and processor chain including TimeStamper, JSONRenderer, and context binding**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-17T22:10:16Z
- **Completed:** 2026-03-17T22:11:22Z
- **Tasks:** 1 (TDD: 2 commits — RED + GREEN)
- **Files modified:** 2

## Accomplishments

- `configure_logging(log_level)` sets up structlog globally with JSON output to stdout
- `get_logger(name)` returns a structlog BoundLogger for any module
- `log.bind(workspace_gid="xyz")` propagates context to all subsequent events
- Log level parameter controls minimum level (DEBUG/INFO/WARNING/ERROR) correctly
- All 5 tests pass; verified JSON output has `timestamp`, `level`, `event` fields

## Task Commits

Each TDD phase committed atomically:

1. **RED: Failing tests** - `6602256` (test)
2. **GREEN: Implementation** - `b55d481` (feat)

## Files Created/Modified

- `src/asana_extractor/logging.py` — configure_logging() and get_logger() implementation using structlog
- `tests/test_logging.py` — 5 tests covering configure_logging, get_logger, bind, emit, and all log levels

## Decisions Made

- **cache_logger_on_first_use=False** — The plan's reference implementation used `True`, but this causes stale cached loggers across test runs (the second `configure_logging()` call wouldn't update already-cached loggers). Changed to `False` for correct test behavior.
- **Root logger level via setLevel()** — `logging.basicConfig()` is a no-op after the first call, so `logging.getLogger().setLevel()` is called directly to support multiple `configure_logging()` invocations (common in tests).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Set `cache_logger_on_first_use=False` and added explicit `setLevel()` call**
- **Found during:** GREEN phase (running `test_configure_logging_accepts_all_levels`)
- **Issue:** The reference implementation used `cache_logger_on_first_use=True` and only called `basicConfig()` for log level. In test suites where `configure_logging()` is called multiple times, cached loggers would not pick up new log levels, causing the level test to fail.
- **Fix:** Set `cache_logger_on_first_use=False` and added `logging.getLogger().setLevel(...)` call alongside `basicConfig()` to ensure level changes take effect after the first invocation.
- **Files modified:** src/asana_extractor/logging.py
- **Verification:** All 5 tests pass; `test_configure_logging_accepts_all_levels` verifies level changes are reflected.
- **Committed in:** b55d481 (feat commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential fix for correct test behavior. No scope creep.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Logging foundation complete; any module can `from asana_extractor.logging import configure_logging, get_logger`
- Context binding via `log.bind(workspace_gid=...)` ready for Phase 2 API client integration
- JSON output with consistent fields ready for production observability

## Self-Check

Checking created files and commits:

- `src/asana_extractor/logging.py`: FOUND
- `tests/test_logging.py`: FOUND
- Commit `6602256` (RED): FOUND
- Commit `b55d481` (GREEN): FOUND

## Self-Check: PASSED

---
*Phase: 01-project-foundation*
*Completed: 2026-03-17*
