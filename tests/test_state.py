"""Tests for extraction state management — load, save, delete, round-trip."""

from __future__ import annotations

from pathlib import Path

import orjson
import pytest

from asana_extractor.state import (
    ExtractionState,
    delete_state,
    load_state,
    save_state,
    state_file_path,
)


def test_state_file_path() -> None:
    result = state_file_path("output", "ws123")
    assert result == Path("output/ws123/.extraction_state.json")


def test_load_state_returns_none_when_no_file(tmp_path: Path) -> None:
    result = load_state(str(tmp_path), "ws_missing")
    assert result is None


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    state = ExtractionState(
        workspace_gid="ws123",
        last_cycle_start="2026-03-20T10:00:00+00:00",
        entity_timestamps={
            "tasks": "2026-03-20T10:00:00+00:00",
            "projects": "2026-03-20T10:00:00+00:00",
            "users": "2026-03-20T10:00:00+00:00",
        },
        cycle_count=5,
    )
    save_state(str(tmp_path), state)
    loaded = load_state(str(tmp_path), "ws123")
    assert loaded is not None
    assert loaded.workspace_gid == "ws123"
    assert loaded.last_cycle_start == "2026-03-20T10:00:00+00:00"
    assert loaded.entity_timestamps["tasks"] == "2026-03-20T10:00:00+00:00"
    assert loaded.cycle_count == 5


def test_save_state_creates_directories(tmp_path: Path) -> None:
    output_dir = str(tmp_path / "deep" / "nested")
    state = ExtractionState(workspace_gid="ws_new")
    save_state(output_dir, state)
    assert state_file_path(output_dir, "ws_new").exists()


def test_save_state_atomic_no_tmp_left(tmp_path: Path) -> None:
    state = ExtractionState(workspace_gid="ws_atomic")
    save_state(str(tmp_path), state)
    ws_dir = tmp_path / "ws_atomic"
    tmp_files = list(ws_dir.glob("*.tmp"))
    assert tmp_files == [], f"Temp files left behind: {tmp_files}"
    assert (ws_dir / ".extraction_state.json").exists()


def test_delete_state_removes_file(tmp_path: Path) -> None:
    state = ExtractionState(workspace_gid="ws_del")
    save_state(str(tmp_path), state)
    assert state_file_path(str(tmp_path), "ws_del").exists()
    delete_state(str(tmp_path), "ws_del")
    assert not state_file_path(str(tmp_path), "ws_del").exists()


def test_delete_state_no_error_when_missing(tmp_path: Path) -> None:
    # Should not raise
    delete_state(str(tmp_path), "ws_nonexistent")


def test_load_state_returns_none_on_corrupt_json(tmp_path: Path) -> None:
    ws_dir = tmp_path / "ws_corrupt"
    ws_dir.mkdir(parents=True)
    (ws_dir / ".extraction_state.json").write_text("not valid json{{{")
    result = load_state(str(tmp_path), "ws_corrupt")
    assert result is None


def test_extraction_state_defaults() -> None:
    state = ExtractionState(workspace_gid="ws_defaults")
    assert state.cycle_count == 0
    assert state.entity_timestamps == {}
    assert state.last_cycle_start is None
