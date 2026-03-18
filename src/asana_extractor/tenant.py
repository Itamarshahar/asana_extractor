"""Multi-tenant data contracts for workspace orchestration.

The multi-tenant model represents each customer as a (workspace_gid, PAT) pair.
A TenantProvider ABC abstracts the credential source — the orchestrator works
against any backend (database, secret manager, environment variables) without
code changes. OrchestratorResult and WorkspaceError capture run outcomes so
that run() never raises, enabling Phase 7 (Scheduler) to inspect failures cleanly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

__all__ = ["OrchestratorResult", "TenantConfig", "TenantProvider", "WorkspaceError"]


@dataclass
class TenantConfig:
    """Configuration for a single tenant workspace.

    Each tenant is a (workspace_gid, PAT) pair. The PAT authenticates API
    calls for this specific workspace. In a multi-tenant deployment, each
    tenant typically has its own PAT with access to their workspace only.

    Attributes:
        workspace_gid: Asana workspace GID (e.g., "12345678901234").
        pat: Personal Access Token for authenticating with the Asana API.
    """

    workspace_gid: str
    pat: str


class TenantProvider(ABC):
    """Abstract interface for retrieving tenant configurations.

    Implement this to connect the orchestrator to any credential store:
    database, secret manager (AWS SSM, Azure Key Vault, GCP Secret Manager),
    config file, etc. No changes to WorkspaceOrchestrator required.

    To add a new provider:
        1. Subclass TenantProvider
        2. Implement list_tenants() -> list[TenantConfig]
        3. Pass your provider to the caller (Scheduler or __main__)

    The orchestrator does NOT call list_tenants() itself — the caller
    (Phase 7 Scheduler or __main__) calls provider.list_tenants() and
    passes the result to orchestrator.run().
    """

    @abstractmethod
    def list_tenants(self) -> list[TenantConfig]:
        """Return all tenant configurations.

        Returns:
            List of TenantConfig objects, one per tenant workspace.
            Returns an empty list if no tenants are configured.
        """


@dataclass
class WorkspaceError:
    """Represents a workspace extraction failure.

    Captured when a workspace task raises an exception. Included in
    OrchestratorResult.failed for inspection by callers.

    Attributes:
        workspace_gid: GID of the workspace that failed.
        exception: The exception that caused the failure.
    """

    workspace_gid: str
    exception: Exception


@dataclass
class OrchestratorResult:
    """Aggregated result of a full orchestrator run across all workspaces.

    run() always returns OrchestratorResult and never raises — all failure
    information is captured in the failed list. Callers (Phase 7 Scheduler)
    inspect this to decide whether to log warnings.

    Attributes:
        succeeded: GIDs of workspaces that completed successfully.
        failed: WorkspaceError objects for each failed workspace.
    """

    succeeded: list[str]
    failed: list[WorkspaceError]

    @property
    def total(self) -> int:
        """Total number of workspaces processed."""
        return len(self.succeeded) + len(self.failed)

    @property
    def has_failures(self) -> bool:
        """True if any workspace failed."""
        return len(self.failed) > 0
