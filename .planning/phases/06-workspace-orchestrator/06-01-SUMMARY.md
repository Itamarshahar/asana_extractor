---
phase: 06-workspace-orchestrator
plan: "01"
subsystem: api
tags: [dataclass, abc, multi-tenant, orchestration, asyncio]

# Dependency graph
requires:
  - phase: 01-project-foundation
    provides: SecretsProvider ABC pattern — TenantProvider follows the same structural ABC design
provides:
  - TenantConfig dataclass (workspace_gid, pat) — one tenant identity
  - TenantProvider ABC with list_tenants() contract — extensible to any credential store
  - WorkspaceError dataclass (workspace_gid, exception) — failure diagnostics
  - OrchestratorResult dataclass (succeeded, failed, total, has_failures) — never-raises run() contract
affects:
  - 06-workspace-orchestrator (plans 02 and 03 implement these contracts)
  - 07-scheduler (inspects OrchestratorResult to decide log warnings)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - ABC-based interface matching SecretsProvider structural pattern
    - Plain dataclasses for simple value objects (no Pydantic)
    - run() never raises — all failures captured in OrchestratorResult.failed

key-files:
  created:
    - src/asana_extractor/tenant.py
  modified: []

key-decisions:
  - "Plain dataclasses for TenantConfig, WorkspaceError, OrchestratorResult — no Pydantic needed for simple value objects"
  - "TenantProvider ABC follows SecretsProvider pattern — extensible without changing orchestrator code"
  - "OrchestratorResult.total and has_failures as computed properties — read-only derived values from stored lists"

patterns-established:
  - "TenantProvider ABC: subclass + implement list_tenants() + pass to caller (same pattern as SecretsProvider)"
  - "OrchestratorResult contract: run() always returns, never raises — callers inspect .failed"

requirements-completed:
  - EXTR-06
  - EXTR-07

# Metrics
duration: 1min
completed: 2026-03-18
---

# Phase 6 Plan 1: Workspace Orchestrator Data Contracts Summary

**TenantConfig, TenantProvider ABC, OrchestratorResult, and WorkspaceError data contracts for multi-tenant workspace orchestration, following the SecretsProvider ABC pattern**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-18T05:57:07Z
- **Completed:** 2026-03-18T05:58:22Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created `src/asana_extractor/tenant.py` with all four exported types
- TenantConfig dataclass holds workspace_gid and pat for one tenant
- TenantProvider ABC defines list_tenants() → list[TenantConfig] contract, extensible to any credential store
- WorkspaceError dataclass holds workspace_gid + exception for per-workspace failure diagnostics
- OrchestratorResult dataclass captures succeeded/failed lists with total and has_failures computed properties — run() never raises
- All types pass ruff and mypy strict; ABC enforcement verified (TenantProvider cannot be instantiated directly)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create tenant.py with TenantConfig, TenantProvider, OrchestratorResult, WorkspaceError** - `4f5df3a` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `src/asana_extractor/tenant.py` - Multi-tenant data contracts: TenantConfig, TenantProvider ABC, WorkspaceError, OrchestratorResult

## Decisions Made
- Used plain dataclasses (not Pydantic) for TenantConfig, WorkspaceError, and OrchestratorResult — these are simple value objects with no validation requirements
- Followed SecretsProvider ABC structural pattern exactly for TenantProvider: abstractmethod, Google-style docstrings, extensibility note in docstring
- OrchestratorResult.total and has_failures implemented as `@property` — derived read-only values that don't need storage

## Deviations from Plan

None - plan executed exactly as written.

(Auto-fix: ruff I001 import-sort was auto-fixed via `ruff check --fix` — blank line between `from __future__ import annotations` and stdlib imports was removed per isort conventions. Not a logic change.)

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- tenant.py complete with all four types — Plan 06-02 (WorkspaceOrchestrator) implements `async def run(self, tenants: list[TenantConfig]) -> OrchestratorResult` against these contracts
- Plan 06-03 (EnvTenantProvider) satisfies TenantProvider ABC for env-var-based tenant configuration

---
*Phase: 06-workspace-orchestrator*
*Completed: 2026-03-18*
