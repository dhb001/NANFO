"""Registered digital twin scene delta channel.

Credentials arrive as the ``nanfo.bearer.<token>`` subprotocol (or the legacy
``?token=`` query value); see app.websocket.endpoint.
"""

from fastapi import APIRouter, WebSocket

from app.websocket.endpoint import serve
from app.websocket.manager import digital_twin_ws_manager

router = APIRouter()


@router.websocket("/ws/digital-twin")
async def digital_twin_websocket(websocket: WebSocket):
    await serve(websocket, channel="digital-twin", manager=digital_twin_ws_manager)
