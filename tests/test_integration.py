"""End-to-end integration tests for the full extraction chain.

Tests exercise the complete path: TenantConfig → WorkspaceOrchestrator →
RateLimitedClient → extractors → EntityWriter → JSON files on disk.

All HTTP is mocked via aioresponses at the aiohttp level — no real network calls.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import orjson
import tenacity
from aioresponses import aioresponses as _aioresponses

from asana_extractor.client import BASE_URL
from asana_extractor.config import Settings
from asana_extractor.orchestrator import WorkspaceOrchestrator
from asana_extractor.tenant import TenantConfig


def _url(path: str) -> str:
    """Build a full Asana API URL from an endpoint path (strips leading slash)."""
    return BASE_URL + path.lstrip("/")


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

WS_GID = "111"
USER_DATA = {"gid": "u1", "name": "Alice", "email": "alice@example.com"}
PROJECT_DATA = {"gid": "p1", "name": "My Project"}
TASK_DATA = {"gid": "t1", "name": "Do thing", "completed": False}


def _register_happy_path_mocks(mock: _aioresponses, ws_gid: str = WS_GID) -> None:
    """Register all HTTP mocks for a single workspace happy-path extraction.

    Mocks:
      GET /users?workspace={ws_gid}&limit=100   → one user page
      GET /projects?workspace={ws_gid}&limit=100 → one project page
      GET /tasks?project=p1&limit=100            → one task page
    """
    mock.get(
        _url(f"/users?workspace={ws_gid}&limit=100"),
        payload={"data": [USER_DATA], "next_page": None},
    )
    mock.get(
        _url(f"/projects?workspace={ws_gid}&limit=100"),
        payload={"data": [PROJECT_DATA], "next_page": None},
    )
    mock.get(
        _url("/tasks?project=p1&limit=100"),
        payload={"data": [TASK_DATA], "next_page": None},
    )


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestIntegrationHappyPath:
    """Full extraction chain succeeds for valid workspace with entities."""

    async def test_single_workspace_full_extraction(self, tmp_path: Path) -> None:
        """Full extraction produces correct JSON files at expected paths.

        Asserts:
        - OrchestratorResult.succeeded == [WS_GID]
        - No failures
        - users/u1.json exists with correct content
        - projects/p1.json exists with correct content
        - tasks/t1.json exists with correct content
        """
        settings = Settings(
            extraction_interval=300,
            output_dir=str(tmp_path / "output"),
            max_concurrent_workspaces=2,
        )

        with _aioresponses() as mock:
            _register_happy_path_mocks(mock)
            orchestrator = WorkspaceOrchestrator(settings)
            tenants = [TenantConfig(workspace_gid=WS_GID, pat="test-pat")]
            result = await orchestrator.run(tenants)

        # Result assertions
        assert result.succeeded == [WS_GID]
        assert result.failed == []
        assert not result.has_failures

        output = tmp_path / "output"

        # User file
        user_file = output / WS_GID / "users" / "u1.json"
        assert user_file.exists(), f"User file not found: {user_file}"
        content = orjson.loads(user_file.read_bytes())
        assert content["gid"] == "u1"
        assert content["name"] == "Alice"
        assert content["email"] == "alice@example.com"

        # Project file
        project_file = output / WS_GID / "projects" / "p1.json"
        assert project_file.exists(), f"Project file not found: {project_file}"
        content = orjson.loads(project_file.read_bytes())
        assert content["gid"] == "p1"
        assert content["name"] == "My Project"

        # Task file
        task_file = output / WS_GID / "tasks" / "t1.json"
        assert task_file.exists(), f"Task file not found: {task_file}"
        content = orjson.loads(task_file.read_bytes())
        assert content["gid"] == "t1"
        assert content["name"] == "Do thing"
        assert content["completed"] is False

    async def test_empty_workspace_succeeds(self, tmp_path: Path) -> None:
        """Workspace with no entities completes successfully with no files created.

        Asserts:
        - OrchestratorResult.succeeded == ["ws-empty"]
        - No failures
        - No JSON files written (no entities)
        """
        ws_gid = "ws-empty"
        settings = Settings(
            extraction_interval=300,
            output_dir=str(tmp_path / "output"),
            max_concurrent_workspaces=2,
        )

        with _aioresponses() as mock:
            # Empty data on both workspace-level endpoints
            mock.get(
                _url(f"/users?workspace={ws_gid}&limit=100"),
                payload={"data": [], "next_page": None},
            )
            mock.get(
                _url(f"/projects?workspace={ws_gid}&limit=100"),
                payload={"data": [], "next_page": None},
            )
            # Note: /tasks will NOT be called — no project GIDs to iterate

            orchestrator = WorkspaceOrchestrator(settings)
            tenants = [TenantConfig(workspace_gid=ws_gid, pat="test-pat")]
            result = await orchestrator.run(tenants)

        assert result.succeeded == [ws_gid]
        assert result.failed == []
        assert not result.has_failures

        # No files should have been created
        output = tmp_path / "output"
        if output.exists():
            all_json_files = list(output.rglob("*.json"))
            assert all_json_files == [], f"Unexpected files created: {all_json_files}"


# ---------------------------------------------------------------------------
# Error isolation tests
# ---------------------------------------------------------------------------


class TestIntegrationErrorIsolation:
    """Failures in one workspace do not abort extraction for other workspaces."""

    async def test_one_workspace_fails_other_succeeds(self, tmp_path: Path) -> None:
        """ws2 /users endpoint 500s (exhausts retries); ws1 extracts correctly.

        Asserts:
        - OrchestratorResult.succeeded == [WS_GID]
        - OrchestratorResult.failed has one entry for ws2
        - ws1 output files exist with correct content
        - ws2 produces no output files
        """
        ws2_gid = "222"
        settings = Settings(
            extraction_interval=300,
            output_dir=str(tmp_path / "output"),
            max_concurrent_workspaces=2,
        )

        with _aioresponses() as mock:
            # ws1 gets valid data
            _register_happy_path_mocks(mock, ws_gid=WS_GID)

            # ws2 /users returns 500 three times (exhausts tenacity retries)
            for _ in range(3):
                mock.get(
                    _url(f"/users?workspace={ws2_gid}&limit=100"),
                    status=500,
                    body="Internal Server Error",
                )

            with patch.object(tenacity.nap, "sleep", AsyncMock()):
                orchestrator = WorkspaceOrchestrator(settings)
                tenants = [
                    TenantConfig(workspace_gid=WS_GID, pat="test-pat-1"),
                    TenantConfig(workspace_gid=ws2_gid, pat="test-pat-2"),
                ]
                result = await orchestrator.run(tenants)

        # ws1 succeeded, ws2 failed
        assert result.succeeded == [WS_GID]
        assert len(result.failed) == 1
        assert result.failed[0].workspace_gid == ws2_gid

        output = tmp_path / "output"

        # ws1 files exist and are correct
        user_file = output / WS_GID / "users" / "u1.json"
        assert user_file.exists(), f"ws1 user file missing: {user_file}"
        content = orjson.loads(user_file.read_bytes())
        assert content["gid"] == "u1"

        project_file = output / WS_GID / "projects" / "p1.json"
        assert project_file.exists()

        task_file = output / WS_GID / "tasks" / "t1.json"
        assert task_file.exists()

        # ws2 produced no output files
        ws2_dir = output / ws2_gid
        assert not ws2_dir.exists(), f"ws2 directory should not exist: {ws2_dir}"
