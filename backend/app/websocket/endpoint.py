"""Subscription lifecycle shared by the four registered channels."""

import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from app.core.logging import get_logger
from app.websocket.auth import authenticate, authorized_workspaces

logger = get_logger(__name__)

class Subscription(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    action: Literal["subscribe"]
    channel: StrictStr
    filters: dict[str, StrictStr] = Field(default_factory=dict)


async def close_denied(websocket: WebSocket, code: str = "WS_UNAUTHORIZED") -> None:
    try:
        await websocket.send_json({
            "event": "error", "data": {"code": code, "message": "Subscription denied."},
        })
    except Exception:  # noqa: BLE001
        logger.debug("ws_denial_frame_unavailable")
    try:
        await websocket.close(code=1008)
    except Exception:  # noqa: BLE001
        logger.debug("ws_denial_close_unavailable")


async def serve(websocket: WebSocket, *, token: str, channel: str, manager) -> None:
    try:
        claims = await authenticate(token, channel)
    except Exception:  # noqa: BLE001
        try:
            await websocket.close(code=1008)
        except Exception:  # noqa: BLE001
            logger.debug("ws_upgrade_denial_close_unavailable")
        return

    await websocket.accept()
    network_id = None
    subscribed = False
    try:
        try:
            frame = Subscription.model_validate_json(await websocket.receive_text())
        except (ValidationError, ValueError):
            await close_denied(websocket, "WS_INVALID_FILTER")
            return
        if frame.channel != channel:
            await close_denied(websocket, "WS_UNKNOWN_CHANNEL")
            return
        if channel != "alerts":
            try:
                if set(frame.filters) != {"network_id"}:
                    raise ValueError("Invalid filters")
                network_id = str(uuid.UUID(frame.filters["network_id"]))
            except (KeyError, ValueError):
                await close_denied(websocket, "WS_INVALID_FILTER")
                return
        elif frame.filters:
            await close_denied(websocket, "WS_INVALID_FILTER")
            return

        try:
            allowed = await authorized_workspaces(token=token, channel=channel, network_id=network_id)
            if not allowed:
                await close_denied(websocket, "WS_INVALID_FILTER")
                return
        except Exception:  # noqa: BLE001
            await close_denied(websocket, "WS_INVALID_FILTER")
            return

        if channel == "alerts":
            await manager.subscribe(
                websocket, token=token, token_exp=claims["exp"], token_jti=claims["jti"],
                allowed_workspace_ids=allowed,
            )
        else:
            await manager.subscribe(
                network_id, websocket, token=token, token_exp=claims["exp"],
                token_jti=claims["jti"], workspace_id=next(iter(allowed)),
            )
        subscribed = True
        await websocket.send_text(json.dumps({
            "event": "subscribed", "channel": channel,
            "filters": {"network_id": network_id} if network_id else {},
            "timestamp": datetime.now(UTC).isoformat(),
        }))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        await close_denied(websocket)
    finally:
        if subscribed:
            if channel == "alerts":
                await manager.unsubscribe(websocket)
            else:
                await manager.unsubscribe(network_id, websocket)
