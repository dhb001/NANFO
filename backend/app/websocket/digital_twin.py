"""NANFO Backend - /ws/digital-twin WebSocket endpoint.

Implements WebSocket.md §2 (JWT auth), §3 (subscription protocol), and
digital twin scene delta delivery over /ws/digital-twin.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError

from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.redis import get_redis_client
from app.websocket.manager import digital_twin_ws_manager

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
    "data": {
        "code": "WS_INVALID_FILTER",
        "message": "network_id filter is required for digital-twin channel.",
    },
})


@router.websocket("/ws/digital-twin")
async def digital_twin_websocket(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    """WebSocket endpoint for real-time digital twin scene deltas (/ws/digital-twin)."""
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
    logger.info("ws_digital_twin_connected", user_id=claims.get("sub"))

    network_id: str | None = None

    try:
        raw = await websocket.receive_text()
        frame = json.loads(raw)

        channel = frame.get("channel", "")
        if channel != "digital-twin":
            await websocket.send_text(_UNKNOWN_CHANNEL_FRAME)
            await websocket.close()
            return

        filters = frame.get("filters", {})
        network_id = filters.get("network_id")
        if not network_id:
            await websocket.send_text(_INVALID_FILTER_FRAME)
            await websocket.close()
            return

        ack = json.dumps({
            "event": "subscribed",
            "channel": "digital-twin",
            "filters": {"network_id": network_id},
            "timestamp": datetime.now(UTC).isoformat(),
        })
        await websocket.send_text(ack)

        await digital_twin_ws_manager.subscribe(network_id, websocket)

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info("ws_digital_twin_disconnected", user_id=claims.get("sub"), network_id=network_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("ws_digital_twin_error", error=str(exc))
        try:
            await websocket.send_text(_UNAUTHORIZED_FRAME)
            await websocket.close()
        except Exception:  # noqa: BLE001
            logger.debug("ws_digital_twin_error_frame_send_failed")
    finally:
        if network_id:
            await digital_twin_ws_manager.unsubscribe(network_id, websocket)
