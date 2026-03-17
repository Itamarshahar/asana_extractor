# Concerns Analysis

**Mapped:** 2026-03-17
**Status:** Greenfield — pre-implementation concerns

## Greenfield Risk

This is a from-scratch implementation with no existing code. All concerns are forward-looking design risks rather than existing tech debt.

## Key Concerns

### 1. Rate Limit Management (High Risk)
- **Constraint:** ~150 requests/minute per workspace/token
- **Risk:** Naive implementation will hit rate limits immediately at scale
- **Considerations:**
  - Need central request throttling across concurrent workers
  - Must handle 429 responses gracefully with Retry-After backoff
  - One workspace's rate limit should not block other workspaces
  - Large workspaces may not complete within one extraction interval

### 2. Scalability Design (High Risk)
- **Constraint:** Must support thousands of workspaces, each with thousands of entities
- **Risk:** In-memory processing of all entities will exhaust memory at scale
- **Considerations:**
  - Stream entities rather than loading all into memory
  - Process workspaces independently (isolation)
  - Controlled concurrency to balance throughput vs resource usage
  - What happens when extraction takes longer than the interval?

### 3. Credential Security (Medium Risk)
- **Constraint:** PAT tokens must be stored securely
- **Risk:** Hardcoded tokens or tokens in committed files
- **Considerations:**
  - Environment variables or `.env` file (already in .gitignore)
  - Multiple workspace tokens need secure management
  - Never log or write tokens to output files

### 4. Output Consistency (Medium Risk)
- **Constraint:** Each entity as separate JSON file in output directory
- **Risk:** Partial writes during failures leave corrupt/incomplete data
- **Considerations:**
  - Atomic file writes (write to temp, then rename)
  - What happens if extraction fails mid-workspace?
  - File naming strategy for thousands of entities
  - Disk space management for large-scale extraction

### 5. Periodic Extraction Overlap (Medium Risk)
- **Constraint:** 5-minute and 30-second intervals
- **Risk:** Previous extraction not complete when next interval starts
- **Considerations:**
  - Skip vs queue overlapping runs
  - Track extraction state/progress
  - 30-second interval is very aggressive for large workspaces

---
*Mapped: 2026-03-17*
