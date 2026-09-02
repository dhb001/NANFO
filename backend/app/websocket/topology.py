"""NANFO Backend — /ws/topology WebSocket endpoint.

Implements WebSocket.md §2 (JWT auth), §3 (subscription protocol), §4 (delta payloads).
Connection lifecycle:
  1. JWT validated on upgrade (HTTP 401 on failure — WebSocket.md §2)
  2. Client sends subscribe frame with network_id filter
  3. Server acknowledges subscription
  4. Server pushes topology deltas from TopologyWSManager
  5. JWT expiry check on disconnect / error → WS_UNAUTHORIZED error frame + close
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.postgres import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.modules.network.service import NetworkService
from app.websocket.manager import topology_ws_manager

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
    "data": {"code": "WS_INVALID_FILTER", "message": "network_id filter is required for topology channel."},
})

_FORBIDDEN_FILTER_FRAME = json.dumps({
    "event": "error",
    "data": {"code": "WS_INVALID_FILTER", "message": "Unauthorized network scope for topology channel."},
})

_WS_ERROR_CODE = 1011


async def _resolve_topology_subscription_scope(
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


@router.websocket("/ws/topology")
async def topology_websocket(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    """WebSocket endpoint for real-time topology deltas (/ws/topology).

    JWT provided as query param per WebSocket.md §2.
    Channel: topology | Required filter: network_id.
    Delta payload format: WebSocket.md §4.1.
    """
    # ── Step 1: Validate JWT before accepting upgrade ─────────────────────────
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
    logger.info("ws_connected", user_id=claims.get("sub"))

    network_id: str | None = None

    try:
        # ── Step 2: Wait for subscribe frame ─────────────────────────────────
        raw = await websocket.receive_text()
        frame = json.loads(raw)

        channel = frame.get("channel", "")
        if channel != "topology":
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
            scope = await _resolve_topology_subscription_scope(
                db=db,
                claims=claims,
                network_id=network_id,
            )

        if scope is None:
            await websocket.send_text(_FORBIDDEN_FILTER_FRAME)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        network_id, workspace_id = scope

        # ── Step 3: Acknowledge subscription ─────────────────────────────────
        from datetime import UTC, datetime
        ack = json.dumps({
            "event": "subscribed",
            "channel": "topology",
            "filters": {"network_id": network_id},
            "timestamp": datetime.now(UTC).isoformat(),
        })
        await websocket.send_text(ack)

        await topology_ws_manager.subscribe(
            network_id,
            websocket,
            token_exp=claims.get("exp"),
            token_jti=claims.get("jti"),
            workspace_id=workspace_id,
        )

        # ── Step 4: Keep alive — deltas are pushed by WS push consumer ───────
        while True:
            # Keep connection alive; also detects client disconnect
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info("ws_disconnected", user_id=claims.get("sub"), network_id=network_id)
    except (ValueError, RuntimeError, OSError, TypeError) as exc:
        logger.error("ws_error", error=str(exc))
        try:
            await websocket.send_text(_UNAUTHORIZED_FRAME)
            await websocket.close(code=_WS_ERROR_CODE)
        except (RuntimeError, OSError, TypeError) as close_exc:
            logger.debug("ws_error_frame_send_failed", error=str(close_exc))
    finally:
        if network_id:
            await topology_ws_manager.unsubscribe(network_id, websocket)
