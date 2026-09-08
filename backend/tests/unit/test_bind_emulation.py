"""Operator binder uses returned API IDs and never persists credentials."""

import json
import uuid

import httpx
import pytest

from scripts.bind_emulation import bind_emulation, save_binding


async def test_binder_bootstraps_then_reuses_returned_inventory(tmp_path, capsys):
    actor, org, workspace, network = [str(uuid.uuid4()) for _ in range(4)]
    dpid = "0000000000000001"
    devices = []
    created = []
    logged_out = []

    def respond(request):
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path == "/api/v1/auth/login":
            assert body == {"email": "operator@example.test", "password": "private-password"}
            data = {"access_token": "private-token", "refresh_token": "private-refresh"}
        else:
            assert request.headers["Authorization"] == "Bearer private-token"
            if path == "/api/v1/auth/me":
                data = {"user_id": actor, "permissions": ["write:config", "read:topology"]}
            elif path == "/api/v1/organizations":
                item = {"org_id": org, "slug": "lab"}
                data = {"items": [item] if "org" in created else [], "total": int("org" in created)}
                if request.method == "POST":
                    created.append("org")
                    data = item
            elif path == f"/api/v1/organizations/{org}/workspaces":
                item = {"workspace_id": workspace, "name": "lab"}
                data = {"items": [item] if "workspace" in created else [], "total": int("workspace" in created)}
                if request.method == "POST":
                    created.append("workspace")
                    data = item
            elif path == "/api/v1/networks":
                item = {"network_id": network, "workspace_id": workspace, "name": "lab"}
                data = {"items": [item] if "network" in created else [], "total": int("network" in created)}
                if request.method == "POST":
                    created.append("network")
                    data = item
            elif path == f"/api/v1/networks/{network}/devices":
                if request.method == "POST":
                    data = {**body, "device_id": str(uuid.uuid4()), "network_id": network, "status": "active"}
                    devices.append(data)
                else:
                    # Exercise multi-page inventory retrieval on the second bind.
                    page = int(request.url.params["page"])
                    data = {"items": devices[page - 1:page], "total": len(devices)}
            elif path == "/api/v1/auth/logout":
                logged_out.append(True)
                data = {}
            else:
                pytest.fail(f"Unapproved API call: {path}")
        return httpx.Response(200, json={"success": True, "data": data})

    manifest = {"topology_id": "campus-small-v1", "switches": [{"name": "core", "dpid": dpid}],
                "hosts": [{"name": "h1", "ipv4": "10.77.0.1"}],
                "port_capacities_mbps": {f"{dpid}:1": 100}}
    async with httpx.AsyncClient(base_url="http://localhost", transport=httpx.MockTransport(respond)) as client:
        kwargs = {"email": "operator@example.test", "password": "private-password", "manifest": manifest,
                  "org_slug": "lab", "workspace_name": "lab", "network_name": "lab"}
        first = await bind_emulation(client, **kwargs)
        second = await bind_emulation(client, **kwargs)
        assert "Authorization" not in client.headers
    assert first == second
    assert len(devices) == 2 and len(logged_out) == 2
    assert str(first.switches[dpid]) == devices[0]["device_id"]
    assert str(first.hosts["h1"]) == devices[1]["device_id"]
    assert str(first.actor_user_id) == actor
    output = tmp_path / "binding.json"
    save_binding(first, output, tmp_path / "producer" / "snapshot.json")
    assert output.stat().st_mode & 0o777 == 0o600
    assert "private-" not in output.read_text()
    assert "private-" not in capsys.readouterr().out
    with pytest.raises(ValueError):
        save_binding(first, output, tmp_path / "snapshot.json")


async def test_binder_does_not_expose_api_error_body():
    async with httpx.AsyncClient(base_url="http://localhost", transport=httpx.MockTransport(
        lambda request: httpx.Response(401, text="private-password private-token")
    )) as client:
        with pytest.raises(ValueError, match="HTTP 401") as error:
            await bind_emulation(client, email="x", password="private-password", manifest={},
                                 org_slug="lab", workspace_name="lab", network_name="lab")
    assert "private-" not in str(error.value)
