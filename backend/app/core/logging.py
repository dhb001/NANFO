"""NANFO Backend — Structured logging configuration.

Uses structlog with ISO8601 timestamps and correlation ID injection.
All log entries carry a request_id when available (coding-standards.md:
'Use structured logging with correlation/request identifiers where available').

Implementation note: uses structlog.stdlib.LoggerFactory (not PrintLoggerFactory)
so that every logger has a .name attribute — required by the add_logger_name processor.

Redaction (ADR-028 C1/C2):
  * Exceptions are logged as type + stack frames (file, line, function) only.
    Exception messages/args and frame locals can carry credentials, tokens or
    payloads and are never rendered, for structlog events and stdlib records alike.
  * Query strings are stripped from request paths in stdlib records (uvicorn logs
    ``WebSocket /ws/x?token=...`` on accept/403), and credential-like query
    parameters are redacted anywhere in a message.
"""

from __future__ import annotations

import logging
import re
import sys
from types import TracebackType
from typing import Any

import structlog

MAX_EXCEPTION_FRAMES = 40
MAX_EXCEPTION_CHAIN = 3
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
_SENSITIVE_QUERY = re.compile(
    r"(?i)([?&;](?:token|access_token|refresh_token|id_token|password|passwd|secret|api_key|apikey|key|auth)=)"
    r"[^&;\s\"'#]*",
)
_PATH_WITH_QUERY = re.compile(r"^(/[^\s?#]*)\?[^\s]*$")


def redact_text(value: str) -> str:
    """Redact credential-like query parameters wherever they appear in text."""
    return _SENSITIVE_QUERY.sub(r"\1[REDACTED]", value)


def strip_query(value: str) -> str:
    """Drop the query string of a bare request path; redact other text."""
    match = _PATH_WITH_QUERY.match(value)
    if match:
        return match.group(1)
    return redact_text(value)


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < MAX_EXCEPTION_CHAIN:
        seen.add(id(current))
        chain.append(current)
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__context__ is not None and not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
    return chain


def _frames(tb: TracebackType | None) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append({"file": code.co_filename, "line": tb.tb_lineno, "function": code.co_name})
        tb = tb.tb_next
    # Innermost frames locate the failure; keep them when bounding.
    return frames[-MAX_EXCEPTION_FRAMES:]


def _type_name(exc: BaseException) -> str:
    kind = type(exc)
    module = kind.__module__
    return kind.__qualname__ if module in ("builtins", "__main__") else f"{module}.{kind.__qualname__}"


def exception_summary(exc: BaseException) -> dict[str, Any]:
    """Redacted, JSON-safe exception description: types and frames, never messages."""
    chain = _exception_chain(exc)
    summary: dict[str, Any] = {"type": _type_name(exc), "frames": _frames(exc.__traceback__)}
    if len(chain) > 1:
        summary["chain"] = [
            {"type": _type_name(item), "frames": _frames(item.__traceback__)} for item in chain[1:]
        ]
    return summary


def format_redacted_exception(exc: BaseException) -> str:
    """Traceback-shaped text for stdlib handlers without messages or locals."""
    lines: list[str] = []
    for index, item in enumerate(reversed(_exception_chain(exc))):
        if index:
            lines.append("During handling of the above exception, another exception occurred:")
        lines.append("Traceback (most recent call last; messages and locals redacted):")
        for frame in _frames(item.__traceback__):
            lines.append(f'  File "{frame["file"]}", line {frame["line"]}, in {frame["function"]}')
        lines.append(_type_name(item))
    return "\n".join(lines)


def _exc_from_info(value: Any) -> BaseException | None:
    if isinstance(value, BaseException):
        return value
    if isinstance(value, tuple) and len(value) == 3 and isinstance(value[1], BaseException):
        return value[1]
    if value is True:
        return sys.exc_info()[1]
    return None


def redact_exception_processor(logger, method_name: str, event_dict: dict) -> dict:
    """structlog processor replacing ``exc_info`` with a redacted exception summary."""
    exc_info = event_dict.pop("exc_info", None)
    exc = _exc_from_info(exc_info)
    if exc is not None:
        event_dict["exception"] = exception_summary(exc)
    return event_dict


class RedactingLogFilter(logging.Filter):
    """Sanitize stdlib records in place; never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "_nanfo_redacted", False):
            return True
        record._nanfo_redacted = True
        try:
            if isinstance(record.msg, str):
                record.msg = redact_text(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(strip_query(arg) if isinstance(arg, str) else arg for arg in record.args)
            elif isinstance(record.args, dict):
                record.args = {
                    key: strip_query(arg) if isinstance(arg, str) else arg for key, arg in record.args.items()
                }
            exc = _exc_from_info(record.exc_info)
            if exc is not None:
                record.exc_text = format_redacted_exception(exc)
                record.exc_info = None
            elif record.exc_text:
                # Pre-rendered text may contain a message; keep only its final type line.
                record.exc_text = "Traceback redacted"
        except Exception:  # noqa: BLE001 - logging must never fail the caller
            record.exc_info = None
            record.exc_text = "Traceback redacted"
        return True


def _install_filter(target: logging.Filterer) -> None:
    if not any(isinstance(item, RedactingLogFilter) for item in target.filters):
        target.addFilter(RedactingLogFilter())


def install_redaction_filters() -> None:
    """Attach redaction to uvicorn/root loggers and every handler they own (idempotent)."""
    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        _install_filter(logger)
        for handler in logger.handlers:
            _install_filter(handler)
    for handler in logging.getLogger().handlers:
        _install_filter(handler)


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
            redact_exception_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),   # stdlib — has .name
        cache_logger_on_first_use=True,
    )

    # Silence noisy stdlib loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    install_redaction_filters()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named structlog logger."""
    return structlog.get_logger(name)
