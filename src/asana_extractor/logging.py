"""Structured logging configuration using structlog.

Usage:
    from asana_extractor.logging import configure_logging, get_logger

    configure_logging(log_level="INFO")
    log = get_logger(__name__)
    log.info("extraction_started", workspace_gid="12345")

    # Bind workspace context for a subsystem
    workspace_log = log.bind(workspace_gid="12345")
    workspace_log.info("users_extracted", count=42)
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog for JSON output to stdout.

    Call once at application startup before any logging occurs.

    Args:
        log_level: One of DEBUG, INFO, WARNING, ERROR. Controls minimum log level.
    """
    # Configure standard library logging (structlog wraps it)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )
    # Also update root logger level directly (basicConfig is a no-op after first call)
    logging.getLogger().setLevel(getattr(logging, log_level.upper()))

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog bound logger for the given module name.

    Args:
        name: Logger name, typically __name__ of the calling module.

    Returns:
        A structlog BoundLogger that outputs structured JSON.

    Example:
        log = get_logger(__name__)
        log.info("task_complete", entity_count=100, workspace_gid="12345")
    """
    return structlog.get_logger(name)
