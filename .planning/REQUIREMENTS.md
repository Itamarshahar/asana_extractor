# Requirements: Asana Extractor

**Defined:** 2026-03-17
**Core Value:** Reliably extract Asana data at scale without exceeding API rate limits or losing data to partial failures.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Authentication & Configuration

- [x] **AUTH-01**: Program authenticates with Asana API using a Personal Access Token (PAT) via Bearer token header
- [x] **AUTH-02**: PAT is loaded from an abstract secrets interface with .env file as the default provider
- [x] **AUTH-03**: Secrets interface is extensible (new providers can be added without modifying extraction code)
- [x] **CONF-01**: Program reads configuration from a YAML/TOML/JSON config file (extraction interval, output directory, log level, concurrency limits)
- [x] **CONF-02**: Configuration is validated at startup with clear error messages for missing/invalid values

### Data Extraction

- [x] **EXTR-01**: Program auto-discovers all workspaces accessible to the authenticated user
- [x] **EXTR-02**: Program extracts all users for each workspace
- [x] **EXTR-03**: Program extracts all projects for each workspace
- [x] **EXTR-04**: Program extracts all tasks for each project within each workspace
- [x] **EXTR-05**: All extraction endpoints handle API pagination correctly (offset-based, follow next_page until None)
- [x] **EXTR-06**: Workspaces are extracted concurrently using asyncio (not sequentially)
- [x] **EXTR-07**: One workspace's failure does not abort extraction of other workspaces (workspace isolation)
- [x] **EXTR-08**: Empty workspaces (0 users, 0 projects) are handled without error
- [x] **EXTR-09**: Entities are written to disk as they are extracted — not buffered in memory (avoids excessive memory usage at scale)

### Rate Limiting

- [ ] **RATE-01**: Program enforces per-workspace rate limiting (~150 requests per minute per token)
- [ ] **RATE-02**: Program handles 429 Too Many Requests responses by respecting the Retry-After header
- [ ] **RATE-03**: After a 429 response, program pauses requests for at least the Retry-After duration (no aggressive retry — rejected requests count against quota)
- [ ] **RATE-04**: Program uses exponential backoff with jitter for retries on transient errors (500, timeout, network)
- [ ] **RATE-05**: Concurrent in-flight requests are capped via semaphore to coordinate concurrent workers (prevents overwhelming the API)
- [ ] **RATE-06**: One workspace's rate limiting does not block or slow down other workspaces

### Output

- [ ] **OUT-01**: Each entity (user, project, task) is written as a separate JSON file
- [ ] **OUT-02**: Output directory structure follows: `output/{workspace_gid}/{type}/{entity_gid}.json`
- [ ] **OUT-03**: File writes are atomic (write to temp file, then os.replace to final path) — no partial/corrupt JSON files on crash
- [ ] **OUT-04**: Output directories are created automatically if they don't exist

### Scheduling

- [x] **SCHED-01**: Extraction runs periodically at a configurable interval (supports 5-minute and 30-second modes)
- [x] **SCHED-02**: Skip-on-overlap: if an extraction cycle is still running when the next interval fires, the new cycle is skipped and a warning is logged
- [x] **SCHED-03**: Program supports graceful shutdown (SIGTERM/SIGINT) — in-flight requests complete before exit

### Error Handling

- [x] **ERR-01**: Transient API errors (5xx, timeouts, connection errors) are retried with exponential backoff
- [x] **ERR-02**: Permanent API errors (4xx other than 429) are logged and skipped without crashing
- [x] **ERR-03**: All errors include sufficient context for debugging (workspace GID, entity type, endpoint, HTTP status)
- [x] **ERR-04**: Structured logging (JSON format) with workspace context in all log entries

### Testing

- [x] **TEST-01**: Unit tests validate API client behavior (pagination, rate limit handling, error handling)
- [ ] **TEST-02**: Unit tests validate file writer (atomic writes, directory creation, correct file paths)
- [x] **TEST-03**: Unit tests validate scheduler (skip-on-overlap behavior)
- [x] **TEST-04**: Integration tests validate end-to-end extraction flow with mocked API responses
- [x] **TEST-05**: Type checking passes (mypy strict mode)
- [x] **TEST-06**: Linting passes (ruff)

### Documentation

- [x] **DOC-01**: README explains how to run the program (setup, configuration, execution)
- [x] **DOC-02**: README explains the system design and architecture
- [x] **DOC-03**: README explains scalability considerations (how the design handles thousands of workspaces/entities)
- [x] **DOC-04**: README explains the rate limit handling strategy

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Extraction

- **EXTR-V2-01**: Incremental/delta extraction (only extract entities changed since last cycle)
- **EXTR-V2-02**: Hierarchical extraction fallback for large result sets (teams→projects, sections→tasks) to avoid 400 truncation
- **EXTR-V2-03**: Field selection via opt_fields parameter to reduce response size and cost-based rate limit impact

### Extended Infrastructure

- **INFRA-V2-01**: Cloud secret manager implementations (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager)
- **INFRA-V2-02**: Database output adapter (PostgreSQL, SQLite)
- **INFRA-V2-03**: Metrics/monitoring (extraction duration, entity counts, error rates per workspace)
- **INFRA-V2-04**: Multi-token support (different PATs per workspace)

### Real-time

- **RT-V2-01**: Webhook-based real-time event processing

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| OAuth authentication | Exercise specifies PAT only |
| Real-time streaming / webhooks | Exercise is poll-based extraction |
| Database storage | Output is JSON files only per exercise spec |
| UI or web dashboard | This is a CLI/background service |
| CLI arguments for config overrides | User chose config file only, no CLI args |
| Full denormalization (embed users in tasks) | Massively increases API calls and file sizes; keep entities normalized |
| In-memory entity cache for deduplication/lookups | Not needed — entities are written to disk immediately; memory management is handled via EXTR-09 |
| Using official Asana Python SDK | Synchronous only; cannot do concurrent extraction |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUTH-01 | Phase 2 | Complete |
| AUTH-02 | Phase 1 | Complete |
| AUTH-03 | Phase 1 | Complete |
| CONF-01 | Phase 1 | Complete |
| CONF-02 | Phase 1 | Complete |
| EXTR-01 | Phase 5 | Complete |
| EXTR-02 | Phase 5 | Complete |
| EXTR-03 | Phase 5 | Complete |
| EXTR-04 | Phase 5 | Complete |
| EXTR-05 | Phase 2 | Complete |
| EXTR-06 | Phase 6 | Complete |
| EXTR-07 | Phase 6 | Complete |
| EXTR-08 | Phase 5 | Complete |
| EXTR-09 | Phase 5 | Complete |
| RATE-01 | Phase 3 | Pending |
| RATE-02 | Phase 3 | Pending |
| RATE-03 | Phase 3 | Pending |
| RATE-04 | Phase 3 | Pending |
| RATE-05 | Phase 3 | Pending |
| RATE-06 | Phase 3 | Pending |
| OUT-01 | Phase 4 | Pending |
| OUT-02 | Phase 4 | Pending |
| OUT-03 | Phase 4 | Pending |
| OUT-04 | Phase 4 | Pending |
| SCHED-01 | Phase 7 | Complete |
| SCHED-02 | Phase 7 | Complete |
| SCHED-03 | Phase 7 | Complete |
| ERR-01 | Phase 2 | Complete |
| ERR-02 | Phase 2 | Complete |
| ERR-03 | Phase 2 | Complete |
| ERR-04 | Phase 7 | Complete |
| TEST-01 | Phase 8 | Complete |
| TEST-02 | Phase 8 | Pending |
| TEST-03 | Phase 8 | Complete |
| TEST-04 | Phase 8 | Complete |
| TEST-05 | Phase 8 | Complete |
| TEST-06 | Phase 8 | Complete |
| DOC-01 | Phase 9 | Complete |
| DOC-02 | Phase 9 | Complete |
| DOC-03 | Phase 9 | Complete |
| DOC-04 | Phase 9 | Complete |

**Coverage:**
- v1 requirements: 41 total
- Mapped to phases: 41
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-17*
*Last updated: 2026-03-17 after roadmap creation*
