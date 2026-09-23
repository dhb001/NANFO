"""ADR027 bounded request identity shared by envelopes and structured logs."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core.config import get_settings

# Protocol bound, not an operational setting. Never truncate correlation identity.
MAX_REQUEST_ID_LENGTH = 128


def normalize_request_id(value: str | None) -> str:
    """Preserve opaque printable ASCII IDs; reject unsafe/oversized supplied IDs."""
    if not value:
        return str(uuid.uuid4())
    if len(value) > MAX_REQUEST_ID_LENGTH or not value.isascii() or not value.isprintable() or not value.strip():
        raise HTTPException(400, detail={
            "code": "REQUEST_ID_INVALID",
            "message": "X-Request-ID must be 1..128 printable ASCII characters.",
        })
    return value


class RequestMeta:
    """Holds the single request identity and UTC timestamp for envelope construction."""

    def __init__(self, request_id: str, timestamp: str, request: Request):
        self.request_id = request_id
        self.timestamp = timestamp
        self.request = request


def request_context(request: Request) -> RequestMeta:
    """Cache even rejected requests' safe metadata for exception handling."""
    if not hasattr(request.state, "request_meta"):
        try:
            values = request.headers.getlist("X-Request-ID")
            if len(values) > 1:
                raise HTTPException(400, detail={
                    "code": "REQUEST_ID_INVALID",
                    "message": "Supply only one X-Request-ID header.",
                })
            request_id = normalize_request_id(values[0] if values else None)
            error = None
        except HTTPException as exc:
            request_id, error = str(uuid.uuid4()), exc
        request.state.request_id_error = error
        request.state.request_meta = RequestMeta(request_id, datetime.now(UTC).isoformat(), request)
    return request.state.request_meta


def error_meta(request: Request) -> dict:
    meta = request_context(request)
    return {"request_id": meta.request_id, "timestamp": meta.timestamp,
            "execution_mode": get_settings().EXECUTION_MODE}


class RequestContextMiddleware:
    """Pure ASGI middleware keeps context through errors/streaming and clears it."""

    def __init__(self, app, *, http_error_handler, error_handler):
        self.app = app
        self.http_error_handler = http_error_handler
        self.error_handler = error_handler

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        clear_contextvars()
        request = Request(scope)
        response_started = False
        try:
            meta = request_context(request)
            bind_contextvars(request_id=meta.request_id, request_timestamp=meta.timestamp)

            async def send_with_identity(message):
                nonlocal response_started
                if message["type"] == "http.response.start":
                    response_started = True
                    MutableHeaders(scope=message)["X-Request-ID"] = meta.request_id
                await send(message)

            if request.state.request_id_error is not None:
                response = await self.http_error_handler(request, request.state.request_id_error)
                await response(scope, receive, send_with_identity)
                return
            try:
                await self.app(scope, receive, send_with_identity)
            except Exception as exc:
                # Handle before context cleanup, unlike the outer ServerErrorMiddleware.
                # A started stream cannot be replaced by a second response.
                if response_started:
                    raise
                response = await self.error_handler(request, exc)
                await response(scope, receive, send_with_identity)
        finally:
            clear_contextvars()
