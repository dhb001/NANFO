"""Authenticated, scope-bound raw-history traversal; no authorization cached in tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.telemetry.repository import TelemetryRecordRepository
from app.modules.telemetry.schemas import (
    TelemetryCursorResponse,
    TelemetryHistoryQuery,
    TelemetryRecordResponse,
)

_DOMAIN = b"nanfo/telemetry/history-cursor/v1"
_TTL = timedelta(minutes=15)


class CursorState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1, le=1)
    scope: str = Field(pattern=r"^[0-9a-f]{64}$")
    cutoff: AwareDatetime
    expires: AwareDatetime
    upper_at: AwareDatetime
    upper_id: uuid.UUID
    last_at: AwareDatetime
    last_id: uuid.UUID


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _encode(raw) != value:
        raise ValueError("noncanonical token")
    return raw


class HistoryCursorCodec:
    def __init__(self, secret: str):
        self._key = hmac.digest(secret.encode(), _DOMAIN, "sha256")

    def encode(self, state: CursorState) -> str:
        body = _encode(state.model_dump_json().encode())
        signature = hmac.digest(self._key, _DOMAIN + b"\0" + body.encode(), "sha256")
        return body + "." + _encode(signature)

    def decode(self, token: str, *, scope: str, now: datetime) -> CursorState:
        try:
            if len(token) > 4096:
                raise ValueError("oversized token")
            body, signature = token.split(".")
            expected = hmac.digest(self._key, _DOMAIN + b"\0" + body.encode("ascii"), "sha256")
            if not hmac.compare_digest(expected, _decode(signature)):
                raise ValueError("bad signature")
            state = CursorState.model_validate_json(_decode(body))
            if (
                not hmac.compare_digest(state.scope, scope)
                or state.expires <= now
                or state.cutoff > now
                or state.expires != state.cutoff + _TTL
                or (state.last_at, state.last_id) > (state.upper_at, state.upper_id)
            ):
                raise ValueError("invalid scope or bounds")
            return state
        except (ValueError, TypeError, UnicodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid or expired telemetry cursor.") from exc


class TelemetryCursorService:
    """Separate read-side owner keeps the existing collector service untouched."""

    def __init__(self, db: AsyncSession):
        self._repo = TelemetryRecordRepository(db)
        self._codec = HistoryCursorCodec(get_settings().JWT_SECRET_KEY)

    async def get_history(
        self, *, actor_id: uuid.UUID, workspace_id: uuid.UUID,
        network_id: uuid.UUID | None, query: TelemetryHistoryQuery,
        page_size: int, cursor: str | None,
    ) -> TelemetryCursorResponse:
        if workspace_id is None or not 1 <= page_size <= 200 or query.aggregation is not None:
            raise ValueError("cursor requires workspace-scoped bounded raw history")
        scope = hashlib.sha256(json.dumps({
            "endpoint": "telemetry/history/raw/v1", "actor": str(actor_id),
            "workspace": str(workspace_id), "network": str(network_id),
            "query": query.model_dump(mode="json"), "page_size": page_size,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        now = datetime.now(UTC)
        state = self._codec.decode(cursor, scope=scope, now=now) if cursor is not None else None
        cutoff = state.cutoff if state else now
        rows = await self._repo.list_history_keyset(
            workspace_id=workspace_id, network_id=network_id, query=query,
            page_size=page_size, cutoff=cutoff,
            upper=(state.upper_at, state.upper_id) if state else None,
            after=(state.last_at, state.last_id) if state else None,
        )
        upper = (state.upper_at, state.upper_id) if state else (
            (rows[0].observed_at, rows[0].record_id) if rows else None
        )
        items = rows[:page_size]
        next_cursor = None
        if len(rows) > page_size:
            next_cursor = self._codec.encode(CursorState(
                scope=scope, cutoff=cutoff, expires=state.expires if state else cutoff + _TTL,
                upper_at=upper[0], upper_id=upper[1],
                last_at=items[-1].observed_at, last_id=items[-1].record_id,
            ))
        return TelemetryCursorResponse(
            items=[TelemetryRecordResponse.model_validate(row) for row in items],
            page_size=page_size, next_cursor=next_cursor,
            upper_observed_at=upper[0] if upper else None,
            upper_record_id=upper[1] if upper else None,
        )
