"""NANFO Backend — WebSocket connection managers for realtime channels.

Manages channel subscriptions and delta push semantics.
Per WebSocket.md §4: delta payloads only — never full state snapshots.
Per WebSocket.md §2: JWT re-validated before every push.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import WebSocket

from app.core.logging import get_logger
from app.db.redis import get_redis_client

logger = get_logger(__name__)

_DIGITAL_TWIN_WS_SECURITY_CLOSE_COUNTER_PREFIX = "digital_twin:ws:security_close"

_WS_UNAUTHORIZED_FRAME = json.dumps({
    "event": "error",
    "data": {
        "code": "WS_UNAUTHORIZED",
        "message": "Token expired. Reconnect with a valid token.",
    },
})


@dataclass(frozen=True)
class _ConnectionAuth:
    token_exp: int | None
    token_jti: str | None
    workspace_id: str | None = None
    allowed_workspace_ids: frozenset[str] | None = None


def _coerce_token_exp(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_token_jti(value: object) -> str | None:
    if value is None:
        return None
    token_jti = str(value).strip()
    return token_jti or None


def _coerce_workspace_id(value: object) -> str | None:
    if value is None:
        return None
    workspace_id = str(value).strip()
    return workspace_id or None


def _coerce_allowed_workspace_ids(value: object) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, (set, frozenset, list, tuple)):
        return frozenset()

    normalized = {
        workspace_id
        for item in value
        if (workspace_id := _coerce_workspace_id(item)) is not None
    }
    return frozenset(normalized)


def _is_token_expired(auth: _ConnectionAuth | None) -> bool:
    if auth is None or auth.token_exp is None:
        return False
    return int(datetime.now(UTC).timestamp()) >= auth.token_exp


async def _is_token_revoked(auth: _ConnectionAuth | None) -> bool:
    if auth is None or auth.token_jti is None:
        return False

    try:
        redis = get_redis_client()
    except RuntimeError as exc:
        logger.warning(
            "ws_digital_twin_denylist_client_unavailable",
            jti=auth.token_jti,
            error=str(exc),
        )
        return False

    try:
        return bool(await redis.exists(f"jti:deny:{auth.token_jti}"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ws_digital_twin_denylist_check_failed",
            jti=auth.token_jti,
            error=str(exc),
        )
        return False


async def _record_security_close_reason(*, reason: str, network_id: str) -> None:
    counter_key = f"{_DIGITAL_TWIN_WS_SECURITY_CLOSE_COUNTER_PREFIX}:{reason}"

    try:
        redis = get_redis_client()
    except RuntimeError as exc:
        logger.warning(
            "ws_digital_twin_security_close_counter_client_unavailable",
            reason=reason,
            network_id=network_id,
            error=str(exc),
        )
        return

    try:
        await redis.incr(counter_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ws_digital_twin_security_close_counter_increment_failed",
            reason=reason,
            network_id=network_id,
            counter_key=counter_key,
            error=str(exc),
        )
        return

    logger.info(
        "ws_digital_twin_security_close_reason_recorded",
        reason=reason,
        network_id=network_id,
        counter_key=counter_key,
    )


class TopologyWSManager:
    """Manages active WebSocket connections subscribed to topology deltas."""

    def __init__(self):
        # network_id → set of WebSocket connections
        self._subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._connection_auth: dict[WebSocket, _ConnectionAuth] = {}
        self._lock = asyncio.Lock()

    async def subscribe(
        self,
        network_id: str,
        websocket: WebSocket,
        *,
        token_exp: int | None = None,
        token_jti: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        async with self._lock:
            self._subscriptions[network_id].add(websocket)
            self._connection_auth[websocket] = _ConnectionAuth(
                token_exp=_coerce_token_exp(token_exp),
                token_jti=_coerce_token_jti(token_jti),
                workspace_id=_coerce_workspace_id(workspace_id),
            )
        logger.info("ws_subscribed", network_id=network_id)

    async def unsubscribe(self, network_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscriptions[network_id].discard(websocket)
            if not self._subscriptions[network_id]:
                del self._subscriptions[network_id]
            has_other_subscriptions = any(
                websocket in sockets for sockets in self._subscriptions.values()
            )
            if not has_other_subscriptions:
                self._connection_auth.pop(websocket, None)
        logger.info("ws_unsubscribed", network_id=network_id)

    async def push_delta(
        self,
        network_id: str,
        event_type: str,
        delta_type: str,
        node: dict,
        correlation_id: str,
        timestamp: str,
        workspace_id: str | None = None,
    ) -> None:
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

        event_workspace_id = _coerce_workspace_id(workspace_id)
        dead_connections: list[tuple[str, WebSocket]] = []
        async with self._lock:
            targets = {
                ws: self._connection_auth.get(ws)
                for ws in self._subscriptions.get(network_id, set())
            }

        for ws, auth in targets.items():
            if (
                event_workspace_id is not None
                and auth is not None
                and auth.workspace_id is not None
                and auth.workspace_id != event_workspace_id
            ):
                continue

            if _is_token_expired(auth) or await _is_token_revoked(auth):
                try:
                    await ws.send_text(_WS_UNAUTHORIZED_FRAME)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "ws_topology_unauthorized_frame_send_failed",
                        network_id=network_id,
                        error=str(exc),
                    )
                try:
                    await ws.close(code=1008)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "ws_topology_unauthorized_connection_close_failed",
                        network_id=network_id,
                        error=str(exc),
                    )
                dead_connections.append((network_id, ws))
                continue

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
        self._connection_auth: dict[WebSocket, _ConnectionAuth] = {}
        self._lock = asyncio.Lock()

    async def subscribe(
        self,
        network_id: str,
        websocket: WebSocket,
        *,
        token_exp: int | None = None,
        token_jti: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        async with self._lock:
            self._subscriptions[network_id].add(websocket)
            self._connection_auth[websocket] = _ConnectionAuth(
                token_exp=_coerce_token_exp(token_exp),
                token_jti=_coerce_token_jti(token_jti),
                workspace_id=_coerce_workspace_id(workspace_id),
            )
        logger.info("ws_telemetry_subscribed", network_id=network_id)

    async def unsubscribe(self, network_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscriptions[network_id].discard(websocket)
            if not self._subscriptions[network_id]:
                del self._subscriptions[network_id]
            has_other_subscriptions = any(
                websocket in sockets for sockets in self._subscriptions.values()
            )
            if not has_other_subscriptions:
                self._connection_auth.pop(websocket, None)
        logger.info("ws_telemetry_unsubscribed", network_id=network_id)

    async def push_delta(
        self,
        network_id: str,
        event_type: str,
        metric: dict,
        correlation_id: str,
        timestamp: str,
        workspace_id: str | None = None,
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

        event_workspace_id = _coerce_workspace_id(workspace_id)
        dead_connections: list[tuple[str, WebSocket]] = []
        async with self._lock:
            targets = {
                ws: self._connection_auth.get(ws)
                for ws in self._subscriptions.get(network_id, set())
            }

        for ws, auth in targets.items():
            if (
                event_workspace_id is not None
                and auth is not None
                and auth.workspace_id is not None
                and auth.workspace_id != event_workspace_id
            ):
                continue

            if _is_token_expired(auth) or await _is_token_revoked(auth):
                try:
                    await ws.send_text(_WS_UNAUTHORIZED_FRAME)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "ws_telemetry_unauthorized_frame_send_failed",
                        network_id=network_id,
                        error=str(exc),
                    )
                try:
                    await ws.close(code=1008)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "ws_telemetry_unauthorized_connection_close_failed",
                        network_id=network_id,
                        error=str(exc),
                    )
                dead_connections.append((network_id, ws))
                continue

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
        self._connection_auth: dict[WebSocket, _ConnectionAuth] = {}
        self._lock = asyncio.Lock()

    async def subscribe(
        self,
        network_id: str,
        websocket: WebSocket,
        *,
        token_exp: int | None = None,
        token_jti: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        async with self._lock:
            self._subscriptions[network_id].add(websocket)
            self._connection_auth[websocket] = _ConnectionAuth(
                token_exp=_coerce_token_exp(token_exp),
                token_jti=_coerce_token_jti(token_jti),
                workspace_id=_coerce_workspace_id(workspace_id),
            )
        logger.info("ws_digital_twin_subscribed", network_id=network_id)

    async def unsubscribe(self, network_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscriptions[network_id].discard(websocket)
            if not self._subscriptions[network_id]:
                del self._subscriptions[network_id]
            has_other_subscriptions = any(
                websocket in sockets for sockets in self._subscriptions.values()
            )
            if not has_other_subscriptions:
                self._connection_auth.pop(websocket, None)
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
        workspace_id: str | None = None,
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

        event_workspace_id = _coerce_workspace_id(workspace_id)
        dead_connections: list[tuple[str, WebSocket]] = []
        async with self._lock:
            targets = {
                ws: self._connection_auth.get(ws)
                for ws in self._subscriptions.get(network_id, set())
            }

        for ws, auth in targets.items():
            if (
                event_workspace_id is not None
                and auth is not None
                and auth.workspace_id is not None
                and auth.workspace_id != event_workspace_id
            ):
                continue

            if _is_token_expired(auth):
                await _record_security_close_reason(
                    reason="expired",
                    network_id=network_id,
                )
                try:
                    await ws.send_text(_WS_UNAUTHORIZED_FRAME)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "ws_digital_twin_unauthorized_frame_send_failed",
                        network_id=network_id,
                        error=str(exc),
                    )
                try:
                    await ws.close(code=1008)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "ws_digital_twin_expired_connection_close_failed",
                        network_id=network_id,
                        error=str(exc),
                    )
                dead_connections.append((network_id, ws))
                continue

            if await _is_token_revoked(auth):
                await _record_security_close_reason(
                    reason="revoked",
                    network_id=network_id,
                )
                try:
                    await ws.send_text(_WS_UNAUTHORIZED_FRAME)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "ws_digital_twin_unauthorized_frame_send_failed",
                        network_id=network_id,
                        error=str(exc),
                    )
                try:
                    await ws.close(code=1008)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "ws_digital_twin_revoked_connection_close_failed",
                        network_id=network_id,
                        error=str(exc),
                    )
                dead_connections.append((network_id, ws))
                continue

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
        self._connection_auth: dict[WebSocket, _ConnectionAuth] = {}
        self._lock = asyncio.Lock()

    async def subscribe(
        self,
        websocket: WebSocket,
        *,
        token_exp: int | None = None,
        token_jti: str | None = None,
        allowed_workspace_ids: set[str] | None = None,
    ) -> None:
        async with self._lock:
            self._subscribers.add(websocket)
            self._connection_auth[websocket] = _ConnectionAuth(
                token_exp=_coerce_token_exp(token_exp),
                token_jti=_coerce_token_jti(token_jti),
                allowed_workspace_ids=_coerce_allowed_workspace_ids(allowed_workspace_ids),
            )
        logger.info("ws_alerts_subscribed")

    async def unsubscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscribers.discard(websocket)
            if websocket not in self._subscribers:
                self._connection_auth.pop(websocket, None)
        logger.info("ws_alerts_unsubscribed")

    async def push_delta(
        self,
        *,
        event_type: str,
        delta_type: str,
        alert: dict,
        correlation_id: str,
        timestamp: str,
        workspace_id: str | None = None,
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
            targets = {
                ws: self._connection_auth.get(ws)
                for ws in self._subscribers
            }

        event_workspace_id = _coerce_workspace_id(workspace_id)

        for ws, auth in targets.items():
            if (
                event_workspace_id is not None
                and auth is not None
                and auth.allowed_workspace_ids is not None
                and event_workspace_id not in auth.allowed_workspace_ids
            ):
                continue

            if _is_token_expired(auth) or await _is_token_revoked(auth):
                try:
                    await ws.send_text(_WS_UNAUTHORIZED_FRAME)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("ws_alerts_unauthorized_frame_send_failed", error=str(exc))
                try:
                    await ws.close(code=1008)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("ws_alerts_unauthorized_connection_close_failed", error=str(exc))
                dead_connections.append(ws)
                continue

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
