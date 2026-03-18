"""Unit tests for asana_extractor.models dataclasses and from_api() methods."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from asana_extractor.models import BaseAsanaObject, Project, Task, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow_approx() -> datetime:
    """Return current UTC time for delta assertions."""
    return datetime.now(timezone.utc)


def _assert_recent(dt: datetime, *, tolerance_seconds: float = 2.0) -> None:
    """Assert *dt* is within *tolerance_seconds* of now-UTC."""
    assert abs(dt - _utcnow_approx()) < timedelta(seconds=tolerance_seconds)


# ===========================================================================
# BaseAsanaObject
# ===========================================================================


class TestBaseAsanaObject:
    """Tests for the BaseAsanaObject dataclass."""

    def test_construction(self) -> None:
        now = _utcnow_approx()
        obj = BaseAsanaObject(gid="123", last_fetch_time=now, name="Test")
        assert obj.gid == "123"
        assert obj.last_fetch_time == now
        assert obj.name == "Test"

    def test_name_defaults_to_none(self) -> None:
        now = _utcnow_approx()
        obj = BaseAsanaObject(gid="123", last_fetch_time=now)
        assert obj.name is None

    def test_is_frozen(self) -> None:
        now = _utcnow_approx()
        obj = BaseAsanaObject(gid="123", last_fetch_time=now)
        with pytest.raises(dataclasses.FrozenInstanceError):
            obj.gid = "456"  # type: ignore[misc]


# ===========================================================================
# Task.from_api()
# ===========================================================================


class TestTaskFromApi:
    """Tests for Task.from_api() factory method."""

    def test_happy_path(self) -> None:
        raw = {
            "gid": "task-1",
            "name": "My Task",
            "projects": [
                {"gid": "proj-1", "name": "Alpha"},
                {"gid": "proj-2", "name": "Beta"},
            ],
        }
        task = Task.from_api(raw, project_gid="proj-1")

        assert task.gid == "task-1"
        assert task.name == "My Task"
        assert task.task_name == "My Task"
        assert task.project_gid == "proj-1"
        assert task.project_name == "Alpha"
        _assert_recent(task.last_fetch_time)

    def test_resolves_project_name_from_matching_gid(self) -> None:
        raw = {
            "gid": "t1",
            "name": "Task",
            "projects": [
                {"gid": "other", "name": "Other"},
                {"gid": "target", "name": "Target Project"},
            ],
        }
        task = Task.from_api(raw, project_gid="target")
        assert task.project_name == "Target Project"

    def test_no_matching_project(self) -> None:
        raw = {
            "gid": "t1",
            "name": "Task",
            "projects": [{"gid": "unrelated", "name": "Unrelated"}],
        }
        task = Task.from_api(raw, project_gid="missing")
        assert task.project_name == ""

    def test_empty_projects_list(self) -> None:
        raw = {"gid": "t1", "name": "Task", "projects": []}
        task = Task.from_api(raw, project_gid="proj-1")
        assert task.project_name == ""

    def test_projects_not_a_list(self) -> None:
        # projects is None
        raw_none: dict[str, object] = {"gid": "t1", "name": "Task", "projects": None}
        assert Task.from_api(raw_none, project_gid="p").project_name == ""

        # projects is a string
        raw_str: dict[str, object] = {"gid": "t1", "name": "Task", "projects": "bad"}
        assert Task.from_api(raw_str, project_gid="p").project_name == ""

    def test_missing_fields(self) -> None:
        task = Task.from_api({}, project_gid="p")
        assert task.gid == ""
        assert task.name is None
        assert task.task_name == ""
        assert task.project_gid == "p"
        assert task.project_name == ""

    def test_empty_name_becomes_none(self) -> None:
        raw = {"gid": "t1", "name": ""}
        task = Task.from_api(raw, project_gid="p")
        # name uses `or None` so empty string → None
        assert task.name is None
        # task_name does NOT use `or None` so it stays ""
        assert task.task_name == ""

    def test_sets_last_fetch_time(self) -> None:
        before = _utcnow_approx()
        task = Task.from_api({"gid": "t1"}, project_gid="p")
        after = _utcnow_approx()
        assert before <= task.last_fetch_time <= after


# ===========================================================================
# User.from_api()
# ===========================================================================


class TestUserFromApi:
    """Tests for User.from_api() factory method."""

    def test_happy_path(self) -> None:
        raw = {"gid": "u1", "name": "Alice", "email": "alice@example.com"}
        user = User.from_api(raw)

        assert user.gid == "u1"
        assert user.name == "Alice"
        assert user.email == "alice@example.com"
        _assert_recent(user.last_fetch_time)

    def test_missing_fields(self) -> None:
        user = User.from_api({})
        assert user.gid == ""
        assert user.name is None
        assert user.email is None

    def test_empty_strings_become_none(self) -> None:
        raw = {"gid": "u1", "name": "", "email": ""}
        user = User.from_api(raw)
        assert user.name is None
        assert user.email is None


# ===========================================================================
# Project.from_api()
# ===========================================================================


class TestProjectFromApi:
    """Tests for Project.from_api() factory method."""

    def test_happy_path(self) -> None:
        raw = {
            "gid": "proj-1",
            "name": "My Project",
            "workspace": {"gid": "ws-1"},
        }
        project = Project.from_api(raw)

        assert project.gid == "proj-1"
        assert project.name == "My Project"
        assert project.workspace_gid == "ws-1"
        _assert_recent(project.last_fetch_time)

    def test_no_workspace_key(self) -> None:
        raw = {"gid": "proj-1", "name": "P"}
        project = Project.from_api(raw)
        assert project.workspace_gid is None

    def test_workspace_not_a_dict(self) -> None:
        raw: dict[str, object] = {"gid": "proj-1", "workspace": "not-a-dict"}
        project = Project.from_api(raw)
        assert project.workspace_gid is None

    def test_empty_workspace_gid(self) -> None:
        raw = {"gid": "proj-1", "workspace": {"gid": ""}}
        project = Project.from_api(raw)
        # empty string → `or None` → None
        assert project.workspace_gid is None
