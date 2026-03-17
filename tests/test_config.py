"""Tests for config loading and validation."""

import json
import sys
from pathlib import Path

import pytest

from asana_extractor.config import Settings, load_config


def _write_config(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


VALID_CONFIG = {
    "extraction_interval": 30,
    "output_dir": "output",
    "log_level": "INFO",
    "max_concurrent_workspaces": 5,
}


def test_load_valid_config(tmp_path: Path) -> None:
    p = _write_config(tmp_path, VALID_CONFIG)
    settings = load_config(p)
    assert settings.extraction_interval == 30
    assert settings.output_dir == "output"
    assert settings.log_level == "INFO"
    assert settings.max_concurrent_workspaces == 5


def test_load_config_defaults(tmp_path: Path) -> None:
    """Only required field: extraction_interval."""
    p = _write_config(tmp_path, {"extraction_interval": 300})
    settings = load_config(p)
    assert settings.output_dir == "output"
    assert settings.log_level == "INFO"
    assert settings.max_concurrent_workspaces == 10


def test_missing_config_file_exits(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        load_config(tmp_path / "nonexistent.json")
    assert exc_info.value.code == 1


def test_missing_required_field_exits(tmp_path: Path) -> None:
    p = _write_config(tmp_path, {})  # missing extraction_interval
    with pytest.raises(SystemExit) as exc_info:
        load_config(p)
    assert exc_info.value.code == 1


def test_invalid_extraction_interval_exits(tmp_path: Path) -> None:
    p = _write_config(tmp_path, {"extraction_interval": 60})  # not 30 or 300
    with pytest.raises(SystemExit) as exc_info:
        load_config(p)
    assert exc_info.value.code == 1


def test_invalid_log_level_exits(tmp_path: Path) -> None:
    p = _write_config(tmp_path, {"extraction_interval": 30, "log_level": "VERBOSE"})
    with pytest.raises(SystemExit) as exc_info:
        load_config(p)
    assert exc_info.value.code == 1


def test_zero_concurrent_workspaces_exits(tmp_path: Path) -> None:
    p = _write_config(tmp_path, {"extraction_interval": 30, "max_concurrent_workspaces": 0})
    with pytest.raises(SystemExit) as exc_info:
        load_config(p)
    assert exc_info.value.code == 1
