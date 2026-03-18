"""Tests for entity extractors — UserExtractor, ProjectExtractor, TaskExtractor,
discover_workspaces, and extract_workspace orchestrator.

Mocking strategy: Mock at the client level — create a fake RateLimitedClient
that yields pre-set entity dicts from paginated_get(). Use a fake EntityWriter
(MagicMock with spec) to capture what gets written.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import structlog.testing

from asana_extractor.extractors import (
    ProjectExtractionResult,
    ProjectExtractor,
    TaskExtractor,
    UserExtractor,
    WorkspaceExtractionResult,
    discover_workspaces,
    extract_workspace,
)
from asana_extractor.rate_limited_client import RateLimitedClient
from asana_extractor.writer import EntityWriter

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def make_fake_client(
    paginated_responses: list[dict[str, object]] | None = None,
    get_response: dict[str, object] | None = None,
) -> MagicMock:
    """Create a mock RateLimitedClient that returns pre-set responses."""
    client = MagicMock(spec=RateLimitedClient)

    if paginated_responses is not None:
        entities = list(paginated_responses)  # capture now

        async def fake_paginated_get(*args: object, **kwargs: object):
            for entity in entities:
                yield entity

        client.paginated_get = fake_paginated_get

    if get_response is not None:
        client.get = AsyncMock(return_value=get_response)

    return client


def make_fake_writer() -> MagicMock:
    """Create a mock EntityWriter that captures write_entity calls."""
    writer = MagicMock(spec=EntityWriter)
    return writer


# ---------------------------------------------------------------------------
# TestUserExtractor
# ---------------------------------------------------------------------------


class TestUserExtractor:
    async def test_extracts_users_and_writes(self) -> None:
        """Users yielded by paginated_get are written via write_entity with model fields."""
        entities: list[dict[str, object]] = [
            {"gid": "u1", "name": "Alice", "email": "alice@example.com"},
            {"gid": "u2", "name": "Bob"},
        ]
        client = make_fake_client(paginated_responses=entities)
        writer = make_fake_writer()

        extractor = UserExtractor()
        result = await extractor.extract(client, writer, workspace_gid="ws1")

        assert result.count == 2
        assert result.entity_type == "users"
        assert writer.write_entity.call_count == 2

        # Collect written dicts keyed by gid
        calls = writer.write_entity.call_args_list
        written = {c.args[2]: c.args[3] for c in calls}

        assert "u1" in written
        u1 = written["u1"]
        assert u1["gid"] == "u1"
        assert u1["name"] == "Alice"
        assert u1["email"] == "alice@example.com"
        assert "last_fetch_time" in u1

        assert "u2" in written
        u2 = written["u2"]
        assert u2["gid"] == "u2"
        assert u2["name"] == "Bob"
        assert "last_fetch_time" in u2

    async def test_missing_gid_skipped_with_warning(self) -> None:
        """Entities without a 'gid' field are skipped; warning recorded."""
        entities: list[dict[str, object]] = [{"name": "no-gid-user"}]
        client = make_fake_client(paginated_responses=entities)
        writer = make_fake_writer()

        extractor = UserExtractor()
        with structlog.testing.capture_logs() as logs:
            result = await extractor.extract(client, writer, workspace_gid="ws1")

        assert result.count == 0
        writer.write_entity.assert_not_called()
        assert len(result.warnings) == 1
        assert any(log.get("event") == "entity_missing_gid" for log in logs)


# ---------------------------------------------------------------------------
# TestProjectExtractor
# ---------------------------------------------------------------------------


class TestProjectExtractor:
    async def test_extracts_projects_and_collects_gids(self) -> None:
        """Projects are written with model fields and GIDs collected in ProjectExtractionResult."""
        entities: list[dict[str, object]] = [
            {"gid": "p1", "name": "Alpha", "workspace": {"gid": "ws1"}},
            {"gid": "p2", "name": "Beta"},
        ]
        client = make_fake_client(paginated_responses=entities)
        writer = make_fake_writer()

        extractor = ProjectExtractor()
        result = await extractor.extract(client, writer, workspace_gid="ws1")

        assert isinstance(result, ProjectExtractionResult)
        assert result.count == 2
        assert result.project_gids == ["p1", "p2"]
        assert result.entity_type == "projects"
        assert writer.write_entity.call_count == 2

        # Collect written dicts keyed by gid
        calls = writer.write_entity.call_args_list
        written = {c.args[2]: c.args[3] for c in calls}

        assert "p1" in written
        p1 = written["p1"]
        assert p1["gid"] == "p1"
        assert p1["name"] == "Alpha"
        assert p1["workspace_gid"] == "ws1"
        assert "last_fetch_time" in p1

        assert "p2" in written
        p2 = written["p2"]
        assert p2["gid"] == "p2"
        assert p2["name"] == "Beta"
        assert "last_fetch_time" in p2

    async def test_empty_workspace_returns_empty(self) -> None:
        """Empty paginated response produces count=0 and project_gids=[]."""
        client = make_fake_client(paginated_responses=[])
        writer = make_fake_writer()

        extractor = ProjectExtractor()
        result = await extractor.extract(client, writer, workspace_gid="ws1")

        assert isinstance(result, ProjectExtractionResult)
        assert result.count == 0
        assert result.project_gids == []
        writer.write_entity.assert_not_called()


# ---------------------------------------------------------------------------
# TestTaskExtractor
# ---------------------------------------------------------------------------


class TestTaskExtractor:
    async def test_extracts_tasks_for_project(self) -> None:
        """Tasks are written with entity_type='tasks' for the given project."""
        entities: list[dict[str, object]] = [
            {
                "gid": "t1",
                "name": "Task1",
                "projects": [{"gid": "p1", "name": "Proj1"}],
            },
            {
                "gid": "t2",
                "name": "Task2",
                "projects": [{"gid": "p1", "name": "Proj1"}],
            },
        ]
        client = make_fake_client(paginated_responses=entities)
        writer = make_fake_writer()

        extractor = TaskExtractor()
        result = await extractor.extract(client, writer, workspace_gid="ws1", project_gid="p1")

        assert result.count == 2
        assert result.entity_type == "tasks"

        # Verify both tasks were written — check all calls and match by gid
        # since last_fetch_time is dynamic.
        calls = writer.write_entity.call_args_list
        written = {c.args[2]: c.args[3] for c in calls}  # keyed by gid

        assert "t1" in written
        t1 = written["t1"]
        assert t1["gid"] == "t1"
        assert t1["task_name"] == "Task1"
        assert t1["project_gid"] == "p1"
        assert t1["project_name"] == "Proj1"
        assert t1["name"] == "Task1"
        assert "last_fetch_time" in t1

        assert "t2" in written
        t2 = written["t2"]
        assert t2["gid"] == "t2"
        assert t2["task_name"] == "Task2"
        assert t2["project_gid"] == "p1"
        assert t2["project_name"] == "Proj1"
        assert t2["name"] == "Task2"
        assert "last_fetch_time" in t2

    async def test_extract_all_aggregates_across_projects(self) -> None:
        """extract_all fires concurrent extractions and sums counts."""
        # 2 projects, each with 1 task — total should be 2
        entities_by_call: list[list[dict[str, object]]] = [
            [{"gid": "t1", "name": "TaskA", "projects": [{"gid": "p1", "name": "ProjA"}]}],
            [{"gid": "t2", "name": "TaskB", "projects": [{"gid": "p2", "name": "ProjB"}]}],
        ]
        call_index = 0

        client = MagicMock(spec=RateLimitedClient)

        async def fake_paginated_get(*args: object, **kwargs: object):
            nonlocal call_index
            entities = entities_by_call[call_index % len(entities_by_call)]
            call_index += 1
            for entity in entities:
                yield entity

        client.paginated_get = fake_paginated_get
        writer = make_fake_writer()

        extractor = TaskExtractor()
        result = await extractor.extract_all(
            client, writer, workspace_gid="ws1", project_gids=["p1", "p2"]
        )

        assert result.count == 2
        assert result.entity_type == "tasks"

    async def test_extract_all_no_projects_returns_zero(self) -> None:
        """extract_all with empty project_gids returns count=0 immediately."""
        client = make_fake_client(paginated_responses=[])
        writer = make_fake_writer()

        extractor = TaskExtractor()
        result = await extractor.extract_all(client, writer, workspace_gid="ws1", project_gids=[])

        assert result.count == 0
        assert result.entity_type == "tasks"
        writer.write_entity.assert_not_called()

    def test_build_params_includes_opt_fields_with_projects(self) -> None:
        """_build_params returns opt_fields requesting name and project membership."""
        extractor = TaskExtractor()
        params = extractor._build_params(project_gid="p1")

        assert params["project"] == "p1"
        assert "opt_fields" in params
        assert "name" in params["opt_fields"]
        assert "projects.gid" in params["opt_fields"]
        assert "projects.name" in params["opt_fields"]

    async def test_task_model_fields_written(self) -> None:
        """Written dict uses Task model field names (task_name, project_gid, project_name)."""
        entities: list[dict[str, object]] = [
            {
                "gid": "t1",
                "name": "Do thing",
                "projects": [
                    {"gid": "p1", "name": "My Project"},
                    {"gid": "p2", "name": "Other Project"},
                ],
            },
        ]
        client = make_fake_client(paginated_responses=entities)
        writer = make_fake_writer()

        extractor = TaskExtractor()
        await extractor.extract(client, writer, workspace_gid="ws1", project_gid="p1")

        written_data = writer.write_entity.call_args_list[0][0][3]
        assert written_data["gid"] == "t1"
        assert written_data["task_name"] == "Do thing"
        assert written_data["project_gid"] == "p1"
        assert written_data["project_name"] == "My Project"
        assert written_data["name"] == "Do thing"
        assert "last_fetch_time" in written_data

    async def test_task_model_missing_projects_field(self) -> None:
        """Task model handles API response without projects list gracefully."""
        entities: list[dict[str, object]] = [
            {"gid": "t1", "name": "Orphan task"},
        ]
        client = make_fake_client(paginated_responses=entities)
        writer = make_fake_writer()

        extractor = TaskExtractor()
        await extractor.extract(client, writer, workspace_gid="ws1", project_gid="p1")

        written_data = writer.write_entity.call_args_list[0][0][3]
        assert written_data["project_name"] == ""
        assert written_data["project_gid"] == "p1"
        assert written_data["task_name"] == "Orphan task"


# ---------------------------------------------------------------------------
# TestDiscoverWorkspaces
# ---------------------------------------------------------------------------


class TestDiscoverWorkspaces:
    async def test_returns_workspace_list(self) -> None:
        """discover_workspaces extracts 'data' envelope from client.get response."""
        workspaces = [{"gid": "ws1", "name": "My Workspace"}]
        client = make_fake_client(get_response={"data": workspaces})

        result = await discover_workspaces(client)

        assert result == workspaces
        client.get.assert_awaited_once_with("/workspaces")

    async def test_returns_empty_list_when_no_workspaces(self) -> None:
        """Empty data envelope returns empty list."""
        client = make_fake_client(get_response={"data": []})

        result = await discover_workspaces(client)

        assert result == []


# ---------------------------------------------------------------------------
# TestExtractWorkspace
# ---------------------------------------------------------------------------


class TestExtractWorkspace:
    async def test_full_workspace_extraction(self) -> None:
        """extract_workspace orchestrates users, projects, and tasks in two phases."""
        responses_by_endpoint: dict[str, list[dict[str, object]]] = {
            "/users": [{"gid": "u1", "name": "User1"}],
            "/projects": [{"gid": "p1", "name": "Proj1"}],
            "/tasks": [
                {
                    "gid": "t1",
                    "name": "Task1",
                    "projects": [{"gid": "p1", "name": "Proj1"}],
                }
            ],
        }

        client = MagicMock(spec=RateLimitedClient)

        async def fake_paginated_get(endpoint: str, *, params=None, workspace_gid=None):
            for entity in responses_by_endpoint.get(endpoint, []):
                yield entity

        client.paginated_get = fake_paginated_get
        writer = make_fake_writer()

        result = await extract_workspace(client, writer, workspace_gid="ws1")

        assert isinstance(result, WorkspaceExtractionResult)
        assert result.workspace_gid == "ws1"
        assert result.user_result.count == 1
        assert result.project_result.count == 1
        assert result.task_result.count == 1
        assert result.total_entities == 3

    async def test_empty_workspace_no_tasks(self) -> None:
        """When there are no projects, tasks extraction is skipped (count=0)."""
        responses_by_endpoint: dict[str, list[dict[str, object]]] = {
            "/users": [],
            "/projects": [],
            "/tasks": [],
        }

        client = MagicMock(spec=RateLimitedClient)

        async def fake_paginated_get(endpoint: str, *, params=None, workspace_gid=None):
            for entity in responses_by_endpoint.get(endpoint, []):
                yield entity

        client.paginated_get = fake_paginated_get
        writer = make_fake_writer()

        result = await extract_workspace(client, writer, workspace_gid="ws1")

        assert result.task_result.count == 0
        assert result.total_entities == 0
        writer.write_entity.assert_not_called()
