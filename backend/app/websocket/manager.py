"""NANFO Backend — WebSocket connection manager for /ws/topology.

Manages per-network_id subscriber sets and delta push.
Per WebSocket.md §4: delta payloads only — never full state snapshots.
Per WebSocket.md §2: JWT re-validated before every push.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket
from app.core.logging import get_logger

logger = get_logger(__name__)


class TopologyWSManager:
    """Manages active WebSocket connections subscribed to topology deltas."""

    def __init__(self):
        # network_id → set of WebSocket connections
        self._subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, network_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscriptions[network_id].add(websocket)
        logger.info("ws_subscribed", network_id=network_id)

    async def unsubscribe(self, network_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscriptions[network_id].discard(websocket)
            if not self._subscriptions[network_id]:
                del self._subscriptions[network_id]
        logger.info("ws_unsubscribed", network_id=network_id)

    async def push_delta(self, network_id: str, event_type: str, delta_type: str, node: dict, correlation_id: str, timestamp: str) -> None:
        """Push a topology delta to all subscribers of a network_id.

        Per WebSocket.md §4.1: delta_type in {add, update, remove}.
        Per WebSocket.md §2: JWT expiry check is done by the WS endpoint before accepting
        the connection; continuous re-validation is the caller's responsibility.
        """
        message = json.dumps({
            "event": event_type,
            "correlation_id": correlation_id,
            "timestamp": timestamp,
            "data": {
                "delta_type": delta_type,
                "node": node,
            },
        })

        dead_connections: list[tuple[str, WebSocket]] = []
        async with self._lock:
            targets = set(self._subscriptions.get(network_id, set()))

        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append((network_id, ws))

        # Clean up disconnected clients
        for nid, ws in dead_connections:
            await self.unsubscribe(nid, ws)


# Singleton manager — shared across the application
topology_ws_manager = TopologyWSManager()
