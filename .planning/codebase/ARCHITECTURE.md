# Architecture Analysis

**Mapped:** 2026-03-17
**Status:** Greenfield — no architecture exists

## Current State

No implementation code exists. The project contains only:
- `instructions.md` — Exercise requirements
- `README.md` — Empty (title only)
- `.gitignore` — Python template
- `.github/` — GitHub config (Codacy instructions)

## Required Architecture (from exercise requirements)

### Core Components Needed

1. **API Client** — HTTP client for Asana REST API with auth, pagination, error handling
2. **Rate Limiter** — Central throttling (~150 req/min per workspace), 429 handling, Retry-After support
3. **Extractor** — Orchestrates extraction of users, projects, and tasks per workspace
4. **File Writer** — Writes each entity as separate JSON file to output directory
5. **Scheduler** — Runs extraction periodically (5-minute and 30-second modes)
6. **Configuration** — PAT management, workspace selection, interval settings

### Data Flow

```
[Scheduler] → [Extractor] → [API Client] → [Asana API]
                   ↓              ↑
              [Rate Limiter] ─────┘
                   ↓
              [File Writer] → [JSON Files]
```

### Scalability Requirements

The architecture must support:
- **Thousands of workspaces** — workspace isolation, independent processing
- **Thousands of entities per workspace** — pagination, memory-efficient streaming
- **Controlled concurrency** — parallel workspace processing without exceeding rate limits
- **Safe retries and recovery** — resilient to transient API failures
- **Consistent output** — atomic file writes, no partial/corrupt output

### Entry Points

None exist yet. Expected:
- CLI entry point for running the extractor
- Configuration for workspace credentials and intervals

---
*Mapped: 2026-03-17*
