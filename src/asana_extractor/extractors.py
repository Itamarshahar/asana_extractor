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

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from asana_extractor.logging import get_logger
from asana_extractor.rate_limited_client import RateLimitedClient
from asana_extractor.writer import EntityWriter

__all__ = ["BaseExtractor", "ExtractionResult", "discover_workspaces"]


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

        params = self._build_params(**kwargs)

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
