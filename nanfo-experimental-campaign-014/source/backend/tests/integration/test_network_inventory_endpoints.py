"""Authenticated ADR026 inventory routes and canonical validation responses."""
# ruff: noqa: F811 -- pytest fixture imports are injected by parameter name

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.network.schemas import DeviceResponse, NetworkResponse
from tests.auth_support import create_session_access_token
from tests.integration.test_network_endpoints import (  # noqa: F401
    client,
    headers,
    token,
)

NETWORK, DEVICE = uuid.UUID(int=1), uuid.UUID(int=2)
BASE = f"/api/v1/networks/{NETWORK}"


@pytest.mark.parametrize("url,payload", [
    (BASE, {}), (BASE, {"name": None}), (BASE, {"name": "  "}),
    (BASE, {"name": "n" * 254}), (BASE, {"cidr": "not-a-cidr"}),
    (BASE, {"cidr": "10.0.0.1/24"}), (BASE, {"workspace_id": str(uuid.UUID(int=99))}),
    (f"{BASE}/devices/{DEVICE}", {}),
    (f"{BASE}/devices/{DEVICE}", {"ip_address": "invalid"}),
    (f"{BASE}/devices/{DEVICE}", {"device_type": " "}),
    (f"{BASE}/devices/{DEVICE}", {"device_type": None}),
])
def test_patch_validation_before_service(client, headers, url, payload):
    response = client.patch(url, json=payload, headers=headers)
    assert response.status_code == 422
    assert response.json()["success"] is False


@pytest.mark.parametrize("url", ["/api/v1/networks", f"{BASE}/devices"])
@pytest.mark.parametrize("query", [{"page": 0}, {"page": -1}, {"page_size": 0},
                                  {"page_size": -1}, {"page_size": 201}, {"page_size": 500}])
def test_paging_validation(client, headers, url, query):
    response = client.get(url, params={"workspace_id": str(uuid.UUID(int=3)), **query}, headers=headers)
    assert response.status_code == 422 and response.json()["success"] is False


def test_network_patch_and_device_full_patch_envelopes(client, headers):
    network = NetworkResponse(network_id=NETWORK, workspace_id=uuid.UUID(int=3), name="Campus",
                              description=None, cidr="2001:db8::/32", created_at=datetime.now(UTC))
    with patch("app.api.v1.networks.NetworkService.update_network", AsyncMock(return_value=network)) as mutation:
        result = client.patch(BASE, json={"name": "Campus", "description": None, "cidr": "2001:db8::/32"}, headers=headers)
        assert result.status_code == 200 and result.json()["data"]["cidr"] == "2001:db8::/32"
        assert mutation.call_args.kwargs["req"].model_fields_set == {"name", "description", "cidr"}
    fields = dict(hostname="ap-42", ip_address="192.0.2.42", device_type="ap", vendor="v", model="m",
                  location_hint=None, spatial_ref_id=None)
    device = DeviceResponse(device_id=DEVICE, network_id=NETWORK, status="active", created_at=datetime.now(UTC), **fields)
    with patch("app.api.v1.networks.DeviceService.update_device_spatial_ref", AsyncMock(return_value=device)) as mutation:
        result = client.patch(f"{BASE}/devices/{DEVICE}", json=fields, headers=headers)
        assert result.status_code == 200 and result.json()["success"] is True
        assert all(result.json()["data"][key] == value for key, value in fields.items())
        assert mutation.call_args.kwargs["req"].model_dump(exclude_unset=True) == fields


@pytest.mark.parametrize("url,service", [(BASE, "NetworkService.delete_network"),
                                       (f"{BASE}/devices/{DEVICE}", "DeviceService.delete_device")])
def test_delete_204_and_write_permission(client, headers, url, service):
    with patch(f"app.api.v1.networks.{service}", new_callable=AsyncMock) as mutation:
        response = client.delete(url, headers=headers)
        assert response.status_code == 204 and response.content == b""
        mutation.assert_awaited_once()
        read_token, _ = create_session_access_token(user_id=str(uuid.uuid4()), email="read@example.test",
                                                   roles=["Read-Only"], permissions=["read:topology", "read:telemetry"])
        denied = client.delete(url, headers={"Authorization": f"Bearer {read_token}"})
        assert denied.status_code == 403
        assert mutation.await_count == 1
