"""Registered telemetry delta channel."""

from fastapi import APIRouter, Query, WebSocket

from app.websocket.endpoint import serve
from app.websocket.manager import telemetry_ws_manager

router = APIRouter()


@router.websocket("/ws/telemetry")
async def telemetry_websocket(websocket: WebSocket, token: str = Query("")):
    await serve(websocket, token=token, channel="telemetry", manager=telemetry_ws_manager)
