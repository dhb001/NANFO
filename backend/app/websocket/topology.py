"""Registered topology delta channel.

Credentials arrive as the ``nanfo.bearer.<token>`` subprotocol (or the legacy
``?token=`` query value); see app.websocket.endpoint.
"""

from fastapi import APIRouter, WebSocket

from app.websocket.endpoint import serve
from app.websocket.manager import topology_ws_manager

router = APIRouter()


@router.websocket("/ws/topology")
async def topology_websocket(websocket: WebSocket):
    await serve(websocket, channel="topology", manager=topology_ws_manager)
