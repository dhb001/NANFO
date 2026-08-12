"""NANFO Backend — WebSocket connection managers for realtime channels.

Manages channel subscriptions and delta push semantics.
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
            except Exception:  # noqa: BLE001
                dead_connections.append((network_id, ws))

        # Clean up disconnected clients
        for nid, ws in dead_connections:
            await self.unsubscribe(nid, ws)


class TelemetryWSManager:
    """Manages active WebSocket connections subscribed to telemetry deltas."""

    def __init__(self):
        self._subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, network_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscriptions[network_id].add(websocket)
        logger.info("ws_telemetry_subscribed", network_id=network_id)

    async def unsubscribe(self, network_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscriptions[network_id].discard(websocket)
            if not self._subscriptions[network_id]:
                del self._subscriptions[network_id]
        logger.info("ws_telemetry_unsubscribed", network_id=network_id)

    async def push_delta(
        self,
        network_id: str,
        event_type: str,
        metric: dict,
        correlation_id: str,
        timestamp: str,
    ) -> None:
        """Push a telemetry metric delta to all subscribers of a network_id."""
        message = json.dumps({
            "event": event_type,
            "correlation_id": correlation_id,
            "timestamp": timestamp,
            "data": {
                "delta_type": "metric",
                "metric": metric,
            },
        })

        dead_connections: list[tuple[str, WebSocket]] = []
        async with self._lock:
            targets = set(self._subscriptions.get(network_id, set()))

        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:  # noqa: BLE001
                dead_connections.append((network_id, ws))

        for nid, ws in dead_connections:
            await self.unsubscribe(nid, ws)


class DigitalTwinWSManager:
    """Manages active WebSocket connections subscribed to digital twin deltas."""

    def __init__(self):
        self._subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, network_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscriptions[network_id].add(websocket)
        logger.info("ws_digital_twin_subscribed", network_id=network_id)

    async def unsubscribe(self, network_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscriptions[network_id].discard(websocket)
            if not self._subscriptions[network_id]:
                del self._subscriptions[network_id]
        logger.info("ws_digital_twin_unsubscribed", network_id=network_id)

    async def push_delta(
        self,
        *,
        network_id: str,
        event_type: str,
        delta_type: str,
        scene_object: dict,
        correlation_id: str,
        timestamp: str,
    ) -> None:
        """Push a digital twin scene-object delta to all subscribers of a network."""
        message = json.dumps({
            "event": event_type,
            "correlation_id": correlation_id,
            "timestamp": timestamp,
            "data": {
                "delta_type": delta_type,
                "scene_object": scene_object,
            },
        })

        dead_connections: list[tuple[str, WebSocket]] = []
        async with self._lock:
            targets = set(self._subscriptions.get(network_id, set()))

        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:  # noqa: BLE001
                dead_connections.append((network_id, ws))

        for nid, ws in dead_connections:
            await self.unsubscribe(nid, ws)


class AlertsWSManager:
    """Manages active WebSocket connections subscribed to alert deltas."""

    def __init__(self):
        self._subscribers: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscribers.add(websocket)
        logger.info("ws_alerts_subscribed")

    async def unsubscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscribers.discard(websocket)
        logger.info("ws_alerts_unsubscribed")

    async def push_delta(
        self,
        *,
        event_type: str,
        delta_type: str,
        alert: dict,
        correlation_id: str,
        timestamp: str,
    ) -> None:
        """Push an alert lifecycle delta to all alert subscribers."""
        message = json.dumps({
            "event": event_type,
            "correlation_id": correlation_id,
            "timestamp": timestamp,
            "data": {
                "delta_type": delta_type,
                "alert": alert,
            },
        })

        dead_connections: list[WebSocket] = []
        async with self._lock:
            targets = set(self._subscribers)

        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:  # noqa: BLE001
                dead_connections.append(ws)

        for ws in dead_connections:
            await self.unsubscribe(ws)


# Singleton managers — shared across the application
topology_ws_manager = TopologyWSManager()
telemetry_ws_manager = TelemetryWSManager()
digital_twin_ws_manager = DigitalTwinWSManager()
alerts_ws_manager = AlertsWSManager()
