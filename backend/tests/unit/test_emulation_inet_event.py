"""INET values returned by asyncpg must remain JSON-safe on device events."""

import json
import uuid
from datetime import UTC, datetime
from ipaddress import IPv4Address
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.network.schemas import CreateDeviceRequest
from app.modules.network.service import DeviceService


@pytest.mark.parametrize("address", [IPv4Address("10.77.0.1"), None])
async def test_host_add_publishes_json_safe_inet(address):
    network_id, workspace_id, device_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    device = SimpleNamespace(device_id=device_id, network_id=network_id, hostname="h1",
        ip_address=address, device_type="lab_endpoint", vendor=None, model=None,
        location_hint=None, spatial_ref_id=None, status="active", created_at=datetime.now(UTC))
    service = DeviceService(AsyncMock(), AsyncMock())
    with (
        patch.object(service, "_assert_network_workspace_access", new=AsyncMock(
            return_value=SimpleNamespace(workspace_id=workspace_id))),
        patch.object(service._repo, "create", new=AsyncMock(return_value=device)),
        patch("app.modules.network.service.publish_event", new_callable=AsyncMock) as publish,
    ):
        await service.add_device(network_id, CreateDeviceRequest(hostname="h1", device_type="lab_endpoint"),
                                 str(uuid.uuid4()), str(uuid.uuid4()))
    payload = publish.await_args.kwargs["payload"]
    assert json.loads(json.dumps(payload))["ip_address"] == (str(address) if address else None)
