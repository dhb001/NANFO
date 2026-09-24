"""Registered alerts delta channel. No global subscriptions.

Credentials arrive as the ``nanfo.bearer.<token>`` subprotocol (or the legacy
``?token=`` query value); see app.websocket.endpoint.
"""

from fastapi import APIRouter, WebSocket

from app.websocket.endpoint import serve
from app.websocket.manager import alerts_ws_manager

router = APIRouter()


@router.websocket("/ws/alerts")
async def alerts_websocket(websocket: WebSocket):
    await serve(websocket, channel="alerts", manager=alerts_ws_manager)
