---
phase: 11-readme-rate-limit-update
plan: 01
subsystem: docs
tags: [readme, rate-limiting, semaphore, incremental-extraction, documentation]

# Dependency graph
requires:
  - phase: 10-gap-closure
    provides: Retry-After parsing, per-page rate limiting, global semaphore implementation
  - phase: 12-incremental-extraction
    provides: modified_since support, state.py, models.py
provides:
  - Accurate README reflecting Phase 10 rate limiting and Phase 12 incremental extraction
  - Corrected concurrency diagram with shared global semaphore label
  - Updated project structure tree with models.py and state.py
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - README.md

key-decisions:
  - "Fixed WorkspaceOrchestrator description to clarify request semaphore is shared, not independent per workspace"
  - "Silently removed incremental extraction from Known Limitations (no 'now supported' note per user decision)"

patterns-established: []

requirements-completed: [DOC-02, DOC-04]

# Metrics
duration: 3min
completed: 2026-03-20
---

# Phase 11 Plan 01: README Rate Limit & Incremental Extraction Update Summary

**Corrected README semaphore descriptions from per-client to shared global, removed stale incremental extraction limitation, added models.py/state.py to project structure**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-20T10:36:28Z
- **Completed:** 2026-03-20T10:39:40Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Fixed concurrency diagram label from "(request semaphore: 50 max per client)" to "(shared semaphore: 50 max total)"
- Fixed Scalability table from "Per-workspace request semaphore" to "A shared global request semaphore (50 in-flight across all workspaces)"
- Removed stale "No delta/incremental extraction" Known Limitation and "incremental/delta extraction" from Future scaling
- Added incremental extraction to Overview capabilities and Scalability table
- Added models.py and state.py to Project Structure tree in alphabetical order
- Full audit of all semaphore/rate-limit mentions confirmed consistency across all README sections

## Task Commits

Each task was committed atomically:

1. **Task 1: Audit and fix all rate-limit mentions + remove stale content** - `b3a40b8` (docs)
2. **Task 2: Final audit — verify all rate-limit mentions are consistent** - `82f3cf3` (fix)

## Files Created/Modified
- `README.md` — 7 surgical edits: semaphore labels, scalability table, stale limitation removal, overview capability, project structure tree

## Decisions Made
- Fixed WorkspaceOrchestrator Architecture description (line 103) — previously grouped "request semaphore" with "independent", now correctly says "shared global request semaphore" (discovered during Task 2 audit)
- Silently removed incremental extraction limitation per user decision (no "now supported" note added)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed WorkspaceOrchestrator description grouping request semaphore as independent**
- **Found during:** Task 2 (consistency audit)
- **Issue:** Line 103 said "Each workspace gets its own RateLimitedClient instance (with independent token bucket, 429 state, and request semaphore)" — grouping request semaphore as independent is inaccurate since it's shared/global
- **Fix:** Changed to "(with independent token bucket and 429 state, plus a shared global request semaphore)"
- **Files modified:** README.md
- **Verification:** `grep -ci 'per.client' README.md` returns 0; all semaphore references now correctly describe shared/global behavior
- **Committed in:** 82f3cf3 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary correction discovered during the planned audit. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 11 complete (single plan phase) — README is now fully consistent with codebase
- Ready for next milestone planning or additional phases

---
*Phase: 11-readme-rate-limit-update*
*Completed: 2026-03-20*
