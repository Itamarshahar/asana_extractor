# Asana Extractor

## What This Is

A Python program that extracts users, projects, and tasks from the Asana API and writes each entity as a separate JSON file. It runs periodically (configurable 5-minute or 30-second intervals) and is designed to operate at scale — thousands of workspaces, each containing thousands of entities — with controlled concurrency, per-workspace rate limiting, and resilient error handling.

## Core Value

Reliably extract Asana data at scale without exceeding API rate limits or losing data to partial failures.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Authenticate with Asana API using Personal Access Tokens
- [ ] Auto-discover workspaces from authenticated user, extract from all
- [ ] Extract users and projects per workspace
- [ ] Extract all tasks per project
- [ ] Handle API pagination for all entity types
- [ ] Write each entity as a separate JSON file (output/{workspace_id}/{type}/{entity_id}.json)
- [ ] Per-workspace rate limiting (~150 req/min), handle 429 + Retry-After
- [ ] Periodic extraction in two configurable modes: every 5 minutes, every 30 seconds
- [ ] Skip-on-overlap: if extraction is still running when next interval fires, skip and log warning
- [ ] Asyncio-based concurrency for parallel workspace processing
- [ ] Atomic file writes (write to temp, rename) to prevent corrupt output
- [ ] Abstract secrets interface with .env as default provider (extensible to AWS/Azure/GCP)
- [ ] Config file + CLI arguments for settings (interval, output dir, etc.)
- [ ] Workspace isolation — one workspace's failures/rate limits don't block others
- [ ] Safe retries with exponential backoff for transient API errors
- [ ] Tests validating API interaction, output correctness, and error handling
- [ ] README documenting system design, scalability, and rate limit strategy

### Out of Scope

- OAuth authentication — exercise specifies PAT only
- Real-time streaming / webhooks — exercise is poll-based extraction
- Database storage — output is JSON files only
- Cloud secret manager implementations — only the interface + .env provider for v1
- UI or web dashboard — this is a CLI/background service
- Incremental/delta extraction — full extraction each cycle for v1

## Context

This is a technical exercise / take-home assignment. The implementation will be tested with a small Asana account (3 users, 2 projects) but must be designed as if operating at large scale. The Asana API enforces ~150 requests per minute per workspace/token. The exercise evaluates: API integration skills, scalability thinking, error handling, testing discipline, and clear documentation.

Key Asana API details:
- REST API at https://app.asana.com/api/1.0/
- Auth via Bearer token (PAT)
- Pagination via offset-based cursors
- Rate limit: ~150 req/min per workspace, 429 response with Retry-After header
- Entities: workspaces, users, projects, tasks (tasks belong to projects)

## Constraints

- **Language**: Python — project setup and tooling indicate Python
- **Auth**: Personal Access Token only — exercise requirement
- **Concurrency**: asyncio — chosen for I/O-bound API work at scale
- **Rate limit**: ~150 req/min per workspace — Asana API enforced
- **Output format**: JSON files, one per entity — exercise requirement
- **Testing**: pytest — inferred from .gitignore tooling (pytest, mypy, ruff)
- **Linting**: ruff — inferred from .gitignore
- **Type checking**: mypy — inferred from .gitignore

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| asyncio for concurrency | I/O-bound workload, natural fit for Python async, scales to thousands of concurrent workspaces | — Pending |
| Skip-on-overlap scheduling | At scale, large workspaces will regularly exceed short intervals; queuing would accumulate unbounded work | — Pending |
| Abstract secrets interface | Allows .env for dev/exercise, extensible to cloud secret managers without refactoring | — Pending |
| Output: workspace/type/entity.json | Natural grouping by workspace for isolation, then by entity type for discoverability | — Pending |
| Per-workspace rate limiter | Asana rate limits are per workspace/token; central limiter would unfairly throttle small workspaces | — Pending |
| Config + CLI args (both) | Config file for defaults and persistent settings, CLI for runtime overrides | — Pending |

---
*Last updated: 2026-03-17 after deep questioning*
