"""Digital twin delta envelope remains unchanged under strict authorization."""

import json
from unittest.mock import AsyncMock

from app.websocket.manager import DigitalTwinWSManager
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414


async def test_scene_delta_contract(ws_identity):
    state = ws_identity
    manager, ws = DigitalTwinWSManager(), AsyncMock()
    await manager.subscribe(state.network_id, ws, token=state.token, token_exp=state.claims["exp"],
                            workspace_id=state.workspace_id)
    await manager.push_delta(
        network_id=state.network_id, event_type="simulation.started", delta_type="update",
        scene_object={"id": "simulation-state", "state": "queued"},
        correlation_id="correlation", timestamp="timestamp",
    )
    payload = json.loads(ws.send_text.await_args.args[0])
    assert payload["event"] == "simulation.started"
    assert payload["data"] == {"delta_type": "update", "scene_object": {"id": "simulation-state", "state": "queued"}}
