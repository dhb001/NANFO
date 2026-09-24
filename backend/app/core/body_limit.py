"""Request body bounds enforced before routing (ADR-028 C2).

Pure ASGI middleware: rejects a declared ``Content-Length`` above the route limit
without reading the body, and counts streamed bytes for chunked/undeclared bodies.
Once the limit is crossed the application receives ``http.disconnect``, anything it
tries to send is suppressed, and a single ``413 REQUEST_TOO_LARGE`` envelope is
returned (FastAPI would otherwise turn the receive error into a generic 400).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from starlette.requests import Request

from app.core.errors import RequestTooLargeError

ASSET_UPLOAD_PATH = re.compile(r"^/api/v1/networks/[^/]+/campus/model-assets/?$")
ErrorHandler = Callable[[Request, Exception], Awaitable]


class _BodyLimitExceeded(RequestTooLargeError):
    """Internal signal raised from receive(); never reaches clients as-is."""


class BodyLimitMiddleware:
    def __init__(self, app, *, default_limit: int, asset_limit: int, error_handler: ErrorHandler):
        if default_limit <= 0 or asset_limit <= 0:
            raise ValueError("Body limits must be positive")
        self.app = app
        self.default_limit = default_limit
        self.asset_limit = asset_limit
        self.error_handler = error_handler

    def limit_for(self, method: str, path: str) -> int:
        if method == "POST" and ASSET_UPLOAD_PATH.match(path):
            return self.asset_limit
        return self.default_limit

    async def _reject(self, scope, receive, send, limit: int) -> None:
        response = await self.error_handler(Request(scope), RequestTooLargeError(limit))
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope.get("method", ""), scope.get("path", ""))
        declared = [value for name, value in scope.get("headers", ()) if name.lower() == b"content-length"]
        if declared:
            try:
                length = int(declared[0])
            except ValueError:
                length = -1
            if length > limit:
                await self._reject(scope, receive, send, limit)
                return

        received = 0
        exceeded = False
        response_started = False

        async def limited_receive():
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyLimitExceeded(limit)
            return message

        async def guarded_send(message):
            nonlocal response_started
            if exceeded and not response_started:
                return  # The application's reaction to the aborted read is discarded.
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not exceeded or response_started:
                raise
        if exceeded and not response_started:
            await self._reject(scope, receive, send, limit)
