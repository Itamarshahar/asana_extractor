"""Atomic JSON file writer for Asana entities.

Writes entity dicts to output/{workspace_gid}/{type}/{entity_gid}.json using
temp-file-then-os.replace for crash safety. Uses orjson for fast serialization.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import orjson

from asana_extractor.logging import get_logger

__all__ = ["EntityWriter"]


class EntityWriter:
    """Writes entity dicts to JSON files with atomic temp-file-then-rename writes.

    Output path: {output_dir}/{workspace_gid}/{entity_type}/{entity_gid}.json

    Usage:
        writer = EntityWriter(output_dir="output")
        writer.write_entity("ws123", "users", "u456", {"gid": "u456", "name": "..."})
    """

    def __init__(self, output_dir: str = "output") -> None:
        self._output_dir = output_dir
        self._log = get_logger(__name__)

    def _entity_path(self, workspace_gid: str, entity_type: str, entity_gid: str) -> Path:
        """Construct the output path for an entity."""
        return Path(self._output_dir) / workspace_gid / entity_type / f"{entity_gid}.json"

    def write_entity(
        self,
        workspace_gid: str,
        entity_type: str,
        entity_gid: str,
        data: dict[str, Any],
    ) -> None:
        """Write entity data to a JSON file atomically.

        Writes to a temp file in the same directory, then renames to the final
        path (os.replace is atomic on POSIX). Ensures no partial/corrupt files
        on crash. Overwrites unconditionally on each call.

        Args:
            workspace_gid: Workspace identifier (part of output path).
            entity_type: Entity type string, e.g. "users", "projects", "tasks".
            entity_gid: Entity identifier (used as filename without extension).
            data: Entity dict to serialize as JSON.

        Raises:
            OSError: On disk full, permission denied, or other I/O failures.
            orjson.JSONEncodeError: If data contains non-serializable values.
        """
        final_path = self._entity_path(workspace_gid, entity_type, entity_gid)
        dir_path = final_path.parent

        # Lazy directory creation — no-op if already exists
        os.makedirs(dir_path, exist_ok=True)

        # Temp file in same directory (same filesystem) for atomic rename
        tmp_path = dir_path / f".{entity_gid}.json.tmp"

        try:
            json_bytes = orjson.dumps(data, option=orjson.OPT_INDENT_2)
            tmp_path.write_bytes(json_bytes)
            os.replace(tmp_path, final_path)
        finally:
            # Clean up orphaned temp file if write or replace failed
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass  # Best-effort cleanup; don't mask original exception

        self._log.info(
            "entity_written",
            workspace_gid=workspace_gid,
            entity_type=entity_type,
            entity_gid=entity_gid,
            file_path=str(final_path),
        )
