---
phase: 01-project-foundation
plan: "05"
subsystem: infra
tags: [ruff, mypy, pytest, linting, type-checking, code-quality]

# Dependency graph
requires:
  - phase: 01-project-foundation
    provides: pyproject.toml package scaffold with dev dependencies
provides:
  - ruff linting/formatting config (target py312, line-length 100, E/W/F/I/B/C4/UP/ANN/RUF rules)
  - mypy strict type checking config with structlog/dotenv overrides
  - pytest config (tests/ directory, asyncio_mode=auto)
  - Zero-error baseline for ruff check, mypy, and pytest across all current source files
affects:
  - all future phases (must maintain ruff/mypy/pytest clean baseline)

# Tech tracking
tech-stack:
  added: [ruff>=0.3, mypy>=1.8, pytest>=8.0, pytest-asyncio>=0.23]
  patterns:
    - "Single pyproject.toml for all tool config (no separate mypy.ini, .ruff.toml, pytest.ini)"
    - "Strict mypy mode with ignore_missing_imports for third-party stubs"
    - "noqa: ANN401 for Any return types where third-party libraries lack stubs"

key-files:
  created: []
  modified:
    - pyproject.toml
    - src/asana_extractor/logging.py
    - tests/test_config.py
    - tests/test_logging.py

key-decisions:
  - "structlog.* added to mypy overrides (ignore_missing_imports=true) — no stubs available"
  - "get_logger() return type changed to Any with noqa: ANN401 — structlog.get_logger() returns Any"
  - "ANN101/ANN102 ignore rules removed — these rules were deleted from newer ruff versions"

patterns-established:
  - "All tool config lives in pyproject.toml — single source of truth"
  - "mypy strict mode is the baseline — future modules must pass with 0 errors"
  - "ruff format + ruff check must both pass before commits"

requirements-completed: [CONF-01, CONF-02]

# Metrics
duration: 4min
completed: 2026-03-17
---

# Phase 1 Plan 05: Dev Tooling Config Summary

**ruff (linting/formatting), mypy (strict mode), and pytest all configured in pyproject.toml with zero errors on the full codebase**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-17T22:10:18Z
- **Completed:** 2026-03-17T22:14:33Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added `[tool.ruff]`, `[tool.mypy]`, and `[tool.pytest.ini_options]` sections to pyproject.toml
- Fixed all ruff and mypy errors to zero on existing codebase (config.py, secrets.py, logging.py, __init__.py, __main__.py + test files)
- All 17 existing tests continue to pass after lint/type fixes

## Task Commits

Each task was committed atomically:

1. **Task 1: Add ruff, mypy, and pytest config to pyproject.toml** - `b55d481` (chore)
2. **Task 2: Run linting and type checking — fix any issues** - `8caf1db` (fix)

**Plan metadata:** TBD (docs)

## Files Created/Modified
- `pyproject.toml` - Added [tool.ruff], [tool.mypy], [tool.pytest.ini_options] sections; removed invalid ANN101/ANN102; added structlog.* to mypy overrides
- `src/asana_extractor/logging.py` - Changed get_logger() return type to `Any` with noqa: ANN401; added `from typing import Any`
- `tests/test_config.py` - Ruff auto-removed unused `import sys` and `Settings` import
- `tests/test_logging.py` - Ruff auto-removed unused `import json`, `import pytest`, `import structlog`

## Decisions Made
- **structlog stubs**: `structlog.*` added to `[[tool.mypy.overrides]]` with `ignore_missing_imports = true` since no stubs are available
- **ANN401 noqa**: `get_logger()` returns `Any` (with `# noqa: ANN401`) because `structlog.get_logger()` has no return type annotation and mypy infers `Any`
- **ANN101/ANN102 removal**: These ruff rules were removed in newer versions — the `ignore` list was cleaned up to avoid spurious warnings

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed stale/invalid ruff ignore rules ANN101 and ANN102**
- **Found during:** Task 2 (Run linting and type checking)
- **Issue:** pyproject.toml `ignore` list had `ANN101`/`ANN102` which ruff warned about: "rules have been removed and ignoring them has no effect"
- **Fix:** Replaced with a comment-only block noting they were removed in newer ruff
- **Files modified:** pyproject.toml
- **Verification:** ruff check runs without deprecation warnings
- **Committed in:** 8caf1db (Task 2 commit)

**2. [Rule 2 - Missing Critical] Added structlog.* to mypy overrides**
- **Found during:** Task 2 (Run linting and type checking)  
- **Issue:** mypy strict mode flagged `Returning Any from function declared to return "BoundLogger"` because structlog has no type stubs
- **Fix:** Added `structlog.*` to `[[tool.mypy.overrides]]` in pyproject.toml, changed `get_logger()` return to `Any` with noqa
- **Files modified:** pyproject.toml, src/asana_extractor/logging.py
- **Verification:** mypy src/ → "Success: no issues found in 5 source files"
- **Committed in:** 8caf1db (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 bug/invalid config, 1 missing critical override)
**Impact on plan:** Both fixes necessary for correct tool operation. No scope creep.

## Issues Encountered
None — ruff and mypy errors were straightforward and all auto-fixable or directly addressed.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Dev tooling baseline established: ruff, mypy, pytest all clean
- All future phases must maintain this zero-error baseline
- pyproject.toml is the single config file for all tools
- Phase 1 complete — all 5 plans executed

---
*Phase: 01-project-foundation*
*Completed: 2026-03-17*

## Self-Check: PASSED

- FOUND: .planning/phases/01-project-foundation/01-05-SUMMARY.md
- FOUND: pyproject.toml
- FOUND: commit b55d481 (Task 1)
- FOUND: commit 8caf1db (Task 2)
- FOUND: commit 1583629 (Plan metadata)
- ruff check src/ tests/ → All checks passed!
- mypy src/ → Success: no issues found in 5 source files
- pytest tests/ → 17 passed in 0.17s
