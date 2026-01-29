"""Logging configuration for SDLC Agent System."""

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor


def setup_logging(level: str = "INFO", log_format: str = "json") -> None:
    """
    Configure structured logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_format: Output format ('json' or 'text')
    """
    # Convert string level to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Common processors
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if log_format == "json":
        # JSON format for production
        processors: list[Processor] = [
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Human-readable format for development
        processors = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Also configure standard logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=numeric_level,
    )


def get_logger(name: str | None = None, **initial_context: Any) -> structlog.BoundLogger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (typically module name)
        **initial_context: Initial context to bind to logger

    Returns:
        Configured structlog logger
    """
    log = structlog.get_logger(name)
    if initial_context:
        log = log.bind(**initial_context)
    return log
