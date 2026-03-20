---
phase: 12-incremental-extraction
plan: 02
subsystem: extraction
tags: [incremental, state-management, orchestrator, scheduler, modified_since]

# Dependency graph
requires:
  - phase: 12-incremental-extraction
    provides: ExtractionState dataclass with atomic load/save, modified_since wired through extract_workspace
provides:
  - Orchestrator loads state and passes modified_since to extract_workspace per workspace
  - Orchestrator saves state only on successful extraction (all-or-nothing)
  - Scheduler captures cycle_start_iso before extraction and passes through to orchestrator
affects: [12-03-PLAN, testing, scheduler]

# Tech tracking
tech-stack:
  added: []
  patterns: [state-load-save-per-workspace, cycle-start-timestamp-passthrough]

key-files:
  created: []
  modified: [src/asana_extractor/orchestrator.py, src/asana_extractor/scheduler.py]

key-decisions:
  - "cycle_start_iso defaults to datetime.now(UTC) in orchestrator when not provided by scheduler — supports run_once and testing"
  - "modified_since uses entity_timestamps['tasks'] from state — only tasks support modified_since in Asana API"
  - "save_state in success path only (before return None, never in except block) — all-or-nothing semantics"

patterns-established:
  - "State flow: scheduler captures timestamp → orchestrator.run() → _run_workspace() → state file"
  - "Incremental extraction detection via load_state returning None (full) vs ExtractionState (incremental)"

requirements-completed: [EXTR-10]

# Metrics
duration: 2min
completed: 2026-03-20
---

# Phase 12 Plan 02: Orchestrator & Scheduler State Wiring Summary

**Orchestrator wired to load/save extraction state per workspace with modified_since passthrough, scheduler captures cycle_start_iso before extraction begins**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-20T09:38:54Z
- **Completed:** 2026-03-20T09:41:22Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Orchestrator loads extraction state before each workspace extraction and passes modified_since to extract_workspace
- State saved only after ALL entity types succeed for a workspace (all-or-nothing per workspace)
- Scheduler captures UTC timestamp at cycle start (before extraction) and passes through orchestrator to state files
- First run with no state file proceeds as full extraction (modified_since=None) — identical to pre-incremental behavior

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire state load/save into orchestrator._run_workspace** - `ccf7988` (feat)
2. **Task 2: Capture cycle_start timestamp in scheduler and pass to orchestrator** - `37d8ead` (feat)

## Files Created/Modified
- `src/asana_extractor/orchestrator.py` - Added state import, load_state before extraction, save_state on success, cycle_start_iso parameter on run() and _run_workspace()
- `src/asana_extractor/scheduler.py` - Added datetime import, cycle_start_iso capture before extraction, pass to orchestrator.run()

## Decisions Made
- cycle_start_iso defaults to datetime.now(UTC) in orchestrator when scheduler doesn't provide it — supports run_once() and direct orchestrator testing
- modified_since uses entity_timestamps["tasks"] from state — only tasks endpoint supports modified_since in Asana API
- save_state placed in success path only (before `return None`, never in except block) — guarantees all-or-nothing semantics per workspace

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Full incremental extraction data flow is now wired: scheduler → orchestrator → extractors → state file
- Ready for Plan 03 (integration tests for the incremental extraction flow)
- All entity types get timestamps updated on success; only tasks use modified_since for API queries

## Self-Check: PASSED

---
*Phase: 12-incremental-extraction*
*Completed: 2026-03-20*
