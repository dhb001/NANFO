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
from app.websocket.auth import authorized_workspaces
from app.websocket.delivery import ConnectionDelivery, DeliveryDenied, DeliveryLimits, PendingDelta

logger = get_logger(__name__)

_DIGITAL_TWIN_WS_SECURITY_CLOSE_COUNTER_PREFIX = "digital_twin:ws:security_close"

_WS_UNAUTHORIZED_FRAME = json.dumps({
    "event": "error",
    "data": {
        "code": "WS_UNAUTHORIZED",
        "message": "Token expired. Reconnect with a valid token.",
    },
})

_WS_BACKPRESSURE_FRAME = json.dumps({
    "event": "error",
    "data": {
        "code": "WS_BACKPRESSURE",
        "message": "Delta queue capacity exceeded. Reconnect and re-fetch full state from REST endpoint.",
    },
})


@dataclass
class _ConnectionAuth:
    token_exp: int | None
    token_jti: str | None
    workspace_id: str | None = None
    allowed_workspace_ids: frozenset[str] | None = None
    token: str | None = None
    channel: str = ""
    network_id: str | None = None


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
        return True
    return int(datetime.now(UTC).timestamp()) >= auth.token_exp


async def _is_token_revoked(auth: _ConnectionAuth | None) -> bool:
    if auth is None or not auth.token:
        return True
    try:
        allowed = await authorized_workspaces(
            token=auth.token, channel=auth.channel, network_id=auth.network_id,
        )
        if not allowed or (auth.workspace_id is not None and auth.workspace_id not in allowed):
            return True
        auth.allowed_workspace_ids = frozenset(allowed)
        return False
    except Exception:  # noqa: BLE001
        logger.warning("ws_authorization_revalidation_failed", channel=auth.channel)
        return True


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


class _QueuedManager:
    """Connection-local transport; channel envelopes and authorization stay here."""

    def __init__(self, *, delivery_limits: DeliveryLimits | None = None):
        self._subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._subscribers: set[WebSocket] = set()
        self._connection_auth: dict[WebSocket, _ConnectionAuth] = {}
        self._deliveries: dict[WebSocket, ConnectionDelivery] = {}
        self._delivery_limits = delivery_limits or DeliveryLimits()
        self._lock = asyncio.Lock()
        self._realtime_available = True  # Legacy singleton requires no fanout.

    async def set_realtime_available(self, available: bool) -> None:
        async with self._lock:
            self._realtime_available = available
            if not available:
                for ws in list(self._connection_auth):
                    self._delivery(ws).invalidate()

    def _check_realtime(self, ws: WebSocket) -> None:
        if not self._realtime_available:
            self._delivery(ws).invalidate()

    async def stop_realtime(self) -> None:
        """Drain terminal writers before the application closes auth/Redis clients."""
        await self.set_realtime_available(False)
        tasks = [delivery.task for delivery in self._deliveries.values() if delivery.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _forget(self, ws: WebSocket, delivery: ConnectionDelivery) -> None:
        if self._deliveries.get(ws) is not delivery:
            return
        self._deliveries.pop(ws, None)
        self._connection_auth.pop(ws, None)
        self._subscribers.discard(ws)
        for network_id, sockets in list(self._subscriptions.items()):
            sockets.discard(ws)
            if not sockets:
                del self._subscriptions[network_id]

    async def _close(self, ws: WebSocket, frame: str, code: int) -> None:
        # Independent deadlines ensure a blocked error frame cannot prevent close.
        for operation in (lambda: ws.send_text(frame), lambda: ws.close(code=code)):
            try:
                async with asyncio.timeout(self._delivery_limits.timeout_seconds):
                    await operation()
            except Exception:  # noqa: BLE001
                logger.debug("ws_terminal_transport_failed", close_code=code)

    async def _authorize(self, auth: _ConnectionAuth) -> None:
        reason = "expired" if _is_token_expired(auth) else None
        if reason is None and await _is_token_revoked(auth):
            reason = "revoked"
        # Authorization may have awaited external services across token expiry.
        if reason is None and _is_token_expired(auth):
            reason = "expired"
        if reason is None:
            return
        raise DeliveryDenied(reason)

    def _delivery(self, ws: WebSocket) -> ConnectionDelivery:
        existing = self._deliveries.get(ws)
        if existing is not None:
            return existing
        auth = self._connection_auth[ws]

        async def denied(reason: str) -> None:
            await self._close(ws, _WS_UNAUTHORIZED_FRAME, 1008)
            if auth.channel == "digital-twin":
                try:
                    async with asyncio.timeout(self._delivery_limits.timeout_seconds):
                        await _record_security_close_reason(reason=reason, network_id=auth.network_id)
                except TimeoutError:
                    logger.debug("ws_security_counter_timeout", channel=auth.channel)

        async def deliver(delta: PendingDelta) -> bool:
            await self._authorize(auth)
            if self._connection_auth.get(ws) is not auth:
                return False
            if auth.channel == "alerts":
                # Revalidation refreshes the current membership set, not login claims.
                if delta.workspace_id is None or delta.workspace_id not in (auth.allowed_workspace_ids or ()):
                    return True
            elif delta.workspace_id is not None and auth.workspace_id != delta.workspace_id:
                return True
            await ws.send_text(delta.message)
            return True

        async def backpressure() -> None:
            logger.warning("ws_delivery_backpressure", channel=auth.channel, network_id=auth.network_id)
            try:
                async with asyncio.timeout(self._delivery_limits.timeout_seconds):
                    await self._authorize(auth)
            except DeliveryDenied as exc:
                await denied(str(exc))
                return
            except TimeoutError:
                # Auth unavailability cannot grant delivery, including queued deltas.
                await self._close(ws, _WS_UNAUTHORIZED_FRAME, 1008)
                return
            await self._close(ws, _WS_BACKPRESSURE_FRAME, 1013)

        delivery = ConnectionDelivery(
            self._delivery_limits, deliver, backpressure, denied,
            lambda: self._forget(ws, delivery),
        )
        self._deliveries[ws] = delivery
        return delivery

    async def _enqueue(self, network_id: str | None, message: str, workspace_id: str | None) -> None:
        delta = PendingDelta(message, _coerce_workspace_id(workspace_id), network_id, len(message.encode("utf-8")))
        async with self._lock:
            targets = self._subscribers if network_id is None else self._subscriptions.get(network_id, ())
            for ws in targets:
                if network_id is None:
                    auth = self._connection_auth.get(ws)
                    # Routing only: foreign/unscoped events must not consume this
                    # tenant's queue. Dequeue still revalidates current authority.
                    if auth is None or delta.workspace_id not in (auth.allowed_workspace_ids or ()):
                        continue
                self._delivery(ws).enqueue(delta)
        # Give ready writers a turn without waiting for slow sockets or auth services.
        await asyncio.sleep(0)

    async def _unsubscribe(self, websocket: WebSocket, network_id: str | None = None) -> None:
        delivery = None
        async with self._lock:
            if network_id is None:
                self._subscribers.discard(websocket)
            else:
                sockets = self._subscriptions.get(network_id)
                if sockets is not None:
                    sockets.discard(websocket)
                    if not sockets:
                        del self._subscriptions[network_id]
            if not any(websocket in sockets for sockets in self._subscriptions.values()):
                self._connection_auth.pop(websocket, None)
                delivery = self._deliveries.pop(websocket, None)
            elif network_id is not None and websocket in self._deliveries:
                self._deliveries[websocket].discard_network(network_id)
        if delivery is not None:
            await delivery.stop()


class TopologyWSManager(_QueuedManager):
    """Manages active WebSocket connections subscribed to topology deltas."""

    async def subscribe(
        self,
        network_id: str,
        websocket: WebSocket,
        *,
        token_exp: int | None = None,
        token_jti: str | None = None,
        workspace_id: str | None = None,
        token: str | None = None,
    ) -> None:
        async with self._lock:
            self._subscriptions[network_id].add(websocket)
            self._connection_auth[websocket] = _ConnectionAuth(
                token_exp=_coerce_token_exp(token_exp),
                token_jti=_coerce_token_jti(token_jti),
                workspace_id=_coerce_workspace_id(workspace_id),
                token=token, channel="topology", network_id=network_id,
            )
            self._check_realtime(websocket)
        logger.info("ws_subscribed", network_id=network_id)

    async def unsubscribe(self, network_id: str, websocket: WebSocket) -> None:
        await self._unsubscribe(websocket, network_id)
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
        Identity, session, capability and membership are rechecked before delivery.
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

        await self._enqueue(network_id, message, workspace_id)


class TelemetryWSManager(_QueuedManager):
    """Manages active WebSocket connections subscribed to telemetry deltas."""

    async def subscribe(
        self,
        network_id: str,
        websocket: WebSocket,
        *,
        token_exp: int | None = None,
        token_jti: str | None = None,
        workspace_id: str | None = None,
        token: str | None = None,
    ) -> None:
        async with self._lock:
            self._subscriptions[network_id].add(websocket)
            self._connection_auth[websocket] = _ConnectionAuth(
                token_exp=_coerce_token_exp(token_exp),
                token_jti=_coerce_token_jti(token_jti),
                workspace_id=_coerce_workspace_id(workspace_id),
                token=token, channel="telemetry", network_id=network_id,
            )
            self._check_realtime(websocket)
        logger.info("ws_telemetry_subscribed", network_id=network_id)

    async def unsubscribe(self, network_id: str, websocket: WebSocket) -> None:
        await self._unsubscribe(websocket, network_id)
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

        await self._enqueue(network_id, message, workspace_id)


class DigitalTwinWSManager(_QueuedManager):
    """Manages active WebSocket connections subscribed to digital twin deltas."""

    async def subscribe(
        self,
        network_id: str,
        websocket: WebSocket,
        *,
        token_exp: int | None = None,
        token_jti: str | None = None,
        workspace_id: str | None = None,
        token: str | None = None,
    ) -> None:
        async with self._lock:
            self._subscriptions[network_id].add(websocket)
            self._connection_auth[websocket] = _ConnectionAuth(
                token_exp=_coerce_token_exp(token_exp),
                token_jti=_coerce_token_jti(token_jti),
                workspace_id=_coerce_workspace_id(workspace_id),
                token=token, channel="digital-twin", network_id=network_id,
            )
            self._check_realtime(websocket)
        logger.info("ws_digital_twin_subscribed", network_id=network_id)

    async def unsubscribe(self, network_id: str, websocket: WebSocket) -> None:
        await self._unsubscribe(websocket, network_id)
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

        await self._enqueue(network_id, message, workspace_id)


class AlertsWSManager(_QueuedManager):
    """Manages active WebSocket connections subscribed to alert deltas."""

    async def subscribe(
        self,
        websocket: WebSocket,
        *,
        token_exp: int | None = None,
        token_jti: str | None = None,
        allowed_workspace_ids: set[str] | None = None,
        token: str | None = None,
    ) -> None:
        auth = _ConnectionAuth(
            token_exp=_coerce_token_exp(token_exp),
            token_jti=_coerce_token_jti(token_jti),
            allowed_workspace_ids=_coerce_allowed_workspace_ids(allowed_workspace_ids),
            token=token, channel="alerts",
        )
        # The endpoint supplies validated scopes. Direct manager callers that
        # omit them must resolve them once before becoming routing candidates.
        if auth.allowed_workspace_ids is None:
            try:
                async with asyncio.timeout(self._delivery_limits.timeout_seconds):
                    await self._authorize(auth)
            except (DeliveryDenied, TimeoutError):
                await self._close(websocket, _WS_UNAUTHORIZED_FRAME, 1008)
                return
        async with self._lock:
            self._subscribers.add(websocket)
            self._connection_auth[websocket] = auth
            self._check_realtime(websocket)
        logger.info("ws_alerts_subscribed")

    async def unsubscribe(self, websocket: WebSocket) -> None:
        await self._unsubscribe(websocket)
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

        await self._enqueue(None, message, workspace_id)


# Singleton managers — shared across the application
topology_ws_manager = TopologyWSManager()
telemetry_ws_manager = TelemetryWSManager()
digital_twin_ws_manager = DigitalTwinWSManager()
alerts_ws_manager = AlertsWSManager()
