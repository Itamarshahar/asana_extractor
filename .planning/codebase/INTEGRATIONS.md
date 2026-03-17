# Integrations Analysis

**Mapped:** 2026-03-17
**Status:** Greenfield — no integrations implemented

## Required Integration: Asana API

**Documentation:** https://developers.asana.com

### Authentication
- **Method:** Personal Access Token (PAT) — NOT OAuth
- **Header:** `Authorization: Bearer {PAT}`
- Token must be generated per-workspace in Asana settings

### API Endpoints Required

| Entity | Endpoint | Notes |
|--------|----------|-------|
| Users | `GET /users` | Workspace members |
| Projects | `GET /projects` | All projects in workspace |
| Tasks | `GET /tasks` | Per-project, all related tasks |

### Rate Limits
- **~150 requests per minute** per workspace/token
- Returns **429 Too Many Requests** when exceeded
- **Retry-After** header indicates backoff duration
- Must coordinate across concurrent workers

### Pagination
- Asana API uses **cursor-based pagination**
- Response includes `next_page.offset` when more results exist
- Must handle pagination for all list endpoints

### Output
- Each entity written as **separate JSON file**
- Files stored in a **dedicated output directory**
- No database or external storage required

## Other Integrations

None required. The exercise is self-contained:
- Input: Asana API
- Output: Local JSON files
- No message queues, databases, or external services

---
*Mapped: 2026-03-17*
