"""Tests for entity extractors — UserExtractor, ProjectExtractor, TaskExtractor,
discover_workspaces, and extract_workspace orchestrator.

Mocking strategy: Mock at the client level — create a fake RateLimitedClient
that yields pre-set entity dicts from paginated_get(). Use a fake EntityWriter
(MagicMock with spec) to capture what gets written.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest
import structlog.testing

from asana_extractor.extractors import (
    ExtractionResult,
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
    paginated_responses: list[dict] | None = None,
    get_response: dict | None = None,
) -> MagicMock:
    """Create a mock RateLimitedClient that returns pre-set responses."""
    client = MagicMock(spec=RateLimitedClient)

    if paginated_responses is not None:
        entities = list(paginated_responses)  # capture now

        async def fake_paginated_get(*args: object, **kwargs: object):  # type: ignore[return]
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
        """Users yielded by paginated_get are written via write_entity."""
        entities = [{"gid": "u1", "name": "Alice"}, {"gid": "u2", "name": "Bob"}]
        client = make_fake_client(paginated_responses=entities)
        writer = make_fake_writer()

        extractor = UserExtractor()
        result = await extractor.extract(client, writer, workspace_gid="ws1")

        assert result.count == 2
        assert result.entity_type == "users"
        assert writer.write_entity.call_count == 2
        writer.write_entity.assert_any_call("ws1", "users", "u1", {"gid": "u1", "name": "Alice"})
        writer.write_entity.assert_any_call("ws1", "users", "u2", {"gid": "u2", "name": "Bob"})

    async def test_missing_gid_skipped_with_warning(self) -> None:
        """Entities without a 'gid' field are skipped; warning recorded."""
        entities = [{"name": "no-gid-user"}]
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
        """Projects are written and GIDs collected in ProjectExtractionResult."""
        entities = [{"gid": "p1", "name": "Alpha"}, {"gid": "p2", "name": "Beta"}]
        client = make_fake_client(paginated_responses=entities)
        writer = make_fake_writer()

        extractor = ProjectExtractor()
        result = await extractor.extract(client, writer, workspace_gid="ws1")

        assert isinstance(result, ProjectExtractionResult)
        assert result.count == 2
        assert result.project_gids == ["p1", "p2"]
        assert result.entity_type == "projects"
        assert writer.write_entity.call_count == 2

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
        entities = [{"gid": "t1", "name": "Task1"}, {"gid": "t2", "name": "Task2"}]
        client = make_fake_client(paginated_responses=entities)
        writer = make_fake_writer()

        extractor = TaskExtractor()
        result = await extractor.extract(client, writer, workspace_gid="ws1", project_gid="p1")

        assert result.count == 2
        assert result.entity_type == "tasks"
        writer.write_entity.assert_any_call("ws1", "tasks", "t1", {"gid": "t1", "name": "Task1"})
        writer.write_entity.assert_any_call("ws1", "tasks", "t2", {"gid": "t2", "name": "Task2"})

    async def test_extract_all_aggregates_across_projects(self) -> None:
        """extract_all fires concurrent extractions and sums counts."""
        # 2 projects, each with 1 task — total should be 2
        entities_by_call: list[list[dict]] = [
            [{"gid": "t1", "name": "TaskA"}],
            [{"gid": "t2", "name": "TaskB"}],
        ]
        call_index = 0

        client = MagicMock(spec=RateLimitedClient)

        async def fake_paginated_get(*args: object, **kwargs: object):  # type: ignore[return]
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
        responses_by_endpoint = {
            "/users": [{"gid": "u1", "name": "User1"}],
            "/projects": [{"gid": "p1", "name": "Proj1"}],
            "/tasks": [{"gid": "t1", "name": "Task1"}],
        }

        client = MagicMock(spec=RateLimitedClient)

        async def fake_paginated_get(endpoint: str, *, params=None, workspace_gid=None):  # type: ignore[return]
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
        responses_by_endpoint = {
            "/users": [],
            "/projects": [],
            "/tasks": [],
        }

        client = MagicMock(spec=RateLimitedClient)

        async def fake_paginated_get(endpoint: str, *, params=None, workspace_gid=None):  # type: ignore[return]
            for entity in responses_by_endpoint.get(endpoint, []):
                yield entity

        client.paginated_get = fake_paginated_get
        writer = make_fake_writer()

        result = await extract_workspace(client, writer, workspace_gid="ws1")

        assert result.task_result.count == 0
        assert result.total_entities == 0
        writer.write_entity.assert_not_called()
