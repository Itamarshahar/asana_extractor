"""Typed entity models for extracted Asana data.

Provides dataclass representations of Asana entities so that downstream
consumers receive structured, typed objects instead of raw API dicts.

All models inherit from :class:`BaseAsanaObject` which carries the common
``gid``, ``name``, and ``last_fetch_time`` fields shared by every Asana
entity.

Supported models:
- BaseAsanaObject: abstract base with common Asana fields.
- Task: a single Asana task with its project membership.
- User: an Asana user / assignee.
- Project: an Asana project.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class BaseAsanaObject:
    """Common fields shared by all Asana entity models.

    Attributes:
        gid: Asana globally-unique identifier for the object.
        last_fetch_time: UTC timestamp of when this record was last
            fetched from the Asana API.
        name: Human-readable name of the object.  ``None`` when the API
            response does not include a name.
    """

    gid: str
    last_fetch_time: datetime
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Task(BaseAsanaObject):
    """A single Asana task with its project membership.

    Constructed from the raw API dict inside TaskExtractor.extract().
    Converted back to a dict via dataclasses.asdict() before passing to
    EntityWriter.write_entity() — the writer interface stays unchanged.

    Attributes:
        project_gid: GID of the project this task was extracted from.
            Sourced from the ``project_gid`` kwarg passed to extract().
        project_name: Display name of the project, extracted from the
            ``projects`` list in the API response.  Empty string if not
            available.
    """

    project_gid: str = ""
    project_name: str = ""

    @staticmethod
    def from_api(raw: dict[str, object], *, project_gid: str) -> Task:
        """Construct a Task from a raw Asana API dict.

        Resolves ``project_name`` from the ``projects`` list in the
        response.  Falls back to empty string for missing fields.

        Args:
            raw: Raw entity dict from the Asana API (via paginated_get).
            project_gid: GID of the project being extracted (passed as
                kwarg to TaskExtractor.extract).

        Returns:
            A fully populated Task instance.
        """
        gid = str(raw.get("gid", ""))
        name = str(raw.get("name", "")) or None

        # Resolve project_name from the embedded projects list
        project_name = ""
        projects = raw.get("projects")
        if isinstance(projects, list):
            for proj in projects:
                if isinstance(proj, dict) and proj.get("gid") == project_gid:
                    project_name = str(proj.get("name", ""))
                    break

        return Task(
            gid=gid,
            last_fetch_time=datetime.now(UTC),
            name=name,
            project_gid=project_gid,
            project_name=project_name,
        )


@dataclass(frozen=True, slots=True)
class User(BaseAsanaObject):
    """An Asana user."""

    @staticmethod
    def from_api(raw: dict[str, object]) -> User:
        """Construct a User from a raw Asana API dict.

        Args:
            raw: Raw entity dict from the Asana API.

        Returns:
            A fully populated User instance.
        """
        return User(
            gid=str(raw.get("gid", "")),
            last_fetch_time=datetime.now(UTC),
            name=str(raw.get("name", "")) or None,
        )


@dataclass(frozen=True, slots=True)
class Project(BaseAsanaObject):
    """An Asana project.

    Attributes:
        workspace_gid: GID of the workspace this project belongs to.
            ``None`` when not available.
    """

    workspace_gid: str | None = None

    @staticmethod
    def from_api(raw: dict[str, object], *, workspace_gid: str | None = None) -> Project:
        """Construct a Project from a raw Asana API dict.

        Args:
            raw: Raw entity dict from the Asana API.
            workspace_gid: Workspace GID known from the extraction context.
                Used as the primary source; falls back to the ``workspace``
                nested object in the API response if not provided.

        Returns:
            A fully populated Project instance.
        """
        resolved_workspace_gid: str | None = workspace_gid
        if resolved_workspace_gid is None:
            workspace = raw.get("workspace")
            if isinstance(workspace, dict):
                resolved_workspace_gid = str(workspace.get("gid", "")) or None

        return Project(
            gid=str(raw.get("gid", "")),
            last_fetch_time=datetime.now(UTC),
            name=str(raw.get("name", "")) or None,
            workspace_gid=resolved_workspace_gid,
        )
