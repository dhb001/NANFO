"""Scoped alert tokens cannot escape their workspace restriction."""

from fastapi.testclient import TestClient

from app.core.security import create_access_token, create_refresh_token, decode_token
from app.modules.identity.sessions import SessionRepository
from app.websocket.auth import authorized_workspaces
from tests.integration.test_topology_ws_endpoint import app
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414


async def test_scoped_alert_subscription(ws_identity):
    state = ws_identity
    scope = {"user_id": str(state.user.user_id), "sid": state.claims["sid"],
             "org_id": state.org_id, "workspace_id": state.workspace_id}
    refresh, _ = create_refresh_token(**scope)
    await SessionRepository(state.redis).revoke(state.claims["sid"])
    await SessionRepository(state.redis).create(decode_token(refresh, token_type="refresh"), refresh)
    token, _ = create_access_token(**scope, email=state.user.email, roles=state.roles, permissions=state.permissions)
    assert await authorized_workspaces(token=token, channel="alerts", network_id=None) == {state.workspace_id}
    with TestClient(app) as client, client.websocket_connect(f"/ws/alerts?token={token}") as ws:
        ws.send_json({"action": "subscribe", "channel": "alerts", "filters": {}})
        assert ws.receive_json()["event"] == "subscribed"
