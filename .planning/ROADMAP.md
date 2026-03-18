# Roadmap: Asana Extractor

## Overview

Build a production-grade Asana data extractor in 9 phases: starting with project foundation and configuration, building the core API client with rate limiting, adding entity extraction logic, file output, scheduling, orchestration, then finishing with tests, documentation, and polish. Each phase delivers a coherent, testable increment. The architecture follows a bottom-up build order — lower layers (HTTP client, rate limiter) before higher layers (extraction, scheduling) — because each layer depends on the one below it.

## Phases

- [x] **Phase 1: Project Foundation** - Package structure, configuration, secrets, dev tooling (completed 2026-03-17)
- [x] **Phase 2: API Client** - Async HTTP client with auth, pagination, and retry logic (completed 2026-03-18)
- [x] **Phase 3: Rate Limiter** - Per-workspace token bucket rate limiting with 429/Retry-After handling (completed 2026-03-18)
- [x] **Phase 4: File Writer** - Atomic JSON file output with directory structure management (completed 2026-03-18)
- [x] **Phase 5: Entity Extraction** - User, project, and task extractors with workspace discovery
- [x] **Phase 6: Workspace Orchestrator** - Concurrent workspace processing with isolation and semaphore
- [x] **Phase 7: Scheduler** - Periodic execution with skip-on-overlap and graceful shutdown
- [x] **Phase 8: Testing** - Unit tests, integration tests, mypy, ruff
- [ ] **Phase 9: Documentation & Polish** - README, final cleanup, end-to-end validation (paused at e2e checkpoint)
- [ ] **Phase 10: Gap Closure** - Fix Retry-After parsing, per-page rate limiting, global semaphore

## Phase Details

### Phase 1: Project Foundation
**Goal**: Establish package structure, configuration management, secrets interface, and dev tooling so all subsequent phases have a solid base to build on.
**Depends on**: Nothing (first phase)
**Requirements**: AUTH-02, AUTH-03, CONF-01, CONF-02
**Success Criteria** (what must be TRUE):
  1. Python package is installable with `pip install -e .`
  2. Configuration loads from a config file and validates all required fields at startup
  3. Secrets interface loads PAT from .env file
  4. A new secrets provider can be added by implementing one class (no changes to extraction code)
  5. ruff and mypy run without errors on the codebase
**Plans**: 5 plans

Plans:
- [x] 01-01-PLAN.md — Package scaffold: pyproject.toml (hatchling, all runtime deps), src/asana_extractor/ package, py.typed marker, editable install
- [x] 01-02-PLAN.md — Configuration module: Settings pydantic model from config.json, load_config() with fail-fast validation and clear error messages
- [x] 01-03-PLAN.md — Secrets interface: SecretsProvider ABC + EnvSecretsProvider (.env via python-dotenv), extensible without modifying extraction code
- [x] 01-04-PLAN.md — Structured logging: configure_logging() + get_logger() using structlog with JSON output and workspace context binding
- [x] 01-05-PLAN.md — Dev tooling: ruff (lint/format), mypy (strict), pytest (asyncio_mode=auto) all configured in pyproject.toml; zero errors on codebase

### Phase 2: API Client
**Goal**: Build the async HTTP client that handles authentication, auto-pagination, and transient error retries — the foundation all extraction logic will use.
**Depends on**: Phase 1
**Requirements**: AUTH-01, EXTR-05, ERR-01, ERR-02, ERR-03
**Success Criteria** (what must be TRUE):
  1. Client authenticates with Asana API using PAT from secrets interface
  2. Client auto-paginates through multi-page results (follows next_page until None)
  3. Client retries transient errors (5xx, timeouts) with exponential backoff + jitter
  4. Client logs permanent errors (4xx) with workspace GID, entity type, endpoint, HTTP status and does not crash
  5. Client uses aiohttp connection pooling for efficient HTTP
**Plans**: 2 plans

Plans:
- [x] 02-01-PLAN.md — Exception hierarchy + base AsanaClient with auth, get(), retry, error classification
- [x] 02-02-PLAN.md — Auto-pagination async generator (paginated_get) + package exports

### Phase 3: Rate Limiter
**Goal**: Implement per-workspace rate limiting that respects Asana's 429/Retry-After and prevents one workspace from blocking others.
**Depends on**: Phase 2
**Requirements**: RATE-01, RATE-02, RATE-03, RATE-04, RATE-05, RATE-06
**Success Criteria** (what must be TRUE):
  1. Each workspace has its own rate limiter (~150 req/min)
  2. 429 responses trigger a pause for at least the Retry-After duration
  3. After a 429, no requests are sent until Retry-After expires (rejected requests count against quota)
  4. A global semaphore caps concurrent in-flight requests (coordinates concurrent workers)
  5. Workspace A hitting its rate limit does not slow down Workspace B
**Plans**: 5 plans

Plans:
- [x] 03-01-PLAN.md — TokenBucket (async acquire, continuous refill, reset_tokens) + WorkspaceRateLimiterRegistry (per-workspace isolation)
- [x] 03-02-PLAN.md — RateLimiter429State: 429 pause coordination, Retry-After handling, consecutive 429 fail-fast, bucket reset after pause
- [x] 03-03-PLAN.md — GlobalRequestSemaphore: asyncio.Semaphore wrapper capping 50 concurrent in-flight requests
- [x] 03-04-PLAN.md — RateLimitedClient: drop-in AsanaClient wrapper composing all rate limiting primitives
- [x] 03-05-PLAN.md — Package wiring: export RateLimitedClient from __init__.py, clean 429 placeholder from client.py

### Phase 4: File Writer
**Goal**: Build the atomic JSON file writer that creates the output directory structure and writes entities safely.
**Depends on**: Phase 1
**Requirements**: OUT-01, OUT-02, OUT-03, OUT-04
**Success Criteria** (what must be TRUE):
  1. Each entity is written as a separate JSON file
  2. Files are written to `output/{workspace_gid}/{type}/{entity_gid}.json`
  3. Writes use temp file + os.replace (no partial files on crash)
  4. Output directories are created automatically on first write
**Plans**: 3 plans

Plans:
- [x] 04-01: Atomic file writer (write to .tmp, os.replace to final path)
- [x] 04-02: Directory structure manager (create output/{workspace}/{type}/ on demand)
- [x] 04-03: JSON serialization with orjson

### Phase 5: Entity Extraction
**Goal**: Implement extraction logic for all entity types (workspaces, users, projects, tasks) with streaming writes to disk.
**Depends on**: Phase 2, Phase 3, Phase 4
**Requirements**: EXTR-01, EXTR-02, EXTR-03, EXTR-04, EXTR-08, EXTR-09
**Success Criteria** (what must be TRUE):
  1. Program discovers all workspaces for the authenticated user
  2. Users are extracted and written to disk for each workspace
  3. Projects are extracted and written to disk for each workspace
  4. Tasks are extracted per project and written to disk
  5. Entities are written to disk as extracted (not buffered in memory)
  6. Empty workspaces (0 users, 0 projects) complete without error
**Plans**: 3 plans

Plans:
- [x] 05-01-PLAN.md — Base extraction types (ExtractionResult, BaseExtractor ABC) + workspace discovery function
- [x] 05-02-PLAN.md — Entity extractors: UserExtractor, ProjectExtractor (with GID collection), TaskExtractor (concurrent per-project)
- [x] 05-03-PLAN.md — Workspace extraction orchestrator (users||projects → tasks) + package exports + edge cases

### Phase 6: Workspace Orchestrator
**Goal**: Run extraction across all workspaces concurrently with isolation — one workspace's failure doesn't affect others.
**Depends on**: Phase 5
**Requirements**: EXTR-06, EXTR-07
**Success Criteria** (what must be TRUE):
  1. All workspaces are extracted concurrently (asyncio tasks, semaphore-limited)
  2. If one workspace fails, all other workspaces complete their extraction
  3. Errors from failed workspaces are logged with full context
**Plans**: 3 plans

Plans:
- [x] 06-01-PLAN.md — Data contracts: TenantConfig, TenantProvider ABC, OrchestratorResult, WorkspaceError (tenant.py)
- [x] 06-02-PLAN.md — WorkspaceOrchestrator: asyncio.gather, per-workspace try/except isolation, semaphore, run() always returns OrchestratorResult
- [x] 06-03-PLAN.md — EnvTenantProvider (reads tenants from config.json) + package __init__.py exports

### Phase 7: Scheduler
**Goal**: Add periodic execution with skip-on-overlap and graceful shutdown, making the extractor a long-running service.
**Depends on**: Phase 6
**Requirements**: SCHED-01, SCHED-02, SCHED-03, ERR-04
**Success Criteria** (what must be TRUE):
  1. Extraction runs periodically at the configured interval (5min or 30s)
  2. If a cycle is still running when the next interval fires, the new cycle is skipped with a warning log
  3. SIGTERM/SIGINT triggers graceful shutdown — in-flight work completes before exit
  4. All log entries are structured JSON with workspace context
**Plans**: 2 plans

Plans:
- [x] 07-01-PLAN.md — Config extension (shutdown_timeout_seconds) + ExtractionScheduler class (interval loop, skip-on-overlap, signal handling, graceful shutdown)
- [x] 07-02-PLAN.md — Main entry point wiring (config → logging → secrets → orchestrator → scheduler, --run-once flag) + package exports

### Phase 8: Testing
**Goal**: Comprehensive test suite validating all components — API client, rate limiter, file writer, extraction, scheduling.
**Depends on**: Phase 7
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TEST-06
**Success Criteria** (what must be TRUE):
  1. Unit tests cover API client (pagination, retries, error handling)
  2. Unit tests cover file writer (atomic writes, directory creation, file paths)
  3. Unit tests cover scheduler (skip-on-overlap, graceful shutdown)
  4. Integration tests validate end-to-end extraction with mocked API
  5. `mypy --strict` passes on entire codebase
  6. `ruff check` passes on entire codebase
**Plans**: 5 plans

Plans:
- [x] 08-01-PLAN.md — Shared fixtures (conftest.py) + AsanaClient unit tests (9 tests)
- [x] 08-02-PLAN.md — Extractor unit tests (11 tests: UserExtractor, ProjectExtractor, TaskExtractor, discover_workspaces, extract_workspace)
- [x] 08-03-PLAN.md — Integration tests (end-to-end extraction with mocked Asana API)
- [x] 08-04-PLAN.md — Type checking and linting (mypy strict, ruff, fix all issues)
- [x] 08-05-PLAN.md — Scheduler unit tests (gap closure: run_once, skip-on-overlap, graceful shutdown, shutdown timeout)

### Phase 9: Documentation & Polish
**Goal**: Write the README documentation required by the exercise and do final cleanup.
**Depends on**: Phase 8
**Requirements**: DOC-01, DOC-02, DOC-03, DOC-04
**Success Criteria** (what must be TRUE):
  1. README explains how to set up and run the program
  2. README explains the system design and component architecture
  3. README explains how the design scales to thousands of workspaces/entities
  4. README explains the rate limit handling strategy in detail
  5. Program runs end-to-end against a real Asana account
**Plans**: 3 plans

Plans:
- [x] 09-01-PLAN.md — Cleanup: config.json.example, remove pydantic-settings, .gitignore, verify exports
- [x] 09-02-PLAN.md — Complete README with all sections (setup, architecture, rate limiting, scalability, testing, project structure)
- [ ] 09-03-PLAN.md — End-to-end validation (static analysis + real Asana account run) — paused at human checkpoint

### Phase 10: Gap Closure
**Goal**: Fix three rate limiting implementation gaps: Retry-After header parsing, per-page rate limiting in paginated_get, and truly global request semaphore.
**Depends on**: Phase 3, Phase 8
**Requirements**: RATE-02, RATE-01, RATE-05
**Success Criteria** (what must be TRUE):
  1. 429 responses respect the Retry-After header (not always 60s)
  2. paginated_get() acquires rate limiting tokens per page, not per call
  3. A single global semaphore caps total in-flight requests across all workspaces
  4. All existing tests continue to pass
  5. New tests cover each fix
**Plans**: 3 plans (all Wave 1 — independent, can run in parallel)

Plans:
- [x] 10-01-PLAN.md — Retry-After header parsing: extract from 429 response, propagate to record_429()
- [x] 10-02-PLAN.md — Per-page rate limiting: restructure paginated_get() to acquire tokens per page
- [x] 10-03-PLAN.md — Global semaphore: create once in orchestrator, inject into all clients

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
Note: Phase 4 (File Writer) depends only on Phase 1 and can run in parallel with Phases 2-3.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Project Foundation | 5/5 | Complete   | 2026-03-17 |
| 2. API Client | 2/2 | Complete | 2026-03-18 |
| 3. Rate Limiter | 5/5 | Complete | 2026-03-18 |
| 4. File Writer | 3/3 | Complete | 2026-03-18 |
| 5. Entity Extraction | 3/3 | Complete | 2026-03-18 |
| 6. Workspace Orchestrator | 3/3 | Complete | 2026-03-18 |
| 7. Scheduler | 2/2 | Complete | 2026-03-18 |
| 8. Testing | 5/5 | Complete | 2026-03-18 |
| 9. Documentation & Polish | 2/3 | In Progress (paused at e2e checkpoint) | - |
| 10. Gap Closure | 3/3 | Complete | 2026-03-18 |
