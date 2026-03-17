# Roadmap: Asana Extractor

## Overview

Build a production-grade Asana data extractor in 9 phases: starting with project foundation and configuration, building the core API client with rate limiting, adding entity extraction logic, file output, scheduling, orchestration, then finishing with tests, documentation, and polish. Each phase delivers a coherent, testable increment. The architecture follows a bottom-up build order — lower layers (HTTP client, rate limiter) before higher layers (extraction, scheduling) — because each layer depends on the one below it.

## Phases

- [x] **Phase 1: Project Foundation** - Package structure, configuration, secrets, dev tooling (completed 2026-03-17)
- [ ] **Phase 2: API Client** - Async HTTP client with auth, pagination, and retry logic
- [ ] **Phase 3: Rate Limiter** - Per-workspace token bucket rate limiting with 429/Retry-After handling
- [ ] **Phase 4: File Writer** - Atomic JSON file output with directory structure management
- [ ] **Phase 5: Entity Extraction** - User, project, and task extractors with workspace discovery
- [ ] **Phase 6: Workspace Orchestrator** - Concurrent workspace processing with isolation and semaphore
- [ ] **Phase 7: Scheduler** - Periodic execution with skip-on-overlap and graceful shutdown
- [ ] **Phase 8: Testing** - Unit tests, integration tests, mypy, ruff
- [ ] **Phase 9: Documentation & Polish** - README, final cleanup, end-to-end validation

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
- [ ] 01-01-PLAN.md — Package scaffold: pyproject.toml (hatchling, all runtime deps), src/asana_extractor/ package, py.typed marker, editable install
- [ ] 01-02-PLAN.md — Configuration module: Settings pydantic model from config.json, load_config() with fail-fast validation and clear error messages
- [ ] 01-03-PLAN.md — Secrets interface: SecretsProvider ABC + EnvSecretsProvider (.env via python-dotenv), extensible without modifying extraction code
- [ ] 01-04-PLAN.md — Structured logging: configure_logging() + get_logger() using structlog with JSON output and workspace context binding
- [ ] 01-05-PLAN.md — Dev tooling: ruff (lint/format), mypy (strict), pytest (asyncio_mode=auto) all configured in pyproject.toml; zero errors on codebase

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
- [ ] 02-01-PLAN.md — Exception hierarchy + base AsanaClient with auth, get(), retry, error classification
- [ ] 02-02-PLAN.md — Auto-pagination async generator (paginated_get) + package exports

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
- [ ] 03-01: Token bucket rate limiter implementation
- [ ] 03-02: 429 response handler with Retry-After integration
- [ ] 03-03: Per-workspace rate limiter registry (create/get limiter per workspace GID)
- [ ] 03-04: Global concurrency semaphore for in-flight request coordination
- [ ] 03-05: Integration with API client (rate limiter middleware wrapping requests)

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
- [ ] 04-01: Atomic file writer (write to .tmp, os.replace to final path)
- [ ] 04-02: Directory structure manager (create output/{workspace}/{type}/ on demand)
- [ ] 04-03: JSON serialization with orjson

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
**Plans**: 6 plans

Plans:
- [ ] 05-01: Workspace discovery (GET /workspaces)
- [ ] 05-02: User extractor (GET /users?workspace={id}, paginated, write each to disk)
- [ ] 05-03: Project extractor (GET /projects?workspace={id}, paginated, write each to disk)
- [ ] 05-04: Task extractor (GET /tasks?project={id}, paginated, write each to disk)
- [ ] 05-05: Workspace extractor (orchestrates users → projects → tasks for one workspace)
- [ ] 05-06: Empty workspace and edge case handling

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
- [ ] 06-01: Concurrent workspace launcher (asyncio.gather with return_exceptions or task group)
- [ ] 06-02: Workspace isolation (try/except per workspace, error logging, continue others)
- [ ] 06-03: Workspace concurrency limiter (semaphore to cap parallel workspace extractions)

### Phase 7: Scheduler
**Goal**: Add periodic execution with skip-on-overlap and graceful shutdown, making the extractor a long-running service.
**Depends on**: Phase 6
**Requirements**: SCHED-01, SCHED-02, SCHED-03, ERR-04
**Success Criteria** (what must be TRUE):
  1. Extraction runs periodically at the configured interval (5min or 30s)
  2. If a cycle is still running when the next interval fires, the new cycle is skipped with a warning log
  3. SIGTERM/SIGINT triggers graceful shutdown — in-flight work completes before exit
  4. All log entries are structured JSON with workspace context
**Plans**: 5 plans

Plans:
- [ ] 07-01: Async periodic scheduler (asyncio-based interval loop)
- [ ] 07-02: Skip-on-overlap detection (flag/lock preventing concurrent cycles)
- [ ] 07-03: Signal handling (SIGTERM/SIGINT → graceful shutdown)
- [ ] 07-04: Main entry point (wire config → secrets → client → scheduler)
- [ ] 07-05: Structured logging integration across all components (structlog context binding)

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
**Plans**: 7 plans

Plans:
- [ ] 08-01: Test infrastructure (conftest, fixtures, aioresponses setup)
- [ ] 08-02: API client unit tests (auth, pagination, retry, error classification)
- [ ] 08-03: Rate limiter unit tests (token bucket, 429 handling, per-workspace isolation)
- [ ] 08-04: File writer unit tests (atomic writes, directory creation, crash safety)
- [ ] 08-05: Extraction unit tests (workspace discovery, entity extractors, empty workspace)
- [ ] 08-06: Integration tests (end-to-end extraction with mocked Asana API)
- [ ] 08-07: Type checking and linting (mypy strict, ruff, fix all issues)

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
**Plans**: 5 plans

Plans:
- [ ] 09-01: README — setup and usage instructions
- [ ] 09-02: README — system design and architecture section
- [ ] 09-03: README — scalability considerations section
- [ ] 09-04: README — rate limit handling strategy section
- [ ] 09-05: Final validation (end-to-end run, cleanup, code review)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
Note: Phase 4 (File Writer) depends only on Phase 1 and can run in parallel with Phases 2-3.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Project Foundation | 5/5 | Complete   | 2026-03-17 |
| 2. API Client | 0/2 | Not started | - |
| 3. Rate Limiter | 0/5 | Not started | - |
| 4. File Writer | 0/3 | Not started | - |
| 5. Entity Extraction | 0/6 | Not started | - |
| 6. Workspace Orchestrator | 0/3 | Not started | - |
| 7. Scheduler | 0/5 | Not started | - |
| 8. Testing | 0/7 | Not started | - |
| 9. Documentation & Polish | 0/5 | Not started | - |
