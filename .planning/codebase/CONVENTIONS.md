# Conventions Analysis

**Mapped:** 2026-03-17
**Status:** Greenfield — no conventions established

## Current State

No source code exists, so no coding conventions are established yet.

## Inferred Conventions

### Language
- **Python** — based on `.gitignore` entries (pycache, pytest, mypy, ruff)
- Project name `asana_extractor` uses Python-standard **snake_case**

### Tooling Hints from .gitignore
- **pytest** — `.pytest_cache/` present, suggesting pytest for testing
- **mypy** — `.mypy_cache/` present, suggesting type checking
- **Ruff** — `.ruff_cache/` present, suggesting Ruff for linting/formatting
- **Virtual environments** — `.venv`, `venv/`, `env/` patterns

### Code Quality
- **Codacy** — `.github/instructions/codacy.instructions.md` suggests Codacy CI integration
- No pre-commit hooks configured
- No CI/CD pipeline files (no `.github/workflows/`)

## Recommendations Based on Tooling

Since the gitignore already includes entries for pytest, mypy, and Ruff, these tools should be adopted for consistency:
- **Ruff** for linting and formatting
- **mypy** for type checking
- **pytest** for testing

---
*Mapped: 2026-03-17*
