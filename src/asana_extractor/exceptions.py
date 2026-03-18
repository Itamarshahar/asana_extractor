"""Custom exception hierarchy for Asana API client errors.

Three-level hierarchy:
- AsanaClientError: base for all API client errors (status, endpoint, message, workspace)
- AsanaTransientError: retriable errors (5xx, timeouts, connection errors)
- AsanaPermanentError: non-retriable errors (4xx, excluding 429 which is handled separately)
"""

from __future__ import annotations

__all__ = ["AsanaClientError", "AsanaPermanentError", "AsanaTransientError"]


class AsanaClientError(Exception):
    """Base exception for all Asana API client errors.

    Attributes:
        status_code: HTTP status code, or None for connection/timeout errors.
        endpoint: The API endpoint path (e.g., "/users").
        message: Human-readable error description.
        workspace_gid: Workspace context if available.
    """

    def __init__(
        self,
        *,
        status_code: int | None,
        endpoint: str,
        message: str,
        workspace_gid: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.endpoint = endpoint
        self.message = message
        self.workspace_gid = workspace_gid
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"AsanaClientError({self.status_code} {self.endpoint}): {self.message}"


class AsanaTransientError(AsanaClientError):
    """Raised when retries are exhausted on transient errors.

    Transient errors include 5xx server errors, timeouts, and connection errors.
    These errors may succeed on a subsequent attempt.

    Attributes:
        retry_after: Retry-After header value in seconds from a 429 response,
            or None if the header was absent/malformed or the error is not a 429.
    """

    def __init__(
        self,
        *,
        status_code: int | None,
        endpoint: str,
        message: str,
        workspace_gid: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(
            status_code=status_code,
            endpoint=endpoint,
            message=message,
            workspace_gid=workspace_gid,
        )

    def __str__(self) -> str:
        return f"AsanaTransientError({self.status_code} {self.endpoint}): {self.message}"


class AsanaPermanentError(AsanaClientError):
    """Raised on permanent 4xx client errors (excluding 429 which is handled by Phase 3).

    Permanent errors indicate that retrying will not succeed without a change
    in the request (e.g., authorization, resource not found, bad request).
    """

    def __str__(self) -> str:
        return f"AsanaPermanentError({self.status_code} {self.endpoint}): {self.message}"
