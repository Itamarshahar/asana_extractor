---
phase: 07-scheduler
plan: 02
subsystem: infra
tags: [asyncio, argparse, structlog, entrypoint, cli]

# Dependency graph
requires:
  - phase: 07-01
    provides: ExtractionScheduler with run() and run_once() methods
  - phase: 06-workspace-orchestrator
    provides: WorkspaceOrchestrator, EnvTenantProvider
  - phase: 01-project-foundation
    provides: load_config, configure_logging, EnvSecretsProvider
provides:
  - Fully-wired __main__.py entry point (python -m asana_extractor)
  - --run-once CLI flag for single extraction cycle
  - ExtractionScheduler exported from package public API
affects: [integration-tests, deployment, end-to-end usage]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Startup sequence: load_config → configure_logging → secrets → orchestrator → tenant → scheduler"
    - "argparse for CLI flags (stdlib, supports --help)"
    - "KeyboardInterrupt catch around asyncio.run() for edge-case signal handling"

key-files:
  created: []
  modified:
    - src/asana_extractor/__main__.py
    - src/asana_extractor/__init__.py

key-decisions:
  - "argparse for --run-once flag — stdlib, no extra deps, clean --help output"
  - "PAT loaded at startup via get_secret() for fail-fast validation, actual per-workspace PATs come from config.json tenants array"
  - "KeyboardInterrupt caught outside asyncio.run() to handle SIGINT during event loop startup/teardown edge case"

patterns-established:
  - "Startup sequence: config → logging → secrets → orchestrator → tenant → scheduler"

requirements-completed: [SCHED-01, SCHED-03, ERR-04]

# Metrics
duration: 4min
completed: 2026-03-18
---

# Phase 7 Plan 2: Entry Point Wiring Summary

**Fully-wired `__main__.py` startup sequence with `--run-once` CLI flag and `ExtractionScheduler` exported from package public API**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-18T09:41:18Z
- **Completed:** 2026-03-18T09:44:43Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `__main__.py` wires full startup sequence: load_config → configure_logging → EnvSecretsProvider → WorkspaceOrchestrator → EnvTenantProvider → ExtractionScheduler
- `--run-once` CLI flag dispatches to `scheduler.run_once()` for single extraction and exit
- Default mode runs `scheduler.run()` for continuous periodic loop
- Fail-fast on missing config.json or unset ASANA_PAT (handled by existing load_config/get_secret)
- `ExtractionScheduler` added to `__init__.py` exports with alphabetically-sorted `__all__`

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire __main__.py entry point** - `da334dd` (feat)
2. **Task 2: Update package exports** - `dd56020` (feat)

**Plan metadata:** _(docs commit — created now)_

## Files Created/Modified
- `src/asana_extractor/__main__.py` — Fully-wired entry point with argparse, startup sequence, asyncio.run dispatch
- `src/asana_extractor/__init__.py` — Added ExtractionScheduler import and __all__ entry (alphabetically sorted)

## Decisions Made
- Used `argparse` for `--run-once` flag — stdlib, clean `--help` output, Claude's discretion area from CONTEXT.md
- PAT loaded at startup via `get_secret("ASANA_PAT")` for fail-fast validation; actual per-workspace PATs come from `config.json` tenants array (EnvTenantProvider)
- `KeyboardInterrupt` caught outside `asyncio.run()` — handles SIGINT edge case during event loop startup/teardown; normal case handled by scheduler's signal handler

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 07 complete — `python -m asana_extractor` is a fully-wired long-running service
- `python -m asana_extractor --run-once` provides single-cycle extraction for testing/CI
- Ready for Phase 08 (rate limiter integration) or end-to-end testing

---
*Phase: 07-scheduler*
*Completed: 2026-03-18*

## Self-Check: PASSED
- `src/asana_extractor/__main__.py` — FOUND
- `src/asana_extractor/__init__.py` — FOUND
- `da334dd` commit — FOUND
- `dd56020` commit — FOUND
