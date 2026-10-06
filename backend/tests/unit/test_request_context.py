"""ADR027 request identity, context isolation, errors and secret-safe validation."""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ValidationError, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from structlog.contextvars import bind_contextvars, get_contextvars

from app.core.dependencies import RequestMeta, get_request_meta
from app.core.logging import get_logger
from app.core.request_context import RequestContextMiddleware
from app.core.security import JWTError
from app.main import (
    http_exception_handler,
    jwt_error_handler,
    request_validation_exception_handler,
    unhandled_exception_handler,
)
from app.modules.organization.schemas import CreateOrgRequest, UpdateOrgRequest
from app.modules.report.schemas import GenerateReportRequest, ReportDateRangeRequest, ReportScope
from app.modules.telemetry.schemas import TelemetryCursorRequest, TelemetryHistoryQuery


class SecretInput(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def reject(cls, value):
        raise ValueError(f"Rejected sensitive value: {value}")


@pytest.fixture
def context_app():
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(JWTError, jwt_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_middleware(RequestContextMiddleware, http_error_handler=http_exception_handler,
                       error_handler=unhandled_exception_handler)
    app.state.entered = 0

    @app.get("/probe/{outcome}")
    async def probe(outcome: str, request: Request, meta: Annotated[RequestMeta, Depends(get_request_meta)]):
        app.state.entered += 1
        assert await get_request_meta(request) is meta
        before = get_contextvars()
        await asyncio.sleep(0.001)
        assert get_contextvars() == before
        get_logger(__name__).warning("probe", observed_request_timestamp=meta.timestamp)
        if outcome == "http":
            raise HTTPException(429, detail="Retry later.", headers={"Retry-After": "60"})
        if outcome == "jwt":
            raise JWTError("sensitive-token")
        if outcome == "unhandled":
            raise RuntimeError("sensitive-internal-value")
        return {"meta": {"request_id": meta.request_id, "timestamp": meta.timestamp}, "context": before}

    @app.post("/secret")
    async def secret(body: SecretInput):
        return {}

    return app


@pytest.mark.parametrize("request_id", [None, "req_opaque/27", str(uuid.UUID(int=27))])
@pytest.mark.parametrize("outcome,code", [("ok", 200), ("http", 429), ("jwt", 401), ("unhandled", 500)])
async def test_shared_response_and_log_metadata(context_app, caplog, request_id, outcome, code):
    headers = {"X-Request-ID": request_id} if request_id else {}
    async with AsyncClient(transport=ASGITransport(app=context_app), base_url="http://test") as client:
        response = await client.get(f"/probe/{outcome}", headers=headers)
    assert response.status_code == code
    meta = response.json()["meta"]
    assert datetime.fromisoformat(meta["timestamp"]).utcoffset().total_seconds() == 0
    assert response.headers["x-request-id"] == meta["request_id"]
    if request_id:
        assert meta["request_id"] == request_id
    else:
        uuid.UUID(meta["request_id"])
    events = [json.loads(row.message) for row in caplog.records
              if row.name in (__name__, "app.main", "app.core.exception_handlers")]
    assert events
    for event in events:
        assert event["request_id"] == meta["request_id"]
        assert event["request_timestamp"] == meta["timestamp"]
    if outcome == "http":
        assert response.headers["retry-after"] == "60"
    if outcome == "unhandled":
        # ADR-028 C2: the redacted stack (types + frames) is logged with the request id.
        [failure] = [event for event in events if event["event"] == "unhandled_exception"]
        assert failure["exception"]["type"] == "RuntimeError"
        frames = failure["exception"]["frames"]
        assert frames[-1]["function"] == "probe" and frames[-1]["file"].endswith("test_request_context.py")
        assert all(set(frame) == {"file", "line", "function"} for frame in frames)
    assert "sensitive" not in response.text
    assert "sensitive" not in caplog.text
    assert get_contextvars() == {}


async def test_concurrent_and_sequential_requests_do_not_leak_context(context_app):
    async with AsyncClient(transport=ASGITransport(app=context_app), base_url="http://test") as client:
        async def invoke(index):
            bind_contextvars(stale="must-be-cleared")
            response = await client.get("/probe/ok", headers={"X-Request-ID": f"req_{index}"})
            body = response.json()
            assert body["context"] == {"request_id": f"req_{index}",
                                       "request_timestamp": body["meta"]["timestamp"]}
            assert get_contextvars() == {}
        await asyncio.gather(*(invoke(index) for index in range(12)))
        await invoke(12)
        generated = [(await client.get("/probe/ok")).json()["meta"]["request_id"] for _ in range(2)]
        assert generated[0] != generated[1]


@pytest.mark.parametrize("value", ["x" * 129, "bad\nheader", "bad\x00header", "   ", "bad\x7fheader"])
async def test_invalid_header_rejected_before_route(context_app, value):
    async with AsyncClient(transport=ASGITransport(app=context_app), base_url="http://test") as client:
        response = await client.get("/probe/ok", headers={"X-Request-ID": value})
    assert response.status_code == 400
    assert response.json()["errors"]["code"] == "REQUEST_ID_INVALID"
    uuid.UUID(response.json()["meta"]["request_id"])
    assert context_app.state.entered == 0
    assert get_contextvars() == {}


async def test_maximum_length_and_empty_header(context_app):
    async with AsyncClient(transport=ASGITransport(app=context_app), base_url="http://test") as client:
        response = await client.get("/probe/ok", headers={"X-Request-ID": "x" * 128})
        assert response.json()["meta"]["request_id"] == "x" * 128
        response = await client.get("/probe/ok", headers={"X-Request-ID": ""})
        uuid.UUID(response.json()["meta"]["request_id"])


async def test_validation_never_echoes_interpolated_secret(context_app, caplog):
    async with AsyncClient(transport=ASGITransport(app=context_app), base_url="http://test") as client:
        response = await client.post("/secret", json={"password": "private-password-027"})
    assert response.status_code == 422
    assert response.json()["errors"] == {
        "code": "VALIDATION_ERROR", "message": "Request validation failed.",
        # ADR-028 C2: location and error type only; never input or ctx.
        "details": [{"loc": ["body", "password"], "type": "value_error"}],
    }
    assert response.json()["meta"]["timestamp"]
    assert "private-password-027" not in response.text + caplog.text
    assert get_contextvars() == {}


async def test_cancellation_clears_context():
    async def cancelled(scope, receive, send):
        assert get_contextvars()["request_id"] == "req_cancel"
        raise asyncio.CancelledError()

    middleware = RequestContextMiddleware(cancelled, http_error_handler=http_exception_handler,
                                          error_handler=unhandled_exception_handler)
    with pytest.raises(asyncio.CancelledError):
        await middleware({"type": "http", "headers": [(b"x-request-id", b"req_cancel")]}, None, None)
    assert get_contextvars() == {}


async def test_binary_stream_and_started_response_failure_clear_context():
    messages = []

    async def send(message):
        messages.append(message)

    async def stream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/octet-stream"), (b"etag", b'"sha256:abc"')]})
        await send({"type": "http.response.body", "body": b"\x00\xff", "more_body": True})
        assert get_contextvars()["request_id"] == "req_binary"
        raise RuntimeError("stream failed after headers")

    middleware = RequestContextMiddleware(stream, http_error_handler=http_exception_handler,
                                          error_handler=unhandled_exception_handler)
    with pytest.raises(RuntimeError, match="stream failed"):
        await middleware({"type": "http", "headers": [(b"x-request-id", b"req_binary")]}, None, send)
    assert len(messages) == 2  # no replacement JSON or second response start
    assert messages[1]["body"] == b"\x00\xff"
    assert dict(messages[0]["headers"]) == {
        b"content-type": b"application/octet-stream", b"etag": b'"sha256:abc"', b"x-request-id": b"req_binary",
    }
    assert get_contextvars() == {}


async def test_standalone_dependency_caches_metadata_and_rejects_non_ascii():
    request = Request({"type": "http", "headers": []})
    first = await get_request_meta(request)
    assert await get_request_meta(request) is first
    uuid.UUID(first.request_id)
    request = Request({"type": "http", "headers": [(b"x-request-id", b"bad\xff")]})
    with pytest.raises(HTTPException) as error:
        await get_request_meta(request)
    assert error.value.status_code == 400


@pytest.mark.parametrize("second", ["req_other", "x" * 129, "bad\nheader"])
async def test_duplicate_request_ids_rejected_before_route(context_app, second):
    async with AsyncClient(transport=ASGITransport(app=context_app), base_url="http://test") as client:
        response = await client.get("/probe/ok", headers=[("X-Request-ID", "req_first"), ("X-Request-ID", second)])
    assert response.status_code == 400
    assert response.json()["errors"]["code"] == "REQUEST_ID_INVALID"
    uuid.UUID(response.json()["meta"]["request_id"])
    assert context_app.state.entered == 0
    assert get_contextvars() == {}


@pytest.mark.parametrize("model,data,expected", [
    (TelemetryHistoryQuery, {"start_time": "2026-09-02T00:00:00Z", "end_time": "2026-09-01T00:00:00Z"},
     "start_time must be before end_time (exclusive)"),
    (TelemetryHistoryQuery, {"aggregation": "sum"}, "aggregation requires a metric"),
    (TelemetryHistoryQuery, {"metric": "flow_private-secret", "aggregation": "sum"},
     "flow_* aggregation is unavailable: snapshot v1 has no durable flow match identity; use raw history"),
    (TelemetryHistoryQuery, {"metric": "cpu", "aggregation": "sum"},
     "aggregation requires start_time, end_time and bucket_seconds"),
    (TelemetryHistoryQuery, {"metric": "cpu", "aggregation": "sum", "bucket_seconds": 60,
                             "start_time": "2026-09-01T00:00:00Z", "end_time": "2026-09-09T00:00:00Z"},
     "aggregation time range must not exceed seven days"),
    (TelemetryHistoryQuery, {"bucket_seconds": 60}, "bucket_seconds requires aggregation"),
    (TelemetryCursorRequest, {"pagination": "cursor", "page": 2}, "cursor mode requires raw history and page=1"),
    (TelemetryCursorRequest, {"cursor": "private-secret"}, "cursor requires pagination=cursor"),
    (ReportDateRangeRequest, {"start": "2026-09-02T00:00:00Z", "end": "2026-09-01T00:00:00Z"},
     "date_range must be increasing and at most 31 days; end is exclusive"),
    (ReportDateRangeRequest, {"start": "2999-09-01T00:00:00Z", "end": "2999-09-02T00:00:00Z"},
     "date_range cannot extend into the future"),
    (ReportScope, {"simulation_ids": [str(uuid.UUID(int=1))] * 2}, "duplicate source IDs"),
    (UpdateOrgRequest, {}, "Supply at least one field; name cannot be null."),
    (CreateOrgRequest, {"name": "Test", "slug": "private-secret!"},
     "Slug must be 3-63 characters, lowercase alphanumeric and hyphens only, and must not start or end with a hyphen."),
])
async def test_reviewed_domain_messages_from_actual_validators(model, data, expected, caplog):
    with pytest.raises(ValidationError) as error:
        model.model_validate(data)
    response = await request_validation_exception_handler(
        Request({"type": "http", "headers": []}), RequestValidationError(error.value.errors()),
    )
    body = json.loads(response.body)
    assert response.status_code == 422
    assert {key: body["errors"][key] for key in ("code", "message")} == {
        "code": "VALIDATION_ERROR", "message": f"Value error, {expected}",
    }
    assert all(set(item) == {"loc", "type"} for item in body["errors"]["details"])
    assert "private-secret" not in response.body.decode() + caplog.text


@pytest.mark.parametrize("overrides,expected", [
    ({"scope": {"simulation_ids": [str(uuid.UUID(int=1))]}}, "simulation_ids require a simulation or summary report"),
    ({"scope": {"intent_ids": [str(uuid.UUID(int=1))]}}, "intent_ids require an intent or summary report"),
    ({"filters": {"metric": "private-secret"}}, "metric requires a telemetry or summary report"),
    ({"report_type": "telemetry", "filters": {"alert_status": "active"}},
     "alert filters require an alerts or summary report"),
])
async def test_reviewed_report_filter_guidance(overrides, expected):
    with pytest.raises(ValidationError) as error:
        GenerateReportRequest.model_validate({
            "workspace_id": str(uuid.UUID(int=27)), "report_type": "alerts", "format": "csv",
            "date_range": {"start": "2026-09-01T00:00:00Z", "end": "2026-09-02T00:00:00Z"}, **overrides,
        })
    response = await request_validation_exception_handler(
        Request({"type": "http", "headers": []}), RequestValidationError(error.value.errors()),
    )
    assert json.loads(response.body)["errors"]["message"] == f"Value error, {expected}"
    assert "private-secret" not in response.body.decode()


@pytest.mark.parametrize("error_type,message", [
    ("value_error", "Value error, aggregation requires a metric: private-secret"),
    ("value_error", "Value error, private-secret aggregation requires a metric"),
    ("value_error", "Value error, aggregation requires a metric\nprivate-secret"),
    ("value_error", "Value error, private-secret"),
    ("assertion_error", "Value error, aggregation requires a metric"),
    ("value_error", {"private-secret": "aggregation requires a metric"}),
    ([], "private-secret"),
])
async def test_non_allowlisted_validation_output_is_redacted(error_type, message, caplog):
    error = RequestValidationError([{
        "type": error_type, "msg": message, "input": "private-secret", "loc": ("body", "private-secret"),
        "ctx": {"error": ValueError("private-secret")},
    }], body={"password": "private-secret"})
    response = await request_validation_exception_handler(Request({"type": "http", "headers": []}), error)
    assert json.loads(response.body)["errors"]["message"] == "Request validation failed."
    assert "private-secret" not in response.body.decode() + caplog.text


async def test_allowlisted_message_does_not_serialize_secret_context(caplog):
    error = RequestValidationError([{
        "type": "value_error", "msg": "Value error, aggregation requires a metric",
        "input": {"password": "private-secret"}, "loc": ("body", "private-secret"),
        "ctx": {"error": ValueError("private-secret")},
    }], body="private-secret")
    response = await request_validation_exception_handler(Request({"type": "http", "headers": []}), error)
    assert json.loads(response.body)["errors"]["message"] == "Value error, aggregation requires a metric"
    assert "private-secret" not in response.body.decode() + caplog.text


async def test_failing_error_handler_still_clears_context():
    async def broken(scope, receive, send):
        raise RuntimeError("route failure")

    async def broken_handler(request, exc):
        assert get_contextvars()["request_id"] == "req_error_handler"
        raise RuntimeError("handler failure")

    middleware = RequestContextMiddleware(broken, http_error_handler=broken_handler, error_handler=broken_handler)
    with pytest.raises(RuntimeError, match="handler failure"):
        await middleware({"type": "http", "headers": [(b"x-request-id", b"req_error_handler")]}, None, None)
    assert get_contextvars() == {}


@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
async def test_non_http_scope_passes_through_without_request_metadata(scope_type):
    scope = {"type": scope_type}
    calls = []

    async def downstream(actual, receive, send):
        calls.append(actual)

    middleware = RequestContextMiddleware(downstream, http_error_handler=http_exception_handler,
                                          error_handler=unhandled_exception_handler)
    await middleware(scope, None, None)
    assert calls == [scope]
    assert "state" not in scope


async def test_validation_details_mask_client_controlled_keys():
    """C2 details carry declared locations only; extra/dict keys may themselves be secrets."""
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)

    class Strict(BaseModel):
        model_config = {"extra": "forbid"}
        name: str

    @app.post("/strict")
    async def strict(body: Strict):
        return {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strict", json={"name": 1, "tok-private-secret": "value-private-secret"})
    assert response.status_code == 422
    details = response.json()["errors"]["details"]
    assert {"loc": ["body", "name"], "type": "string_type"} in details
    assert {"loc": ["body", "*"], "type": "extra_forbidden"} in details
    assert "private-secret" not in response.text


async def test_jwt_error_uses_the_canonical_401_code(context_app):
    async with AsyncClient(transport=ASGITransport(app=context_app), base_url="http://test") as client:
        response = await client.get("/probe/jwt")
    assert response.status_code == 401
    assert response.json()["errors"]["code"] == "AUTH_TOKEN_MISSING_OR_INVALID"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("path", ["/health", "/ready"])
@pytest.mark.parametrize("headers", [
    [("X-Request-ID", "req_first"), ("X-Request-ID", "req_second")],
    [("X-Request-ID", "bad\x7fheader")],
])
async def test_probe_paths_tolerate_duplicate_or_invalid_request_ids(path, headers):
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware, http_error_handler=http_exception_handler,
                       error_handler=unhandled_exception_handler)

    @app.get(path)
    async def probe(meta: Annotated[RequestMeta, Depends(get_request_meta)]):
        return {"request_id": meta.request_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path, headers=headers)
    assert response.status_code == 200
    uuid.UUID(response.json()["request_id"])
    assert response.headers["x-request-id"] == response.json()["request_id"]
    assert get_contextvars() == {}


async def test_started_stream_failure_logs_redacted_stack_with_request_id(caplog):
    async def stream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("sensitive-stream-detail")

    async def send(message):
        return None

    middleware = RequestContextMiddleware(stream, http_error_handler=http_exception_handler,
                                          error_handler=unhandled_exception_handler)
    with pytest.raises(RuntimeError):
        await middleware({"type": "http", "path": "/stream", "headers": [(b"x-request-id", b"req_stream")]},
                         None, send)
    [event] = [json.loads(row.message) for row in caplog.records if row.name == "app.core.request_context"]
    assert event["request_id"] == "req_stream" and event["exception"]["type"] == "RuntimeError"
    assert event["exception"]["frames"][-1]["function"] == "stream"
    assert "sensitive-stream-detail" not in caplog.text
