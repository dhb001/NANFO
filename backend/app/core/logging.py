"""NANFO Backend — Structured logging configuration.

Uses structlog with ISO8601 timestamps and correlation ID injection.
All log entries carry a request_id when available (coding-standards.md:
'Use structured logging with correlation/request identifiers where available').

Implementation note: uses structlog.stdlib.LoggerFactory (not PrintLoggerFactory)
so that every logger has a .name attribute — required by the add_logger_name processor.
"""

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog + stdlib logging for the application.

    Must be called once at application startup before any log emission.
    Also called from the test conftest at WARNING level to enable unit tests
    to use structlog without hitting the 'PrintLogger has no .name' error.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure stdlib root handler (JSON to stdout)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not root_logger.handlers:
        root_logger.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),   # stdlib — has .name
        cache_logger_on_first_use=True,
    )

    # Silence noisy stdlib loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named structlog logger."""
    return structlog.get_logger(name)
