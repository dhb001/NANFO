"""Platform exception handlers mapping failures onto the standard envelope (ADR-028 C2).

Every response is ``{success:false, data:null, meta:{...}, errors:{code,message}}``.
Nothing derived from exception messages, validator context or input values is ever
returned. Unhandled failures are logged as a redacted stack (types and frames only)
with the request id; see :mod:`app.core.logging`.
"""

from __future__ import annotations

import re
from typing import Any, get_args, get_origin

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.errors import DependencyUnavailableError, RequestTooLargeError
from app.core.failures import dependency_name
from app.core.logging import get_logger
from app.core.request_context import error_meta
from app.core.security import JWTError

logger = get_logger(__name__)

DEFAULT_RETRY_AFTER_SECONDS = 5
MAX_VALIDATION_DETAILS = 20
_PARAMETER_SOURCES = frozenset({"body", "query", "path", "header", "cookie"})
_ERROR_TYPE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _http_error_code(status_code: int) -> str:
    """Map an HTTP status code to the canonical error code string (API_STANDARD.md §4)."""
    return {
        400: "BAD_REQUEST",
        401: "AUTH_TOKEN_MISSING_OR_INVALID",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "REQUEST_TOO_LARGE",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, f"HTTP_{status_code}")


def error_response_headers(request: Request, existing: dict[str, str] | None = None) -> dict[str, str] | None:
    """Apply a narrow CORS fallback for error responses when Origin is allowed.

    CORSMiddleware can miss internal error responses depending on where exceptions
    are raised in the middleware stack. This fallback keeps allowed browser
    clients from seeing opaque CORS failures when a real API error occurs. The
    allowed origin is reflected, so caches must vary on Origin. Credentials are
    never allowed (bearer tokens only).
    """
    headers = dict(existing or {})
    origin = request.headers.get("Origin")
    if origin and origin in get_settings().CORS_ALLOW_ORIGINS_LIST:
        headers.setdefault("Access-Control-Allow-Origin", origin)
        vary = headers.get("Vary")
        if not vary:
            headers["Vary"] = "Origin"
        elif "origin" not in {item.strip().lower() for item in vary.split(",")}:
            headers["Vary"] = f"{vary}, Origin"
    return headers or None


def error_envelope(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
    details: list[dict] | None = None,
) -> JSONResponse:
    errors: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        errors["details"] = details
    return JSONResponse(
        status_code=status_code,
        headers=error_response_headers(request, headers),
        content={"success": False, "data": None, "meta": error_meta(request), "errors": errors},
    )


async def jwt_error_handler(request: Request, exc: JWTError):
    """Return 401 on JWT errors with the same code as every other 401 path."""
    return error_envelope(
        request, status.HTTP_401_UNAUTHORIZED, _http_error_code(401), "Invalid or expired token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Wrap all HTTPException responses in the canonical API envelope (API_STANDARD.md §2).

    This overrides FastAPI's default handler that returns {"detail": "..."} and
    ensures every HTTP error (401, 403, 404, 409, 429, ...) carries:
        { success: false, data: null, meta: {...}, errors: {code, message} }
    """
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code", _http_error_code(exc.status_code))
        message = detail.get("message", str(detail))
    else:
        code = _http_error_code(exc.status_code)
        message = str(detail) if detail else "An error occurred."
    return error_envelope(request, exc.status_code, code, message, headers=getattr(exc, "headers", None))


# Reviewed static public guidance from Telemetry, Report and Organization schemas.
# Exact type/message lookup only: never prefix-match, interpolate ctx/input/loc,
# or return an arbitrary validator's text. New messages need explicit review here.
_SAFE_VALIDATION_MESSAGES = {
    ("value_error", f"Value error, {message}"): f"Value error, {message}"
    for message in (
        "start_time must be before end_time (exclusive)",
        "aggregation requires a metric",
        "flow_* aggregation is unavailable: snapshot v1 has no durable flow match identity; use raw history",
        "aggregation requires start_time, end_time and bucket_seconds",
        "aggregation time range must not exceed seven days",
        "bucket_seconds requires aggregation",
        "cursor mode requires raw history and page=1",
        "cursor requires pagination=cursor",
        "date_range must be increasing and at most 31 days; end is exclusive",
        "date_range cannot extend into the future",
        "duplicate source IDs",
        "simulation_ids require a simulation or summary report",
        "intent_ids require an intent or summary report",
        "metric requires a telemetry or summary report",
        "alert filters require an alerts or summary report",
        "Supply at least one field; name cannot be null.",
        "Slug must be 3-63 characters, lowercase alphanumeric and hyphens only, and must not start or end with a hyphen.",
    )
}


def _safe_validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    first = errors[0] if errors else None
    if isinstance(first, dict):
        error_type, message = first.get("type"), first.get("msg")
        if isinstance(error_type, str) and isinstance(message, str):
            return _SAFE_VALIDATION_MESSAGES.get((error_type, message), "Request validation failed.")
    return "Request validation failed."


def _model_names(annotation: Any, seen: set) -> set[str]:
    names: set[str] = set()
    if get_origin(annotation) is not None:
        for argument in get_args(annotation):
            names |= _model_names(argument, seen)
    elif isinstance(annotation, type) and issubclass(annotation, BaseModel) and annotation not in seen:
        seen.add(annotation)
        for name, field in annotation.model_fields.items():
            names.add(name)
            for alias in (field.alias, field.validation_alias):
                if isinstance(alias, str):
                    names.add(alias)
            names |= _model_names(field.annotation, seen)
    return names


def _route_schema_names(route: Any) -> frozenset[str]:
    """Names declared by the matched route's parameters and body models (cached)."""
    cached = getattr(route, "_nanfo_schema_names", None)
    if cached is not None:
        return cached
    names: set[str] = set()
    seen: set = set()
    pending = [getattr(route, "dependant", None)]
    visited: set[int] = set()
    while pending:
        dependant = pending.pop()
        if dependant is None or id(dependant) in visited:
            continue
        visited.add(id(dependant))
        for group in ("path_params", "query_params", "header_params", "cookie_params", "body_params"):
            for field in getattr(dependant, group, ()):
                names.update(item for item in (getattr(field, "name", None), getattr(field, "alias", None))
                             if isinstance(item, str))
                info = getattr(field, "field_info", None)
                names |= _model_names(getattr(info, "annotation", None), seen)
        pending.extend(getattr(dependant, "dependencies", ()))
    result = frozenset(names)
    try:
        route._nanfo_schema_names = result
    except AttributeError:
        pass
    return result


def _validation_details(request: Request, exc: RequestValidationError) -> list[dict]:
    """[{loc, type}] only. Loc names not declared by the route schema are masked:
    extra/dict keys are client-controlled and may themselves be secrets."""
    route = request.scope.get("route")
    declared = _route_schema_names(route) if route is not None else frozenset()
    details = []
    for error in exc.errors()[:MAX_VALIDATION_DETAILS]:
        if not isinstance(error, dict):
            continue
        raw_type = error.get("type")
        error_type = raw_type if isinstance(raw_type, str) and _ERROR_TYPE.fullmatch(raw_type) else "invalid"
        location: list = []
        raw_loc = error.get("loc")
        for index, part in enumerate(raw_loc if isinstance(raw_loc, (list, tuple)) else ()):
            if isinstance(part, bool):
                location.append("*")
            elif isinstance(part, int):
                location.append(part)
            elif isinstance(part, str) and ((index == 0 and part in _PARAMETER_SOURCES) or part in declared):
                location.append(part)
            else:
                location.append("*")
        details.append({"loc": location, "type": error_type})
    return details


async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return canonical validation error envelope for body/query/path validation failures."""
    # Validator messages/context can interpolate raw passwords, tokens or payloads.
    return error_envelope(
        request, 422, "VALIDATION_ERROR", _safe_validation_message(exc),
        details=_validation_details(request, exc),
    )


async def dependency_unavailable_handler(request: Request, exc: Exception):
    """503 + Retry-After for backing-service outages; the dependency is logged, not returned."""
    retry_after = exc.retry_after_seconds if isinstance(exc, DependencyUnavailableError) else DEFAULT_RETRY_AFTER_SECONDS
    meta = error_meta(request)
    logger.warning("dependency_unavailable", dependency=dependency_name(exc) or "unknown",
                   error_type=type(exc).__name__, path=request.scope.get("path", ""), request_id=meta["request_id"])
    return error_envelope(
        request, status.HTTP_503_SERVICE_UNAVAILABLE, "DEPENDENCY_UNAVAILABLE",
        "A required service is temporarily unavailable. Retry later.",
        headers={"Retry-After": str(retry_after)},
    )


async def request_too_large_handler(request: Request, exc: RequestTooLargeError):
    return error_envelope(
        request, 413, "REQUEST_TOO_LARGE",
        "Request body exceeds the limit for this route.",
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    """Final mapping for anything that escaped route-level handlers.

    Also the RequestContextMiddleware error handler, so middleware-raised outages
    and oversize errors keep their specific status. Never leaks exception text.
    """
    if isinstance(exc, RequestTooLargeError):
        return await request_too_large_handler(request, exc)
    if dependency_name(exc) is not None:
        return await dependency_unavailable_handler(request, exc)
    if isinstance(exc, JWTError):
        return await jwt_error_handler(request, exc)
    if isinstance(exc, StarletteHTTPException):
        return await http_exception_handler(request, exc)
    meta = error_meta(request)
    logger.error("unhandled_exception", path=request.scope.get("path", ""), method=request.scope.get("method", ""),
                 error_type=type(exc).__name__, request_id=meta["request_id"],
                 request_timestamp=meta["timestamp"], exc_info=exc)
    return error_envelope(
        request, status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "An unexpected error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    from neo4j.exceptions import ServiceUnavailable, SessionExpired
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError
    from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    app.add_exception_handler(JWTError, jwt_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(RequestTooLargeError, request_too_large_handler)
    for outage in (DependencyUnavailableError, RedisConnectionError, RedisTimeoutError, OperationalError,
                   InterfaceError, PoolTimeoutError, ServiceUnavailable, SessionExpired):
        app.add_exception_handler(outage, dependency_unavailable_handler)
    # Invalidated connections surface as a plain DBAPIError; the generic path decides.
    app.add_exception_handler(DBAPIError, unhandled_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
