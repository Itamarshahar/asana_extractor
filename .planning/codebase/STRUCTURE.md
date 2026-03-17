# Structure Analysis

**Mapped:** 2026-03-17
**Status:** Greenfield — minimal directory structure

## Current Directory Layout

```
asana_extractor/
├── .git/                    # Git repository
├── .github/
│   └── instructions/
│       └── codacy.instructions.md  # Codacy AI instructions
├── .gitignore               # Python template (212 lines)
├── .opencode/               # OpenCode tooling config
├── .planning/               # GSD planning docs (being created)
│   └── codebase/            # This codebase mapping
├── instructions.md          # Exercise requirements document
└── README.md                # Empty — title only ("# asana_extractor")
```

## Key Observations

- **No source code directory** — `src/`, `app/`, or package directory needs to be created
- **No package file** — No `pyproject.toml`, `requirements.txt`, `setup.py`
- **No tests directory** — `tests/` needs to be created
- **No output directory** — Will be needed for JSON file output
- **No configuration files** — `.env`, config YAML/TOML needed for credentials

## Naming Convention

Project name uses **snake_case** (`asana_extractor`), consistent with Python conventions.

---
*Mapped: 2026-03-17*
