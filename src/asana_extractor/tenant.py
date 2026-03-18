"""Multi-tenant data contracts for workspace orchestration.

The multi-tenant model represents each customer as a (workspace_gid, PAT) pair.
A TenantProvider ABC abstracts the credential source — the orchestrator works
against any backend (database, secret manager, environment variables) without
code changes. OrchestratorResult and WorkspaceError capture run outcomes so
that run() never raises, enabling Phase 7 (Scheduler) to inspect failures cleanly.
"""

from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "EnvTenantProvider",
    "OrchestratorResult",
    "TenantConfig",
    "TenantProvider",
    "WorkspaceError",
]


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


class EnvTenantProvider(TenantProvider):
    """Reads tenant configurations from the tenants array in config.json.

    The config.json file must contain a top-level "tenants" array:
    ```json
    {
        "extraction_interval": 300,
        "tenants": [
            {"workspace_gid": "12345678901234", "pat": "1/your-token-here"},
            {"workspace_gid": "98765432109876", "pat": "1/another-token"}
        ]
    }
    ```

    Each entry must have "workspace_gid" and "pat" fields.

    Args:
        config_path: Path to config.json. Defaults to "config.json" in the
                     current working directory.
    """

    def __init__(self, config_path: str | Path = "config.json") -> None:
        self._config_path = Path(config_path)

    def list_tenants(self) -> list[TenantConfig]:
        """Read and return tenant configurations from config.json.

        Exits with a clear error message if:
        - The config file doesn't exist
        - The file is not valid JSON
        - The "tenants" key is missing or not an array
        - Any tenant entry is missing "workspace_gid" or "pat"

        Returns:
            List of TenantConfig objects. Returns empty list if tenants array
            is empty (not an error condition — orchestrator handles empty list).
        """
        if not self._config_path.exists():
            print(
                f"ERROR: Configuration file not found: {self._config_path}\n"
                f"Add a 'tenants' array to your config.json.",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            raw = json.loads(self._config_path.read_text())
        except json.JSONDecodeError as exc:
            print(f"ERROR: config.json is not valid JSON: {exc}", file=sys.stderr)
            sys.exit(1)

        tenants_raw = raw.get("tenants")
        if tenants_raw is None:
            print(
                "ERROR: config.json is missing required key 'tenants'.\n"
                "Add a 'tenants' array with objects containing 'workspace_gid' and 'pat'.",
                file=sys.stderr,
            )
            sys.exit(1)

        if not isinstance(tenants_raw, list):
            print(
                "ERROR: 'tenants' in config.json must be an array.",
                file=sys.stderr,
            )
            sys.exit(1)

        tenants: list[TenantConfig] = []
        for i, entry in enumerate(tenants_raw):
            if not isinstance(entry, dict):
                print(
                    f"ERROR: tenants[{i}] must be an object with 'workspace_gid' and 'pat'.",
                    file=sys.stderr,
                )
                sys.exit(1)
            workspace_gid = entry.get("workspace_gid")
            pat = entry.get("pat")
            if not workspace_gid or not isinstance(workspace_gid, str):
                print(
                    f"ERROR: tenants[{i}].workspace_gid is missing or not a string.",
                    file=sys.stderr,
                )
                sys.exit(1)
            if not pat or not isinstance(pat, str):
                print(
                    f"ERROR: tenants[{i}].pat is missing or not a string.",
                    file=sys.stderr,
                )
                sys.exit(1)
            tenants.append(TenantConfig(workspace_gid=workspace_gid, pat=pat))

        return tenants


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
