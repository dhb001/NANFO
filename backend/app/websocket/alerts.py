"""Registered alerts delta channel. No global subscriptions."""

from fastapi import APIRouter, Query, WebSocket

from app.websocket.endpoint import serve
from app.websocket.manager import alerts_ws_manager

router = APIRouter()


@router.websocket("/ws/alerts")
async def alerts_websocket(websocket: WebSocket, token: str = Query("")):
    await serve(websocket, token=token, channel="alerts", manager=alerts_ws_manager)
