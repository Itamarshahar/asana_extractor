"""Asana data extractor — async, rate-limited, workspace-isolated."""

from asana_extractor.client import AsanaClient
from asana_extractor.exceptions import (
    AsanaClientError,
    AsanaPermanentError,
    AsanaTransientError,
)
from asana_extractor.extractors import (
    BaseExtractor,
    ExtractionResult,
    ProjectExtractionResult,
    ProjectExtractor,
    TaskExtractor,
    UserExtractor,
    WorkspaceExtractionResult,
    discover_workspaces,
    extract_workspace,
)
from asana_extractor.orchestrator import WorkspaceOrchestrator
from asana_extractor.rate_limited_client import RateLimitedClient
from asana_extractor.scheduler import ExtractionScheduler
from asana_extractor.tenant import (
    EnvTenantProvider,
    OrchestratorResult,
    TenantConfig,
    TenantProvider,
    WorkspaceError,
)
from asana_extractor.writer import EntityWriter

__version__ = "0.1.0"

__all__ = [
    "AsanaClient",
    "AsanaClientError",
    "AsanaPermanentError",
    "AsanaTransientError",
    "BaseExtractor",
    "EntityWriter",
    "EnvTenantProvider",
    "ExtractionResult",
    "ExtractionScheduler",
    "OrchestratorResult",
    "ProjectExtractionResult",
    "ProjectExtractor",
    "RateLimitedClient",
    "TaskExtractor",
    "TenantConfig",
    "TenantProvider",
    "UserExtractor",
    "WorkspaceError",
    "WorkspaceExtractionResult",
    "WorkspaceOrchestrator",
    "__version__",
    "discover_workspaces",
    "extract_workspace",
]
