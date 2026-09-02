"""NANFO Backend - /ws/telemetry WebSocket endpoint.

Implements WebSocket.md §2 (JWT auth), §3 (subscription protocol), and
telemetry delta delivery over /ws/telemetry.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.postgres import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.modules.network.service import NetworkService
from app.websocket.manager import telemetry_ws_manager

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

_INVALID_FILTER_FRAME = json.dumps({
    "event": "error",
    "data": {"code": "WS_INVALID_FILTER", "message": "network_id filter is required for telemetry channel."},
})

_FORBIDDEN_FILTER_FRAME = json.dumps({
    "event": "error",
    "data": {"code": "WS_INVALID_FILTER", "message": "Unauthorized network scope for telemetry channel."},
})


async def _resolve_telemetry_subscription_scope(
    *,
    db: AsyncSession,
    claims: dict,
    network_id: str,
) -> tuple[str, str] | None:
    try:
        parsed_network_id = uuid.UUID(str(network_id))
    except (TypeError, ValueError, AttributeError):
        return None

    claim_workspace_id = claims.get("workspace_id")
    requested_workspace_id: uuid.UUID | None = None
    if claim_workspace_id is not None:
        try:
            requested_workspace_id = uuid.UUID(str(claim_workspace_id))
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
        network = await NetworkService(db=db, redis=get_redis_client()).assert_network_workspace_access(
            network_id=parsed_network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=user_id,
            claim_org_id=parsed_claim_org_id,
        )
    except HTTPException:
        return None

    return str(network.network_id), str(network.workspace_id)


@router.websocket("/ws/telemetry")
async def telemetry_websocket(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    """WebSocket endpoint for real-time telemetry metric deltas (/ws/telemetry)."""
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
    logger.info("ws_telemetry_connected", user_id=claims.get("sub"))

    network_id: str | None = None

    try:
        raw = await websocket.receive_text()
        frame = json.loads(raw)

        channel = frame.get("channel", "")
        if channel != "telemetry":
            await websocket.send_text(_UNKNOWN_CHANNEL_FRAME)
            await websocket.close()
            return

        filters = frame.get("filters", {})
        network_id = filters.get("network_id")
        if not network_id:
            await websocket.send_text(_INVALID_FILTER_FRAME)
            await websocket.close()
            return

        async with AsyncSessionLocal() as db:
            scope = await _resolve_telemetry_subscription_scope(
                db=db,
                claims=claims,
                network_id=network_id,
            )

        if scope is None:
            await websocket.send_text(_FORBIDDEN_FILTER_FRAME)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        network_id, workspace_id = scope

        ack = json.dumps({
            "event": "subscribed",
            "channel": "telemetry",
            "filters": {"network_id": network_id},
            "timestamp": datetime.now(UTC).isoformat(),
        })
        await websocket.send_text(ack)

        await telemetry_ws_manager.subscribe(
            network_id,
            websocket,
            token_exp=claims.get("exp"),
            token_jti=claims.get("jti"),
            workspace_id=workspace_id,
        )

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info("ws_telemetry_disconnected", user_id=claims.get("sub"), network_id=network_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("ws_telemetry_error", error=str(exc))
        try:
            await websocket.send_text(_UNAUTHORIZED_FRAME)
            await websocket.close()
        except Exception:  # noqa: BLE001
            logger.debug("ws_telemetry_error_frame_send_failed")
    finally:
        if network_id:
            await telemetry_ws_manager.unsubscribe(network_id, websocket)
