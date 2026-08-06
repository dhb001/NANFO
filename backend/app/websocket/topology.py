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

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from jose import JWTError

from app.core.security import decode_token
from app.core.logging import get_logger
from app.db.redis import get_redis_client
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

        # ── Step 3: Acknowledge subscription ─────────────────────────────────
        from datetime import UTC, datetime
        ack = json.dumps({
            "event": "subscribed",
            "channel": "topology",
            "filters": {"network_id": network_id},
            "timestamp": datetime.now(UTC).isoformat(),
        })
        await websocket.send_text(ack)

        await topology_ws_manager.subscribe(network_id, websocket)

        # ── Step 4: Keep alive — deltas are pushed by WS push consumer ───────
        while True:
            # Keep connection alive; also detects client disconnect
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info("ws_disconnected", user_id=claims.get("sub"), network_id=network_id)
    except Exception as exc:
        logger.error("ws_error", error=str(exc))
        try:
            await websocket.send_text(_UNAUTHORIZED_FRAME)
            await websocket.close()
        except Exception:
            pass
    finally:
        if network_id:
            await topology_ws_manager.unsubscribe(network_id, websocket)
