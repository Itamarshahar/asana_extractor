# Asana Extractor

Async, rate-limited data extractor for the Asana API with per-workspace isolation.

## Overview

Asana Extractor retrieves **users**, **projects**, and **tasks** from the Asana API and writes each entity to an individual JSON file. It runs as a long-lived service with periodic extraction cycles, or as a one-shot command via `--run-once`.

Key capabilities:

- **Async I/O** — built on Python 3.12+ asyncio and aiohttp for concurrent HTTP requests
- **3-tier rate limiting** — token bucket pacing, 429 pause-and-retry handling, and request semaphore backpressure
- **Workspace isolation** — each workspace gets independent rate limiting; one workspace's failure never affects others
- **Periodic scheduling** — configurable 30-second or 5-minute extraction intervals with skip-on-overlap protection
- **Atomic writes** — temp-file-then-`os.replace` ensures no partial JSON files on disk
- **Incremental extraction** — `modified_since` for tasks fetches only changed entities; users and projects always do a full refresh

## Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/your-org/asana-extractor.git
   cd asana-extractor
   ```

2. **Create a virtual environment and install:**

   ```bash
   uv venv && uv pip install -e ".[dev]"
   ```

3. **Configure:**

   ```bash
   cp config.json.example config.json
   ```

   Edit `config.json` — set `extraction_interval` (30 or 300) and add your workspace(s) to the `tenants` array with their GIDs and PATs.

   Create a `.env` file with your Personal Access Token:

   ```
   ASANA_PAT=1/your-personal-access-token
   ```

4. **Run:**

   ```bash
   # Single extraction cycle
   asana-extractor --run-once

   # Periodic extraction (runs until SIGTERM/SIGINT)
   asana-extractor
   ```

   Alternative entry point: `python -m asana_extractor`

## Configuration

All settings are loaded from `config.json` at startup. See `config.json.example` for a complete template.

| Field | Type | Default | Description |
|---|---|---|---|
| `extraction_interval` | `30 \| 300` | *(required)* | Extraction cycle interval in seconds |
| `output_dir` | `string` | `"output"` | Base directory for JSON output files |
| `log_level` | `"DEBUG" \| "INFO" \| "WARNING" \| "ERROR"` | `"INFO"` | Structured log verbosity |
| `max_concurrent_workspaces` | `integer (>= 1)` | `10` | Maximum workspaces processed concurrently |
| `shutdown_timeout_seconds` | `integer (>= 1)` | `300` | Grace period for in-flight requests on shutdown |
| `tenants` | `array` | *(required)* | Workspace configs — each entry has `workspace_gid` and `pat` |

## Architecture

```mermaid
graph LR
    Config["config.json"] --> Main["__main__"]
    Main --> Secrets["SecretsProvider"]
    Main --> Scheduler["ExtractionScheduler"]
    Scheduler --> Orchestrator["WorkspaceOrchestrator"]
    Orchestrator --> |"per workspace"| RLC["RateLimitedClient"]
    RLC --> Bucket["TokenBucket"]
    RLC --> State429["RateLimiter429State"]
    RLC --> Semaphore["GlobalRequestSemaphore"]
    RLC --> Client["AsanaClient"]
    Client --> |"aiohttp"| API["Asana API"]
    Orchestrator --> Extractors["Extractors"]
    Extractors --> Writer["EntityWriter"]
    Writer --> |"atomic write"| JSON["JSON files"]
```

**Components:**

- **AsanaClient** (`client.py`) — Async HTTP client wrapping aiohttp with PAT-based authentication, connection pooling (100 connections), and automatic retry on transient errors using tenacity (3 attempts, exponential backoff + jitter). Classifies errors into `AsanaTransientError` (5xx, connection failures) and `AsanaPermanentError` (4xx). Provides `paginated_get()` that follows `next_page.offset` until exhausted.

- **RateLimitedClient** (`rate_limited_client.py`) — Drop-in wrapper around AsanaClient that composes three rate limiting primitives: per-workspace token bucket (~120 req/min), 429 pause coordination with Retry-After parsing, and a shared global request semaphore (50 concurrent). Every `get()` and every page of `paginated_get()` flows through: `wait_if_paused` → `semaphore.acquire` → `bucket.acquire` → HTTP call → handle 429 if needed. Rate limiting is applied per-page during pagination, preventing unbounded bursts from large entity sets.

- **TokenBucket + WorkspaceRateLimiterRegistry** (`rate_limiter.py`) — Async token bucket with continuous refill at 2 tokens/sec (burst cap 10). The registry auto-creates one bucket per workspace on first request, ensuring per-workspace isolation. Also provides `RateLimiter429State` for 429 pause coordination and `GlobalRequestSemaphore` for backpressure.

- **Extractors** (`extractors.py`) — Stateless per-entity-type classes (`UserExtractor`, `ProjectExtractor`, `TaskExtractor`) inheriting `BaseExtractor` ABC. Dependencies (client, writer) are injected at `extract()` call time. Each extractor defines its API endpoint and query params; the base class handles pagination, writing, and metrics. `TaskExtractor.extract_all()` runs concurrent extraction across all projects.

- **EntityWriter** (`writer.py`) — Atomic JSON writer using orjson serialization. Writes to a temp file then `os.replace()` for crash safety. Output path: `{output_dir}/{workspace_gid}/{entity_type}/{entity_gid}.json`.

- **WorkspaceOrchestrator** (`orchestrator.py`) — Runs extraction across all tenant workspaces concurrently via `asyncio.gather`. Each workspace gets its own `RateLimitedClient` instance (with independent token bucket and 429 state, plus a shared global request semaphore). A semaphore caps concurrent workspace tasks at `max_concurrent_workspaces`. Each workspace runs inside `try/except` so one failure never aborts others. The `run()` method never raises.

- **ExtractionScheduler** (`scheduler.py`) — Drives periodic extraction at fixed intervals. Implements skip-on-overlap: if a cycle exceeds the interval, the next cycle is skipped with a warning log. Handles SIGTERM/SIGINT for graceful shutdown — waits up to `shutdown_timeout_seconds` for in-flight work to complete before cancelling.

## Concurrency Model

```mermaid
graph TD
    Sched["ExtractionScheduler"] --> Orch["WorkspaceOrchestrator"]
    Orch --> |"asyncio.gather<br/>semaphore(max_concurrent_workspaces)"| WA["Workspace A"]
    Orch --> |"asyncio.gather"| WB["Workspace B"]
    Orch --> |"asyncio.gather"| WN["Workspace N"]

    WA --> RLC_A["RateLimitedClient A<br/>(own TokenBucket, own 429 state)"]
    WB --> RLC_B["RateLimitedClient B<br/>(own TokenBucket, own 429 state)"]

    RLC_A --> |"semaphore.acquire<br/>bucket.acquire"| API["Asana API<br/>(shared semaphore: 50 max total)"]
    RLC_B --> |"semaphore.acquire<br/>bucket.acquire"| API

    subgraph "Within each workspace"
        direction TB
        Phase1["Phase 1: users ∥ projects<br/>(asyncio.gather)"]
        Phase2["Phase 2: tasks across all projects<br/>(concurrent, rate-limiter-throttled)"]
        Phase1 --> Phase2
    end
```

**Isolation guarantees:**

- Each workspace gets its own `RateLimitedClient` with independent token bucket and 429 state — Workspace A hitting its rate limit does not slow down Workspace B.
- Workspace extraction runs inside `try/except` — one workspace failing with an API error does not cancel or abort other workspaces.
- A shared `GlobalRequestSemaphore(50)` is created by the orchestrator and injected into all `RateLimitedClient` instances, capping total in-flight HTTP requests across all workspaces at 50.
- Within each workspace, users and projects are extracted concurrently (Phase 1), then tasks are extracted concurrently across all discovered projects (Phase 2).

## Rate Limit Handling

Asana enforces approximately **150 requests per minute per workspace/token**. The extractor uses a 3-tier strategy:

### 1. Proactive Pacing (Token Bucket)

Each workspace gets a `TokenBucket` refilling at 2 tokens/sec (~120 req/min, conservative margin below the 150 limit). `acquire()` blocks callers via `asyncio.sleep` until a token is available — transparent to the caller. The `WorkspaceRateLimiterRegistry` auto-creates and caches a bucket per workspace on first request.

### 2. Reactive Handling (429 Response)

When the API returns `429 Too Many Requests`:

1. The `AsanaClient` parses the `Retry-After` response header and attaches it to the exception. The `RateLimiter429State` **pauses all requests** for that workspace for the duration specified by `Retry-After` (falls back to 60 seconds if the header is absent or malformed).
2. After the pause, **resets the token bucket to 0** to prevent a burst of queued requests firing simultaneously.
3. The failed request is retried once after the pause.
4. After **3 consecutive 429s** without a successful request in between, the workspace is **failed for this cycle** (`AsanaTransientError` raised) — preventing an infinite retry loop.

### 3. Backpressure (Request Semaphore)

A shared `GlobalRequestSemaphore(50)` created by the orchestrator and injected into all `RateLimitedClient` instances caps the total number of concurrent in-flight HTTP requests across all workspaces. This prevents the system from overwhelming the API when many workspaces are being extracted simultaneously.

**How the tiers compose:** Every request passes through `wait_if_paused()` → `semaphore.acquire()` → `bucket.acquire()` → HTTP call → 429 handling if needed.

## Scalability

| Challenge | Mechanism |
|---|---|
| **Thousands of workspaces** | Concurrent extraction via `asyncio.gather`, capped by `max_concurrent_workspaces` semaphore (default 10). Each workspace gets an isolated rate limiter — no cross-workspace blocking. |
| **Thousands of entities per workspace** | Streaming writes — entities are written to disk as they arrive from pagination, not buffered in memory. `paginated_get()` follows `next_page.offset` automatically. |
| **API rate limits at scale** | Per-workspace token buckets (~120 req/min each) prevent any single workspace from starving others. A shared global request semaphore (50 in-flight across all workspaces) provides backpressure. |
| **Partial failures** | Workspace isolation: each workspace runs inside `try/except` with `asyncio.gather`. One workspace's API error is captured in `OrchestratorResult.failed` without aborting others. Transient errors are retried with exponential backoff + jitter. |
| **Long-running extractions** | Skip-on-overlap scheduling: if a cycle exceeds the interval, the next cycle is skipped with a warning log — no queue buildup or unbounded memory growth. |
| **Repeated full extraction** | Incremental extraction via `modified_since` for tasks reduces API calls to O(changed) per cycle. Users and projects always do a full refresh (Asana API limitation). State tracked per workspace in `.extraction_state.json`. |

**Future scaling considerations:** At 10,000+ workspaces, the single-process asyncio model would benefit from distributed workers (process pool or separate nodes), a persistent job queue for extraction tasks, and database output instead of filesystem writes.

## Output Examples

Each extraction cycle writes one JSON file per entity, organized by workspace and entity type:

```
output/
├── 1234567890/
│   ├── .extraction_state.json
│   ├── users/
│   │   ├── 1100000000000001.json
│   │   └── 1100000000000002.json
│   ├── projects/
│   │   └── 1200000000000001.json
│   └── tasks/
│       ├── 1300000000000001.json
│       └── 1300000000000002.json
└── 9876543210/
    ├── .extraction_state.json
    ├── users/
    │   └── 1100000000000003.json
    ├── projects/
    │   └── 1200000000000002.json
    └── tasks/
        └── 1300000000000003.json
```

**User** (`output/1234567890/users/1100000000000001.json`):

```json
{
  "gid": "1100000000000001",
  "last_fetch_time": "2026-03-20T14:30:00+00:00",
  "name": "Alice Smith"
}
```

**Project** (`output/1234567890/projects/1200000000000001.json`):

```json
{
  "gid": "1200000000000001",
  "last_fetch_time": "2026-03-20T14:30:00+00:00",
  "name": "Website Redesign",
  "workspace_gid": "1234567890"
}
```

**Task** (`output/1234567890/tasks/1300000000000001.json`):

```json
{
  "gid": "1300000000000001",
  "last_fetch_time": "2026-03-20T14:30:05+00:00",
  "name": "Update homepage hero section",
  "project_gid": "1200000000000001",
  "project_name": "Website Redesign"
}
```

**Extraction state** (`output/1234567890/.extraction_state.json`):

```json
{
  "workspace_gid": "1234567890",
  "last_cycle_start": "2026-03-20T14:30:00+00:00",
  "entity_timestamps": {
    "users": "2026-03-20T14:30:00+00:00",
    "projects": "2026-03-20T14:30:00+00:00",
    "tasks": "2026-03-20T14:30:00+00:00"
  },
  "cycle_count": 42
}
```

All JSON files are pretty-printed with 2-space indentation (orjson `OPT_INDENT_2`). Writes are atomic — a temp file is written first, then `os.replace()` swaps it into place, so no partial files appear on disk.

## Testing

```bash
# Run tests (asyncio_mode=auto, no manual event loop setup needed)
pytest

# Type checking (strict mode)
mypy --strict src/

# Linting
ruff check src/ tests/
```

Testing patterns used:

- **aioresponses** for mocking HTTP responses in async client tests
- **Fake client pattern** for extraction tests — plain async generators replace `paginated_get()` without `AsyncMock` limitations
- Tests cover: API interaction (auth, pagination, error classification), output correctness (atomic writes, file paths), rate limiting (token bucket, 429 handling), and scheduler lifecycle

## Project Structure

```
src/asana_extractor/
├── __init__.py            # Package exports
├── __main__.py            # CLI entry point (config → logging → secrets → orchestrator → scheduler)
├── client.py              # Async HTTP client (auth, pagination, retry with tenacity)
├── config.py              # Configuration model (pydantic BaseModel) and loader
├── exceptions.py          # Exception hierarchy (AsanaTransientError / AsanaPermanentError)
├── extractors.py          # Entity extractors (users, projects, tasks) and workspace orchestration
├── logging.py             # Structured logging setup (structlog, JSON output)
├── models.py              # Extraction result types (ExtractionResult dataclass)
├── orchestrator.py        # Multi-workspace concurrent processor with isolation
├── rate_limited_client.py # Rate-limited wrapper composing all throttling primitives
├── rate_limiter.py        # Token bucket, 429 state, workspace registry, global semaphore
├── scheduler.py           # Periodic execution (skip-on-overlap, graceful shutdown)
├── secrets.py             # Secrets interface (ABC + .env provider via python-dotenv)
├── state.py               # Incremental extraction state (load/save/delete per workspace)
├── tenant.py              # Tenant/workspace configuration types and provider
└── writer.py              # Atomic JSON file writer (tmp + os.replace, orjson)
```
