"""Extraction state tracking for incremental extraction.

Manages per-workspace state files that record the last successful extraction
timestamp, enabling ``modified_since`` filtering on subsequent cycles. State
files are written atomically using the same temp-file + os.replace pattern
as :class:`~asana_extractor.writer.EntityWriter`.

State file location: ``output/{workspace_gid}/.extraction_state.json``
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

from asana_extractor.logging import get_logger

__all__ = [
    "ExtractionState",
    "delete_state",
    "load_state",
    "save_state",
    "state_file_path",
]

log = get_logger(__name__)

_STATE_FILENAME = ".extraction_state.json"


@dataclass
class ExtractionState:
    """Tracks extraction cycle state for a single workspace.

    Attributes:
        workspace_gid: Asana workspace identifier.
        last_cycle_start: ISO 8601 UTC timestamp of the last successful
            cycle start.  ``None`` on first run.  Used as the
            ``modified_since`` value for incremental task extraction.
        entity_timestamps: Per-entity-type timestamps recording when each
            entity type was last successfully extracted.  Currently all
            values equal ``last_cycle_start`` because the entire workspace
            is extracted atomically — the dict exists so the schema can
            support independent per-entity tracking in the future.
        cycle_count: Number of successful extraction cycles completed.
    """

    workspace_gid: str
    last_cycle_start: str | None = None
    entity_timestamps: dict[str, str] = field(default_factory=dict)
    cycle_count: int = 0


def state_file_path(output_dir: str, workspace_gid: str) -> Path:
    """Return the path to a workspace's extraction state file.

    Args:
        output_dir: Root output directory (e.g. ``"output"``).
        workspace_gid: Asana workspace identifier.

    Returns:
        ``Path(output_dir) / workspace_gid / ".extraction_state.json"``
    """
    return Path(output_dir) / workspace_gid / _STATE_FILENAME


def load_state(output_dir: str, workspace_gid: str) -> ExtractionState | None:
    """Load extraction state from disk.

    Returns ``None`` when no state file exists (first run) or when the
    file contains invalid JSON (treated as first run with a warning).

    Args:
        output_dir: Root output directory.
        workspace_gid: Asana workspace identifier.

    Returns:
        Populated :class:`ExtractionState` or ``None``.
    """
    path = state_file_path(output_dir, workspace_gid)
    if not path.exists():
        log.info("state_not_found", workspace_gid=workspace_gid, path=str(path))
        return None

    try:
        raw: dict[str, Any] = orjson.loads(path.read_bytes())
    except (orjson.JSONDecodeError, OSError) as exc:
        log.warning(
            "state_load_error",
            workspace_gid=workspace_gid,
            path=str(path),
            error=str(exc),
        )
        return None

    state = ExtractionState(
        workspace_gid=raw.get("workspace_gid", workspace_gid),
        last_cycle_start=raw.get("last_cycle_start"),
        entity_timestamps=raw.get("entity_timestamps", {}),
        cycle_count=raw.get("cycle_count", 0),
    )
    log.info(
        "state_loaded",
        workspace_gid=workspace_gid,
        cycle_count=state.cycle_count,
        last_cycle_start=state.last_cycle_start,
    )
    return state


def save_state(output_dir: str, state: ExtractionState) -> None:
    """Persist extraction state to disk atomically.

    Uses the same atomic-write strategy as
    :class:`~asana_extractor.writer.EntityWriter`: serialize to a
    temporary file in the same directory, then ``os.replace()`` to the
    final path (atomic on POSIX).

    Args:
        output_dir: Root output directory.
        state: Extraction state to persist.
    """
    path = state_file_path(output_dir, state.workspace_gid)
    dir_path = path.parent

    os.makedirs(dir_path, exist_ok=True)

    data: dict[str, Any] = {
        "workspace_gid": state.workspace_gid,
        "last_cycle_start": state.last_cycle_start,
        "entity_timestamps": state.entity_timestamps,
        "cycle_count": state.cycle_count,
    }

    tmp_path = dir_path / f"{_STATE_FILENAME}.tmp"
    try:
        json_bytes = orjson.dumps(data, option=orjson.OPT_INDENT_2)
        tmp_path.write_bytes(json_bytes)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass  # Best-effort cleanup

    log.info(
        "state_saved",
        workspace_gid=state.workspace_gid,
        cycle_count=state.cycle_count,
    )


def delete_state(output_dir: str, workspace_gid: str) -> None:
    """Delete a workspace's extraction state file.

    Used by the ``--full-extraction`` CLI flag to force a full
    re-extraction. Silently succeeds if the file does not exist.

    Args:
        output_dir: Root output directory.
        workspace_gid: Asana workspace identifier.
    """
    path = state_file_path(output_dir, workspace_gid)
    try:
        path.unlink()
        log.info("state_deleted", workspace_gid=workspace_gid, path=str(path))
    except FileNotFoundError:
        log.info("state_not_found", workspace_gid=workspace_gid, path=str(path))
