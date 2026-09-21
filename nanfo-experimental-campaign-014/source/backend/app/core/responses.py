"""NANFO Backend — Canonical API response envelope.

All REST endpoints must return this structure (API_STANDARD.md §2):

Success: { success: true,  data: {...}, meta: {...}, errors: null }
Error:   { success: false, data: null,  meta: {...}, errors: {code, message} }
"""

import time
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from app.core.config import get_settings

T = TypeVar("T")


class ResponseMeta(BaseModel):
    request_id: str
    timestamp: str
    execution_time_ms: int | None = None
    execution_mode: Literal["demo", "emulation", "production"] = Field(
        default_factory=lambda: get_settings().EXECUTION_MODE,
    )


class ErrorDetail(BaseModel):
    code: str
    message: str


class APIResponse(BaseModel, Generic[T]):
    """Canonical NANFO REST response envelope (API_STANDARD.md §2)."""

    success: bool
    data: T | None
    meta: ResponseMeta
    errors: ErrorDetail | None


def success_response(
    data: Any,
    request_id: str,
    started_at: float,
    timestamp: str,
) -> APIResponse:
    """Build a success envelope. execution_time_ms is measured from started_at."""
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    return APIResponse(
        success=True,
        data=data,
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=timestamp,
            execution_time_ms=elapsed_ms,
        ),
        errors=None,
    )


def error_response(
    code: str,
    message: str,
    request_id: str,
    timestamp: str,
) -> APIResponse:
    """Build an error envelope. No execution_time_ms on error responses (API_STANDARD.md §2)."""
    return APIResponse(
        success=False,
        data=None,
        meta=ResponseMeta(request_id=request_id, timestamp=timestamp),
        errors=ErrorDetail(code=code, message=message),
    )
