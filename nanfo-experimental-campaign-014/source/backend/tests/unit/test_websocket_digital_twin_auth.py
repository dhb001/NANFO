"""Digital twin security observability failures must never bypass denial."""

from unittest.mock import AsyncMock, patch

from app.websocket.manager import DigitalTwinWSManager
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414


async def test_expired_token_denial_survives_counter_failure(ws_identity):
    manager, ws = DigitalTwinWSManager(), AsyncMock()
    await manager.subscribe(ws_identity.network_id, ws, token=ws_identity.token, token_exp=1)
    with patch("app.websocket.manager.get_redis_client", side_effect=RuntimeError("unavailable")):
        await manager.push_delta(
            network_id=ws_identity.network_id, event_type="simulation.started", delta_type="update",
            scene_object={"id": "state"}, correlation_id="correlation", timestamp="timestamp",
        )
    ws.close.assert_awaited_once_with(code=1008)
    assert "WS_UNAUTHORIZED" in ws.send_text.await_args.args[0]
