"""Configuration loading and validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator


class Settings(BaseModel):
    """Application configuration. Loaded from config.json at startup."""

    # Scheduling
    extraction_interval: Literal[30, 300]  # seconds: 30s or 5min

    # Output
    output_dir: str = "output"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Concurrency
    max_concurrent_workspaces: int = 10

    # Shutdown
    shutdown_timeout_seconds: int = 300

    @field_validator("max_concurrent_workspaces")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be ≥ 1")
        return v

    @field_validator("shutdown_timeout_seconds")
    @classmethod
    def shutdown_timeout_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be ≥ 1")
        return v


def load_config(path: str | Path = "config.json") -> Settings:
    """Load and validate configuration from a JSON file.

    Exits with a clear error message if the file is missing,
    not valid JSON, or fails schema validation.
    """
    config_path = Path(path)

    if not config_path.exists():
        print(
            f"ERROR: Configuration file not found: {config_path}\n"
            f"Create a config.json at the project root. "
            f"See config.json.example for the required fields.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        print(f"ERROR: config.json is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        print("ERROR: Configuration validation failed:", file=sys.stderr)
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            print(f"  - {field}: {error['msg']}", file=sys.stderr)
        sys.exit(1)
