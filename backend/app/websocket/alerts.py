"""NANFO Backend - /ws/alerts WebSocket endpoint.

Implements WebSocket.md §2 (JWT auth), §3 (subscription protocol), and
alert delta delivery over /ws/alerts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError

from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.redis import get_redis_client
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
