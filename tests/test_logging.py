"""Tests for structured logging setup."""

import logging

from asana_extractor.logging import configure_logging, get_logger


def test_configure_logging_runs_without_error() -> None:
    configure_logging(log_level="INFO")
    # No exception means success


def test_get_logger_returns_bound_logger() -> None:
    configure_logging(log_level="INFO")
    log = get_logger("test.module")
    assert log is not None
    # Should have standard logging methods
    assert hasattr(log, "info")
    assert hasattr(log, "debug")
    assert hasattr(log, "warning")
    assert hasattr(log, "error")


def test_logger_bind_adds_context() -> None:
    configure_logging(log_level="INFO")
    log = get_logger("test.bind")
    bound = log.bind(workspace_gid="ws-999")
    # bind() returns a new logger — original is unchanged
    assert bound is not None


def test_logger_emits_without_exception() -> None:
    configure_logging(log_level="DEBUG")
    log = get_logger("test.emit")
    # These should not raise
    log.debug("debug_event", key="val")
    log.info("info_event", workspace_gid="123")
    log.warning("warning_event")


def test_configure_logging_accepts_all_levels() -> None:
    for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
        configure_logging(log_level=level)
        # stdlib root logger should reflect the level
        assert logging.getLogger().level == getattr(logging, level)
