"""Alert envelope and unknown-workspace denial."""

import json
from unittest.mock import AsyncMock

from app.websocket.manager import AlertsWSManager
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414


async def test_alert_delta_requires_known_authorized_workspace(ws_identity):
    state = ws_identity
    manager, ws = AlertsWSManager(), AsyncMock()
    await manager.subscribe(ws, token=state.token, token_exp=state.claims["exp"])
    kwargs = {"event_type": "alert.generated", "delta_type": "add", "alert": {"event_id": "event"},
              "correlation_id": "correlation", "timestamp": "timestamp"}
    await manager.push_delta(**kwargs)
    ws.send_text.assert_not_awaited()
    await manager.push_delta(workspace_id=state.workspace_id, **kwargs)
    assert json.loads(ws.send_text.await_args.args[0])["data"] == {
        "delta_type": "add", "alert": {"event_id": "event"},
    }
