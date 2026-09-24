"""Subscription lifecycle shared by the four registered channels (ADR-028 C1).

1. Credentials: ``nanfo.bearer.<jwt>`` subprotocol (select ``nanfo.v1``) or legacy
   ``?token=``. Missing/invalid/unauthorised -> close 1008 before accept.
2. Authenticate exactly once; the claims are reused for subscription authorization
   and seed the manager's per-connection authorization cache.
3. Backing-service outage during auth/subscribe -> accept, ``WS_UNAVAILABLE``, 1013.
4. Per-user socket cap -> ``WS_CONNECTION_LIMIT``, 1008.
5. No subscribe frame within ``WS_SUBSCRIBE_TIMEOUT_SECONDS`` -> ``WS_SUBSCRIBE_TIMEOUT``, 1013.
6. Inbound frames above ``WS_MAX_FRAME_BYTES`` -> close 1009.
7. Token expiry closes even idle sockets with ``WS_UNAUTHORIZED``, 1008.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from app.core.config import get_settings
from app.core.failures import dependency_name
from app.core.logging import get_logger
from app.websocket.auth import Credentials, authenticate, authorize_claims, read_credentials
from app.websocket.limits import connection_registry

logger = get_logger(__name__)

MESSAGE_TOO_BIG = 1009
POLICY_VIOLATION = 1008
TRY_AGAIN_LATER = 1013
INTERNAL_ERROR = 1011
_MESSAGES = {
    "WS_UNAVAILABLE": "Realtime temporarily unavailable.",
    "WS_SUBSCRIBE_TIMEOUT": "No subscribe frame received in time.",
    "WS_CONNECTION_LIMIT": "Too many concurrent realtime connections.",
    "WS_UNAUTHORIZED": "Token expired. Reconnect with a valid token.",
}


class Subscription(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    action: Literal["subscribe"]
    channel: StrictStr
    filters: dict[str, StrictStr] = Field(default_factory=dict)


def _is_outage(exc: BaseException) -> bool:
    return dependency_name(exc) is not None or isinstance(exc, TimeoutError)


async def send_terminal(websocket: WebSocket, code: str, close_code: int) -> None:
    """Best-effort error frame, then close; neither step may raise."""
    try:
        await websocket.send_json({
            "event": "error", "data": {"code": code, "message": _MESSAGES.get(code, "Subscription denied.")},
        })
    except Exception:  # noqa: BLE001
        logger.debug("ws_denial_frame_unavailable")
    await _close(websocket, close_code)


async def close_denied(websocket: WebSocket, code: str = "WS_UNAUTHORIZED") -> None:
    await send_terminal(websocket, code, POLICY_VIOLATION)


async def _close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except Exception:  # noqa: BLE001
        logger.debug("ws_close_unavailable", close_code=code)


async def _accept(websocket: WebSocket, credentials: Credentials) -> bool:
    try:
        # Only ever the fixed protocol name; the bearer entry is never echoed.
        await websocket.accept(subprotocol=credentials.subprotocol)
        return True
    except Exception:  # noqa: BLE001
        logger.debug("ws_accept_unavailable")
        return False


async def _receive(websocket: WebSocket, *, deadline: float, max_bytes: int) -> tuple[str, str | None]:
    """One inbound message: text | bytes | oversize | disconnect | timeout."""
    try:
        async with asyncio.timeout(max(0.0, deadline - time.monotonic())):
            message = await websocket.receive()
    except TimeoutError:
        return "timeout", None
    if message["type"] == "websocket.disconnect":
        return "disconnect", None
    text, data = message.get("text"), message.get("bytes")
    size = len(text.encode("utf-8")) if text is not None else len(data or b"")
    if size > max_bytes:
        return "oversize", None
    return ("text", text) if text is not None else ("bytes", None)


async def _unsubscribe(manager, channel: str, websocket: WebSocket, network_id: str | None) -> None:
    if channel == "alerts":
        await manager.unsubscribe(websocket)
    else:
        await manager.unsubscribe(network_id, websocket)


async def serve(websocket: WebSocket, *, channel: str, manager, token: str | None = None) -> None:
    settings = get_settings()
    credentials = read_credentials(websocket, legacy_token=token)
    if not credentials.valid or not credentials.token:
        await _close(websocket, POLICY_VIOLATION)
        return
    try:
        claims = await authenticate(credentials.token, channel)
    except Exception as exc:  # noqa: BLE001 - classified; never echoed
        if _is_outage(exc):
            logger.warning("ws_auth_unavailable", channel=channel, error_type=type(exc).__name__)
            if await _accept(websocket, credentials):
                await send_terminal(websocket, "WS_UNAVAILABLE", TRY_AGAIN_LATER)
            return
        await _close(websocket, POLICY_VIOLATION)
        return
    user_id = str(claims.get("sub", ""))
    if not connection_registry.acquire(user_id, settings.WS_MAX_CONNECTIONS_PER_USER):
        logger.warning("ws_connection_limit", channel=channel)
        if await _accept(websocket, credentials):
            await send_terminal(websocket, "WS_CONNECTION_LIMIT", POLICY_VIOLATION)
        return
    try:
        if await _accept(websocket, credentials):
            await _session(websocket, claims=claims, token=credentials.token, channel=channel,
                           manager=manager, settings=settings)
    finally:
        connection_registry.release(user_id)


async def _session(websocket: WebSocket, *, claims: dict, token: str, channel: str, manager, settings) -> None:
    started = time.monotonic()
    expiry_deadline = started + max(0.0, float(claims["exp"]) - time.time())
    subscribe_deadline = min(started + settings.WS_SUBSCRIBE_TIMEOUT_SECONDS, expiry_deadline)
    max_bytes = settings.WS_MAX_FRAME_BYTES
    network_id = None
    subscribed = False
    try:
        kind, text = await _receive(websocket, deadline=subscribe_deadline, max_bytes=max_bytes)
        if kind == "disconnect":
            return
        if kind == "timeout":
            if time.monotonic() >= expiry_deadline:
                await send_terminal(websocket, "WS_UNAUTHORIZED", POLICY_VIOLATION)
            else:
                await send_terminal(websocket, "WS_SUBSCRIBE_TIMEOUT", TRY_AGAIN_LATER)
            return
        if kind == "oversize":
            await _close(websocket, MESSAGE_TOO_BIG)
            return
        try:
            if kind != "text":
                raise ValueError("Subscribe frames are JSON text")
            frame = Subscription.model_validate_json(text)
        except (ValidationError, ValueError):
            await close_denied(websocket, "WS_INVALID_FILTER")
            return
        if frame.channel != channel:
            await close_denied(websocket, "WS_UNKNOWN_CHANNEL")
            return
        if channel != "alerts":
            try:
                if set(frame.filters) != {"network_id"}:
                    raise ValueError("Invalid filters")
                network_id = str(uuid.UUID(frame.filters["network_id"]))
            except (KeyError, ValueError):
                await close_denied(websocket, "WS_INVALID_FILTER")
                return
        elif frame.filters:
            await close_denied(websocket, "WS_INVALID_FILTER")
            return

        try:
            allowed = await authorize_claims(claims=claims, channel=channel, network_id=network_id)
        except Exception as exc:  # noqa: BLE001 - classified; never echoed
            if _is_outage(exc):
                logger.warning("ws_subscribe_unavailable", channel=channel, error_type=type(exc).__name__)
                await send_terminal(websocket, "WS_UNAVAILABLE", TRY_AGAIN_LATER)
            elif isinstance(exc, (HTTPException, ValueError, TypeError, LookupError)):
                await close_denied(websocket, "WS_INVALID_FILTER")
            else:
                logger.error("ws_subscribe_failed", channel=channel, error_type=type(exc).__name__, exc_info=exc)
                await send_terminal(websocket, "WS_UNAVAILABLE", INTERNAL_ERROR)
            return
        if not allowed:
            await close_denied(websocket, "WS_INVALID_FILTER")
            return
        now = time.monotonic()
        if now >= expiry_deadline:
            await send_terminal(websocket, "WS_UNAUTHORIZED", POLICY_VIOLATION)
            return
        # Seed the per-connection cache with this connect-time decision (C1).
        authorized_until = now + min(settings.WS_AUTH_CACHE_SECONDS, expiry_deadline - now)
        if channel == "alerts":
            await manager.subscribe(
                websocket, token=token, token_exp=claims["exp"], token_jti=claims["jti"],
                allowed_workspace_ids=allowed, authorized_until=authorized_until,
            )
        else:
            await manager.subscribe(
                network_id, websocket, token=token, token_exp=claims["exp"],
                token_jti=claims["jti"], workspace_id=next(iter(allowed)), authorized_until=authorized_until,
            )
        subscribed = True
        await websocket.send_text(json.dumps({
            "event": "subscribed", "channel": channel,
            "filters": {"network_id": network_id} if network_id else {},
            "timestamp": datetime.now(UTC).isoformat(),
        }))
        while True:
            kind, _ = await _receive(websocket, deadline=expiry_deadline, max_bytes=max_bytes)
            if kind == "disconnect":
                return
            if kind == "oversize":
                await _close(websocket, MESSAGE_TOO_BIG)
                return
            if kind == "timeout":
                # Idle channels too: stop the single writer first, then close.
                await _unsubscribe(manager, channel, websocket, network_id)
                subscribed = False
                await send_terminal(websocket, "WS_UNAUTHORIZED", POLICY_VIOLATION)
                return
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws_session_failed", channel=channel, error_type=type(exc).__name__)
        await close_denied(websocket)
    finally:
        if subscribed:
            await _unsubscribe(manager, channel, websocket, network_id)
