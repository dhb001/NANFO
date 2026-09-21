"""Registered topology delta channel."""

from fastapi import APIRouter, Query, WebSocket

from app.websocket.endpoint import serve
from app.websocket.manager import topology_ws_manager

router = APIRouter()


@router.websocket("/ws/topology")
async def topology_websocket(websocket: WebSocket, token: str = Query("")):
    await serve(websocket, token=token, channel="topology", manager=topology_ws_manager)
