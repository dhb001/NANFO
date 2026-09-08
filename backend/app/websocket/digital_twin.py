"""Registered digital twin scene delta channel."""

from fastapi import APIRouter, Query, WebSocket

from app.websocket.endpoint import serve
from app.websocket.manager import digital_twin_ws_manager

router = APIRouter()


@router.websocket("/ws/digital-twin")
async def digital_twin_websocket(websocket: WebSocket, token: str = Query("")):
    await serve(websocket, token=token, channel="digital-twin", manager=digital_twin_ws_manager)
