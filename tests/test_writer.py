"""Tests for EntityWriter — atomic JSON file writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import orjson
import pytest

from asana_extractor.writer import EntityWriter


class TestEntityWriterPaths:
    def test_creates_correct_output_path(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))
        writer.write_entity("ws1", "users", "u1", {"gid": "u1"})
        expected = tmp_path / "ws1" / "users" / "u1.json"
        assert expected.exists()

    def test_respects_custom_output_dir(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "my_output"
        writer = EntityWriter(output_dir=str(custom_dir))
        writer.write_entity("ws1", "users", "u1", {"gid": "u1"})
        assert (custom_dir / "ws1" / "users" / "u1.json").exists()

    def test_path_uses_entity_type_and_gid(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))
        writer.write_entity("ws99", "projects", "p42", {"gid": "p42"})
        assert (tmp_path / "ws99" / "projects" / "p42.json").exists()


class TestEntityWriterContent:
    def test_file_content_is_valid_json(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))
        data = {"gid": "u1", "name": "Alice"}
        writer.write_entity("ws1", "users", "u1", data)
        content = (tmp_path / "ws1" / "users" / "u1.json").read_text()
        parsed = json.loads(content)
        assert parsed == data

    def test_file_is_pretty_printed_with_2_space_indent(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))
        writer.write_entity("ws1", "users", "u1", {"gid": "u1", "name": "Bob"})
        content = (tmp_path / "ws1" / "users" / "u1.json").read_bytes()
        # orjson OPT_INDENT_2 produces 2-space indented output
        expected = orjson.dumps({"gid": "u1", "name": "Bob"}, option=orjson.OPT_INDENT_2)
        assert content == expected

    def test_second_write_overwrites_first(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))
        writer.write_entity("ws1", "users", "u1", {"gid": "u1", "name": "First"})
        writer.write_entity("ws1", "users", "u1", {"gid": "u1", "name": "Second"})
        content = json.loads((tmp_path / "ws1" / "users" / "u1.json").read_text())
        assert content["name"] == "Second"


class TestEntityWriterDirectories:
    def test_creates_directories_automatically(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))
        # Directory does not pre-exist
        assert not (tmp_path / "ws1").exists()
        writer.write_entity("ws1", "tasks", "t1", {"gid": "t1"})
        assert (tmp_path / "ws1" / "tasks").is_dir()

    def test_does_not_fail_if_directory_already_exists(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))
        # Pre-create directory
        (tmp_path / "ws1" / "users").mkdir(parents=True)
        # Should not raise
        writer.write_entity("ws1", "users", "u1", {"gid": "u1"})
        assert (tmp_path / "ws1" / "users" / "u1.json").exists()


class TestEntityWriterAtomicity:
    def test_no_temp_file_remains_after_successful_write(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))
        writer.write_entity("ws1", "users", "u1", {"gid": "u1"})
        dir_path = tmp_path / "ws1" / "users"
        tmp_files = list(dir_path.glob("*.tmp"))
        assert tmp_files == []

    def test_temp_file_cleaned_up_on_write_failure(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))
        dir_path = tmp_path / "ws1" / "users"

        original_write_bytes = Path.write_bytes

        call_count = 0

        def failing_write_bytes(self: Path, data: bytes) -> int:
            nonlocal call_count
            call_count += 1
            # Write the bytes so the temp file exists, then raise
            original_write_bytes(self, data)
            raise OSError("Simulated disk error")

        with patch.object(Path, "write_bytes", failing_write_bytes):
            with pytest.raises(OSError, match="Simulated disk error"):
                writer.write_entity("ws1", "users", "u1", {"gid": "u1"})

        # Temp file should be cleaned up
        tmp_files = list(dir_path.glob("*.tmp"))
        assert tmp_files == []

    def test_final_file_does_not_exist_if_write_fails(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))

        with patch.object(Path, "write_bytes", side_effect=OSError("Simulated disk error")):
            with pytest.raises(OSError):
                writer.write_entity("ws1", "users", "u1", {"gid": "u1"})

        # Final file must not exist (no partial write)
        final = tmp_path / "ws1" / "users" / "u1.json"
        assert not final.exists()

    def test_non_serializable_value_raises_and_cleans_up(self, tmp_path: Path) -> None:
        writer = EntityWriter(output_dir=str(tmp_path))

        class NotSerializable:
            pass

        data: dict[str, Any] = {"gid": "u1", "bad": NotSerializable()}
        with pytest.raises(TypeError):
            writer.write_entity("ws1", "users", "u1", data)

        dir_path = tmp_path / "ws1" / "users"
        tmp_files = list(dir_path.glob("*.tmp"))
        assert tmp_files == []


class TestEntityWriterLogging:
    def test_logs_entity_written_at_info(self, tmp_path: Path) -> None:
        import structlog.testing

        with structlog.testing.capture_logs() as logs:
            writer = EntityWriter(output_dir=str(tmp_path))
            writer.write_entity("ws1", "users", "u1", {"gid": "u1"})

        assert any(
            log.get("event") == "entity_written"
            and log.get("workspace_gid") == "ws1"
            and log.get("entity_type") == "users"
            and log.get("entity_gid") == "u1"
            for log in logs
        )
