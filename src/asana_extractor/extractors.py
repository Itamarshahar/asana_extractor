"""Entity extraction framework — base class, result type, workspace discovery.

Provides the foundation for extracting Asana entities:
- ExtractionResult: dataclass holding count, duration, and warnings from an extraction run
- BaseExtractor: abstract base class defining the extract() contract for all entity types
- discover_workspaces(): async function to list accessible workspaces

Concrete extractors (UserExtractor, ProjectExtractor, TaskExtractor) subclass
BaseExtractor and implement entity_type, endpoint, and _build_params(). The
extract() method handles pagination, writing, and metrics automatically.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from asana_extractor.logging import get_logger
from asana_extractor.rate_limited_client import RateLimitedClient
from asana_extractor.writer import EntityWriter

__all__ = [
    "BaseExtractor",
    "ExtractionResult",
    "ProjectExtractionResult",
    "ProjectExtractor",
    "TaskExtractor",
    "UserExtractor",
    "WorkspaceExtractionResult",
    "discover_workspaces",
    "extract_workspace",
]


@dataclass
class ExtractionResult:
    """Result of extracting a single entity type from one workspace.

    Attributes:
        entity_type: String identifying the entity, e.g. "users", "projects", "tasks".
        count: Number of entities successfully written to disk.
        duration_seconds: Wall-clock time for the extraction (seconds, rounded to 2dp).
        warnings: Warning messages collected during extraction (e.g., entities skipped
            because they were missing a 'gid' field).
    """

    entity_type: str
    count: int
    duration_seconds: float
    warnings: list[str] = field(default_factory=list)


class BaseExtractor(ABC):
    """Abstract base class for entity extractors.

    Subclasses implement three abstract members:
    - entity_type: str property returning e.g. "users", "projects", "tasks"
    - endpoint: str property returning e.g. "/users", "/projects", "/tasks"
    - _build_params(): builds query parameters for the API call

    The concrete extract() method handles pagination via client.paginated_get(),
    writes each entity to disk via writer.write_entity(), and returns an
    ExtractionResult with count, duration, and any warnings.

    Dependencies (client, writer) are injected at extract() call time, not at
    construction — extractors are stateless.
    """

    @property
    @abstractmethod
    def entity_type(self) -> str:
        """Return entity type string for output path, e.g. 'users', 'projects', 'tasks'."""

    @property
    @abstractmethod
    def endpoint(self) -> str:
        """Return API endpoint path, e.g. '/users', '/projects', '/tasks'."""

    @abstractmethod
    def _build_params(self, **kwargs: Any) -> dict[str, str]:  # noqa: ANN401
        """Build query parameters for the API call.

        Subclasses define workspace= or project= params as needed.

        Args:
            **kwargs: Additional parameters (e.g., workspace_gid, project_gid).

        Returns:
            Dict of query parameter key-value pairs for the Asana API call.
        """

    async def extract(
        self,
        client: RateLimitedClient,
        writer: EntityWriter,
        workspace_gid: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> ExtractionResult:
        """Extract all entities of this type via paginated_get and write each to disk.

        Iterates the paginated async generator, writing each entity immediately.
        Entities missing a 'gid' field are skipped with a warning.

        Args:
            client: Rate-limited API client.
            writer: Atomic JSON file writer.
            workspace_gid: Workspace identifier for output path and logging.
            **kwargs: Additional parameters passed to _build_params (e.g., project_gid).

        Returns:
            ExtractionResult with count, duration, and any warnings.
        """
        log = get_logger(__name__).bind(
            workspace_gid=workspace_gid,
            entity_type=self.entity_type,
        )
        start_time = time.monotonic()
        count = 0
        warnings: list[str] = []

        params = self._build_params(workspace_gid=workspace_gid, **kwargs)

        log.info("extraction_started", endpoint=self.endpoint)

        async for entity in client.paginated_get(
            self.endpoint, params=params, workspace_gid=workspace_gid
        ):
            gid = entity.get("gid")
            if gid is None:
                msg = (
                    f"Skipped entity missing 'gid': endpoint={self.endpoint} "
                    f"workspace={workspace_gid} entity={repr(entity)[:200]}"
                )
                warnings.append(msg)
                log.warning("entity_missing_gid", entity_repr=repr(entity)[:200])
                continue

            writer.write_entity(workspace_gid, self.entity_type, gid, entity)
            count += 1

        duration = time.monotonic() - start_time

        log.info(
            "extraction_complete",
            count=count,
            duration_seconds=round(duration, 2),
            warning_count=len(warnings),
        )

        return ExtractionResult(
            entity_type=self.entity_type,
            count=count,
            duration_seconds=round(duration, 2),
            warnings=warnings,
        )


class UserExtractor(BaseExtractor):
    """Extracts all users for a workspace via GET /users?workspace={gid}.

    Uses inherited extract() method — no override needed.
    Each user entity is written to output/{workspace_gid}/users/{gid}.json.
    """

    @property
    def entity_type(self) -> str:
        return "users"

    @property
    def endpoint(self) -> str:
        return "/users"

    def _build_params(self, **kwargs: Any) -> dict[str, str]:  # noqa: ANN401
        workspace_gid: str = kwargs["workspace_gid"]
        return {"workspace": workspace_gid}


@dataclass
class ProjectExtractionResult(ExtractionResult):
    """ExtractionResult with collected project GIDs for downstream task extraction."""

    project_gids: list[str] = field(default_factory=list)


@dataclass
class WorkspaceExtractionResult:
    """Aggregated results for a full workspace extraction."""

    workspace_gid: str
    user_result: ExtractionResult
    project_result: ProjectExtractionResult
    task_result: ExtractionResult
    total_entities: int
    total_duration_seconds: float
    warnings: list[str] = field(default_factory=list)


class ProjectExtractor(BaseExtractor):
    """Extracts all projects for a workspace via GET /projects?workspace={gid}.

    Overrides extract() to collect project GIDs while writing entities.
    Returns ProjectExtractionResult with project_gids list for task extraction.
    Each project is written to output/{workspace_gid}/projects/{gid}.json.
    """

    @property
    def entity_type(self) -> str:
        return "projects"

    @property
    def endpoint(self) -> str:
        return "/projects"

    def _build_params(self, **kwargs: Any) -> dict[str, str]:  # noqa: ANN401
        workspace_gid: str = kwargs["workspace_gid"]
        return {"workspace": workspace_gid}

    async def extract(
        self,
        client: RateLimitedClient,
        writer: EntityWriter,
        workspace_gid: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> ProjectExtractionResult:
        """Extract all projects, writing each to disk and collecting GIDs.

        Returns ProjectExtractionResult (extends ExtractionResult) with
        project_gids list that the workspace orchestrator passes to TaskExtractor.
        """
        log = get_logger(__name__).bind(
            workspace_gid=workspace_gid,
            entity_type=self.entity_type,
        )
        log.info("extraction_started", endpoint=self.endpoint)

        start_time = time.monotonic()
        count = 0
        warnings: list[str] = []
        project_gids: list[str] = []
        params = self._build_params(workspace_gid=workspace_gid, **kwargs)

        async for entity in client.paginated_get(
            self.endpoint, params=params, workspace_gid=workspace_gid
        ):
            gid = entity.get("gid")
            if gid is None:
                msg = (
                    f"Skipped entity missing 'gid': endpoint={self.endpoint} "
                    f"workspace={workspace_gid} entity={repr(entity)[:200]}"
                )
                warnings.append(msg)
                log.warning("entity_missing_gid", entity_repr=repr(entity)[:200])
                continue

            writer.write_entity(workspace_gid, self.entity_type, gid, entity)
            project_gids.append(gid)
            count += 1

        duration = time.monotonic() - start_time
        log.info(
            "extraction_complete",
            count=count,
            duration_seconds=round(duration, 2),
            warning_count=len(warnings),
        )

        return ProjectExtractionResult(
            entity_type=self.entity_type,
            count=count,
            duration_seconds=round(duration, 2),
            warnings=warnings,
            project_gids=project_gids,
        )


class TaskExtractor(BaseExtractor):
    """Extracts tasks for projects via GET /tasks?project={gid}, concurrent across projects.

    Unlike User/ProjectExtractor, tasks are scoped to projects not workspaces.
    extract() handles a single project. extract_all() fires concurrent extraction
    across all project GIDs, letting the RateLimitedClient handle throttling.

    Each task entity is written to output/{workspace_gid}/tasks/{gid}.json.
    """

    @property
    def entity_type(self) -> str:
        return "tasks"

    @property
    def endpoint(self) -> str:
        return "/tasks"

    def _build_params(self, **kwargs: Any) -> dict[str, str]:  # noqa: ANN401
        project_gid: str = kwargs["project_gid"]
        return {"project": project_gid}

    async def extract(
        self,
        client: RateLimitedClient,
        writer: EntityWriter,
        workspace_gid: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> ExtractionResult:
        """Extract all tasks for a single project.

        Args:
            client: Rate-limited API client.
            writer: Atomic JSON file writer.
            workspace_gid: Workspace identifier for output path.
            **kwargs: Must include project_gid (str).

        Returns:
            ExtractionResult for this single project's tasks.
        """
        project_gid: str = kwargs["project_gid"]
        log = get_logger(__name__).bind(
            workspace_gid=workspace_gid,
            entity_type=self.entity_type,
            project_gid=project_gid,
        )
        log.info("task_extraction_started")

        start_time = time.monotonic()
        count = 0
        warnings: list[str] = []
        params = self._build_params(project_gid=project_gid)

        async for entity in client.paginated_get(
            self.endpoint, params=params, workspace_gid=workspace_gid
        ):
            gid = entity.get("gid")
            if gid is None:
                msg = (
                    f"Skipped task missing 'gid': project={project_gid} "
                    f"workspace={workspace_gid} entity={repr(entity)[:200]}"
                )
                warnings.append(msg)
                log.warning("entity_missing_gid", entity_repr=repr(entity)[:200])
                continue

            writer.write_entity(workspace_gid, self.entity_type, gid, entity)
            count += 1

        duration = time.monotonic() - start_time
        log.info(
            "task_extraction_complete",
            project_gid=project_gid,
            count=count,
            duration_seconds=round(duration, 2),
        )

        return ExtractionResult(
            entity_type=self.entity_type,
            count=count,
            duration_seconds=round(duration, 2),
            warnings=warnings,
        )

    async def extract_all(
        self,
        client: RateLimitedClient,
        writer: EntityWriter,
        workspace_gid: str,
        project_gids: list[str],
    ) -> ExtractionResult:
        """Extract tasks concurrently across all projects in a workspace.

        Fires concurrent extract() calls for each project_gid. The
        RateLimitedClient handles throttling via its token bucket and global
        semaphore — this method just fires and lets the rate limiter queue.

        Args:
            client: Rate-limited API client.
            writer: Atomic JSON file writer.
            workspace_gid: Workspace identifier.
            project_gids: List of project GIDs to extract tasks from.

        Returns:
            Aggregated ExtractionResult across all projects.
        """
        log = get_logger(__name__).bind(
            workspace_gid=workspace_gid,
            entity_type="tasks",
        )

        if not project_gids:
            log.info("task_extraction_skipped", reason="no_projects")
            return ExtractionResult(
                entity_type=self.entity_type,
                count=0,
                duration_seconds=0.0,
            )

        log.info("task_extraction_all_started", project_count=len(project_gids))
        start_time = time.monotonic()

        # Fire concurrent extraction — rate limiter handles throttling
        coros = [
            self.extract(client, writer, workspace_gid, project_gid=pgid) for pgid in project_gids
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # Aggregate results
        total_count = 0
        all_warnings: list[str] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                pgid = project_gids[i]
                msg = f"Task extraction failed for project {pgid}: {result}"
                all_warnings.append(msg)
                log.error(
                    "task_extraction_project_failed",
                    project_gid=pgid,
                    error=str(result),
                )
            elif isinstance(result, ExtractionResult):
                total_count += result.count
                all_warnings.extend(result.warnings)

        duration = time.monotonic() - start_time
        log.info(
            "task_extraction_all_complete",
            total_tasks=total_count,
            projects_attempted=len(project_gids),
            projects_failed=sum(1 for r in results if isinstance(r, Exception)),
            duration_seconds=round(duration, 2),
        )

        return ExtractionResult(
            entity_type=self.entity_type,
            count=total_count,
            duration_seconds=round(duration, 2),
            warnings=all_warnings,
        )


async def discover_workspaces(client: RateLimitedClient) -> list[dict[str, Any]]:
    """Discover all workspaces accessible to the authenticated user.

    Calls GET /workspaces. This is NOT paginated for typical accounts
    (users rarely have >100 workspaces), so uses client.get() not
    paginated_get().

    Note on client.get() behavior: AsanaClient.get() does
    ``result = raw.get("data", raw); return result if isinstance(result, dict) else raw``
    For /workspaces, Asana returns ``{"data": [...]}`` so ``result`` is a list,
    which is not a dict, so get() returns the full envelope. We extract "data"
    ourselves.

    Args:
        client: Rate-limited API client (authenticated).

    Returns:
        List of workspace dicts as returned by Asana API.
        Each dict contains at minimum 'gid' and 'name' fields.

    Raises:
        AsanaTransientError: On retriable API failures after retries exhausted.
        AsanaPermanentError: On permanent API errors (auth, not found).
    """
    log = get_logger(__name__)
    log.info("workspace_discovery_started")

    response = await client.get("/workspaces")

    # client.get() returns the full envelope for list responses (see docstring above).
    # Handle both envelope dict and direct list for robustness.
    if isinstance(response, dict) and "data" in response:
        workspaces = response["data"]
    elif isinstance(response, list):
        workspaces = response
    else:
        workspaces = [response] if response else []

    if not isinstance(workspaces, list):
        workspaces = []

    log.info("workspace_discovery_complete", workspace_count=len(workspaces))
    return workspaces


async def extract_workspace(
    client: RateLimitedClient,
    writer: EntityWriter,
    workspace_gid: str,
) -> WorkspaceExtractionResult:
    """Extract all entities for a single workspace: users, projects, then tasks.

    Orchestration order (per CONTEXT.md decisions):
    1. Users and projects extracted concurrently (both workspace-level, independent)
    2. Tasks extracted after projects complete (tasks require project GIDs)
    3. Task extraction is concurrent across projects (rate-limiter-throttled)

    Empty workspaces (0 users, 0 projects) complete without error — task
    extraction is simply skipped when project_gids is empty.

    Args:
        client: Rate-limited API client.
        writer: Atomic JSON file writer.
        workspace_gid: Workspace to extract.

    Returns:
        WorkspaceExtractionResult with per-entity-type results and totals.
    """
    log = get_logger(__name__)
    log = log.bind(workspace_gid=workspace_gid)
    log.info("workspace_extraction_started")

    start_time = time.monotonic()
    all_warnings: list[str] = []

    # Phase 1: Extract users and projects concurrently
    user_extractor = UserExtractor()
    project_extractor = ProjectExtractor()

    user_result, project_result = await asyncio.gather(
        user_extractor.extract(client, writer, workspace_gid),
        project_extractor.extract(client, writer, workspace_gid),
    )

    # project_result is ProjectExtractionResult with project_gids
    assert isinstance(project_result, ProjectExtractionResult)
    all_warnings.extend(user_result.warnings)
    all_warnings.extend(project_result.warnings)

    log.info(
        "workspace_phase1_complete",
        users=user_result.count,
        projects=project_result.count,
        project_gids_count=len(project_result.project_gids),
    )

    # Phase 2: Extract tasks for all discovered projects (concurrent)
    task_extractor = TaskExtractor()
    task_result = await task_extractor.extract_all(
        client, writer, workspace_gid, project_result.project_gids
    )
    all_warnings.extend(task_result.warnings)

    total_duration = time.monotonic() - start_time
    total_entities = user_result.count + project_result.count + task_result.count

    log.info(
        "workspace_extraction_complete",
        total_entities=total_entities,
        users=user_result.count,
        projects=project_result.count,
        tasks=task_result.count,
        duration_seconds=round(total_duration, 2),
        warnings_count=len(all_warnings),
    )

    return WorkspaceExtractionResult(
        workspace_gid=workspace_gid,
        user_result=user_result,
        project_result=project_result,
        task_result=task_result,
        total_entities=total_entities,
        total_duration_seconds=round(total_duration, 2),
        warnings=all_warnings,
    )
