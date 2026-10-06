"""ADR-028 C1/C2 log redaction: no WS tokens, no exception messages or locals."""

import io
import json
import logging

import pytest
import structlog

from app.core.logging import (
    RedactingLogFilter,
    configure_logging,
    exception_summary,
    install_redaction_filters,
    redact_text,
    strip_query,
)

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzZWNyZXQifQ.c2lnbmF0dXJl"


@pytest.fixture
def uvicorn_stream():
    """A handler shaped like uvicorn's own ("uvicorn" logger, propagate=False)."""
    configure_logging("WARNING")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("uvicorn")
    previous = (logger.level, logger.propagate)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    install_redaction_filters()
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous[0])
        logger.propagate = previous[1]
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


@pytest.mark.parametrize("template", [
    '%s - "WebSocket %s" [accepted]', '%s - "WebSocket %s" 403', '%s - "WebSocket %s" %d',
])
def test_uvicorn_websocket_upgrade_lines_drop_query_tokens(uvicorn_stream, template):
    args = [("10.0.0.1", 5555), f"/ws/topology?token={TOKEN}"]
    if template.endswith("%d"):
        args.append(403)
    logging.getLogger("uvicorn.error").info(template, *args)
    output = uvicorn_stream.getvalue()
    assert '"WebSocket /ws/topology"' in output
    assert TOKEN not in output and "token=" not in output


def test_uvicorn_access_lines_drop_query_strings(uvicorn_stream):
    access = logging.getLogger("uvicorn.access")
    access.addHandler(logging.StreamHandler(uvicorn_stream))
    try:
        install_redaction_filters()
        access.info('%s - "%s %s HTTP/%s" %d', "10.0.0.1:1", "GET",
                    f"/api/v1/telemetry?token={TOKEN}&page=2", "1.1", 200)
    finally:
        for handler in list(access.handlers):
            access.removeHandler(handler)
    output = uvicorn_stream.getvalue()
    assert '"GET /api/v1/telemetry HTTP/1.1" 200' in output and TOKEN not in output


def test_message_text_redacts_credential_parameters():
    assert redact_text(f"GET /ws/alerts?x=1&token={TOKEN} done") == "GET /ws/alerts?x=1&token=[REDACTED] done"
    assert redact_text("refresh_token=abc;password=hunter2") == "refresh_token=abc;password=[REDACTED]"
    assert strip_query(f"/ws/digital-twin?token={TOKEN}") == "/ws/digital-twin"
    assert strip_query("plain text with token=abc") == "plain text with token=abc"


def _raise_with_secret(secret):
    local_secret = secret  # noqa: F841 - frame local must never be rendered
    raise RuntimeError(f"failure containing {secret}")


def test_stdlib_exception_records_keep_frames_not_messages(uvicorn_stream):
    try:
        _raise_with_secret("hunter2-secret")
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application\n")
    output = uvicorn_stream.getvalue()
    assert "_raise_with_secret" in output and "test_logging_redaction.py" in output
    assert "RuntimeError" in output
    assert "hunter2-secret" not in output and "local_secret" not in output


def test_structlog_exception_summary_is_frames_and_types_only(caplog):
    configure_logging("WARNING")
    try:
        try:
            _raise_with_secret("hunter2-secret")
        except RuntimeError as exc:
            raise ValueError("wrapped hunter2-secret") from exc
    except ValueError as exc:
        structlog.get_logger("tests.redaction").error("failed", exc_info=exc)
        summary = exception_summary(exc)
    [record] = [row for row in caplog.records if row.name == "tests.redaction"]
    event = json.loads(record.message)
    assert event["exception"] == summary
    assert summary["type"] == "ValueError"
    assert summary["chain"][0]["type"] == "RuntimeError"
    assert summary["chain"][0]["frames"][-1]["function"] == "_raise_with_secret"
    assert "hunter2-secret" not in record.message


def test_filters_install_idempotently_and_never_drop_records():
    configure_logging("WARNING")
    configure_logging("WARNING")
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        filters = [item for item in logging.getLogger(name).filters if isinstance(item, RedactingLogFilter)]
        assert len(filters) == 1
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "%s", (object(),), None)
    assert RedactingLogFilter().filter(record) is True
