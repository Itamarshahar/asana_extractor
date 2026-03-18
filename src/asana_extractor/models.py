"""Typed entity models for extracted Asana data.

Provides dataclass representations of Asana entities so that downstream
consumers receive structured, typed objects instead of raw API dicts.

Currently supported:
- Task: represents a single Asana task with its project membership.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Task:
    """A single Asana task with its project membership.

    Constructed from the raw API dict inside TaskExtractor.extract().
    Converted back to a dict via dataclasses.asdict() before passing to
    EntityWriter.write_entity() — the writer interface stays unchanged.

    Attributes:
        gid: Asana globally-unique identifier for the task.
        task_name: Display name of the task (from the API ``name`` field).
        project_gid: GID of the project this task was extracted from.
            Sourced from the ``project_gid`` kwarg passed to extract().
        project_name: Display name of the project, extracted from the
            ``projects`` list in the API response.  Empty string if not
            available.
    """

    gid: str
    task_name: str
    project_gid: str
    project_name: str

    @staticmethod
    def from_api(raw: dict[str, object], *, project_gid: str) -> Task:
        """Construct a Task from a raw Asana API dict.

        Extracts ``name`` as ``task_name`` and resolves ``project_name``
        from the ``projects`` list in the response.  Falls back to empty
        string for missing fields.

        Args:
            raw: Raw entity dict from the Asana API (via paginated_get).
            project_gid: GID of the project being extracted (passed as
                kwarg to TaskExtractor.extract).

        Returns:
            A fully populated Task instance.
        """
        gid = str(raw.get("gid", ""))
        task_name = str(raw.get("name", ""))

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
            task_name=task_name,
            project_gid=project_gid,
            project_name=project_name,
        )
