# Stack Analysis

**Mapped:** 2026-03-17
**Status:** Greenfield — no implementation code exists

## Current State

This is a **pre-implementation project**. No source code, dependencies, or runtime configuration exists yet.

## Language Indicators

The `.gitignore` file is a comprehensive **Python** gitignore template, indicating the project is intended to be built in Python. It includes entries for:

- `__pycache__/`, `*.py[codz]` — Python bytecode
- `.venv`, `venv/`, `env/` — Python virtual environments
- `.pytest_cache/` — pytest test runner
- `.mypy_cache/` — mypy type checker
- `.ruff_cache/` — Ruff linter
- References to `pipenv`, `poetry`, `pdm`, `uv`, `pixi` — Python package managers

## IDE

Project is opened in **PyCharm** (path: `PycharmProjects/asana_extractor`).

## Dependencies

None installed. No `requirements.txt`, `pyproject.toml`, `Pipfile`, `setup.py`, or `setup.cfg` exists.

## Configuration

- `.gitignore` — Python template (212 lines)
- `.github/instructions/codacy.instructions.md` — Codacy AI instructions (gitignored)
- No CI/CD pipeline configured
- No environment configuration

## Exercise Requirements (from `instructions.md`)

The project needs to:
- Call the **Asana REST API** (HTTP client needed)
- Handle **JSON** responses and write **JSON files**
- Run **periodically** (scheduler needed)
- Handle **pagination**, **rate limiting**, **errors**
- Scale to thousands of workspaces/entities

---
*Mapped: 2026-03-17*
