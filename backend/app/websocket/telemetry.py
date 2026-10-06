"""Registered telemetry delta channel.

Credentials arrive as the ``nanfo.bearer.<token>`` subprotocol (or the legacy
``?token=`` query value); see app.websocket.endpoint.
"""

from fastapi import APIRouter, WebSocket

from app.websocket.endpoint import serve
from app.websocket.manager import telemetry_ws_manager

router = APIRouter()


@router.websocket("/ws/telemetry")
async def telemetry_websocket(websocket: WebSocket):
    await serve(websocket, channel="telemetry", manager=telemetry_ws_manager)
