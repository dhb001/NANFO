"""Digital twin subscription rechecks membership after connection upgrade."""

from fastapi.testclient import TestClient

from tests.integration.test_topology_ws_endpoint import app
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414


async def test_membership_removed_after_upgrade(ws_identity):
    state = ws_identity
    with TestClient(app) as client, client.websocket_connect(f"/ws/digital-twin?token={state.token}") as ws:
        state.memberships.clear()
        ws.send_json({"action": "subscribe", "channel": "digital-twin",
                      "filters": {"network_id": state.network_id}})
        assert ws.receive_json()["data"]["code"] == "WS_INVALID_FILTER"
