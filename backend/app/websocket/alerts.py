"""NANFO Backend - /ws/alerts WebSocket endpoint.

Implements WebSocket.md §2 (JWT auth), §3 (subscription protocol), and
alert delta delivery over /ws/alerts.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.postgres import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.modules.organization.service import WorkspaceService
from app.websocket.manager import alerts_ws_manager

logger = get_logger(__name__)

router = APIRouter()

_UNAUTHORIZED_FRAME = json.dumps({
    "event": "error",
    "data": {"code": "WS_UNAUTHORIZED", "message": "Token expired. Reconnect with a valid token."},
})

_UNKNOWN_CHANNEL_FRAME = json.dumps({
    "event": "error",
    "data": {"code": "WS_UNKNOWN_CHANNEL", "message": "Channel not registered."},
})

_FORBIDDEN_FILTER_FRAME = json.dumps({
    "event": "error",
    "data": {"code": "WS_INVALID_FILTER", "message": "Unauthorized workspace scope for alerts channel."},
})


async def _resolve_alert_subscription_workspaces(
    *,
    db: AsyncSession,
    claims: dict,
) -> set[str] | None:
    claim_workspace_id = claims.get("workspace_id")
    if claim_workspace_id is not None:
        try:
            parsed_workspace_id = uuid.UUID(str(claim_workspace_id))
        except (TypeError, ValueError, AttributeError):
            return None

        claim_org_id = claims.get("org_id")
        parsed_claim_org_id: uuid.UUID | None = None
        if claim_org_id is not None:
            try:
                parsed_claim_org_id = uuid.UUID(str(claim_org_id))
            except (TypeError, ValueError, AttributeError):
                return None

        user_id_raw = claims.get("sub")
        try:
            user_id = str(uuid.UUID(str(user_id_raw)))
        except (TypeError, ValueError, AttributeError):
            return None

        try:
            workspace = await WorkspaceService(db=db, redis=get_redis_client()).get_active_workspace(
                parsed_workspace_id,
                user_id=user_id,
                claim_org_id=parsed_claim_org_id,
            )
        except Exception:  # noqa: BLE001
            return None
        return {str(workspace.workspace_id)}

    return None


@router.websocket("/ws/alerts")
async def alerts_websocket(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    """WebSocket endpoint for real-time alert lifecycle deltas (/ws/alerts)."""
    try:
        claims = decode_token(token)
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    jti = claims.get("jti", "")
    redis = get_redis_client()
    if jti and await redis.exists(f"jti:deny:{jti}"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    logger.info("ws_alerts_connected", user_id=claims.get("sub"))

    subscribed = False

    try:
        raw = await websocket.receive_text()
        frame = json.loads(raw)

        channel = frame.get("channel", "")
        if channel != "alerts":
            await websocket.send_text(_UNKNOWN_CHANNEL_FRAME)
            await websocket.close()
            return

        async with AsyncSessionLocal() as db:
            allowed_workspace_ids = await _resolve_alert_subscription_workspaces(
                db=db,
                claims=claims,
            )

        claim_workspace_id = claims.get("workspace_id")
        if claim_workspace_id is not None and (allowed_workspace_ids is None or not allowed_workspace_ids):
            await websocket.send_text(_FORBIDDEN_FILTER_FRAME)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        ack = json.dumps({
            "event": "subscribed",
            "channel": "alerts",
            "filters": {},
            "timestamp": datetime.now(UTC).isoformat(),
        })
        await websocket.send_text(ack)

        await alerts_ws_manager.subscribe(
            websocket,
            token_exp=claims.get("exp"),
            token_jti=claims.get("jti"),
            allowed_workspace_ids=allowed_workspace_ids,
        )
        subscribed = True

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info("ws_alerts_disconnected", user_id=claims.get("sub"))
    except Exception as exc:  # noqa: BLE001
        logger.error("ws_alerts_error", error=str(exc))
        try:
            await websocket.send_text(_UNAUTHORIZED_FRAME)
            await websocket.close()
        except Exception:  # noqa: BLE001
            logger.debug("ws_alerts_error_frame_send_failed")
    finally:
        if subscribed:
            await alerts_ws_manager.unsubscribe(websocket)
