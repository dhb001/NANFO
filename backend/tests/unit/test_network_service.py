"""Unit tests for NetworkService and DeviceService (app/modules/network/service.py).

Key constraint C5: workspace_id validation calls WorkspaceService (not WorkspaceRepository).
Key constraint C6: no deferred topology endpoint methods exist in the service.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.network.models import Device, Network
from app.modules.network.schemas import CreateDeviceRequest, CreateNetworkRequest
from app.modules.network.service import DeviceService, NetworkService
from app.modules.organization.models import Workspace


def _make_network(workspace_id: uuid.UUID | None = None) -> Network:
    n = MagicMock(spec=Network)
    n.network_id = uuid.uuid4()
    n.workspace_id = workspace_id or uuid.uuid4()
    n.name = "Test Network"
    n.description = None
    n.cidr = "10.0.0.0/24"
    n.created_at = MagicMock()
    return n


def _make_device(network_id: uuid.UUID | None = None) -> Device:
    d = MagicMock(spec=Device)
    d.device_id = uuid.uuid4()
    d.network_id = network_id or uuid.uuid4()
    d.hostname = "router-01"
    d.ip_address = "10.0.0.1"
    d.device_type = "router"
    d.vendor = "Cisco"
    d.model = "C9300"
    d.location_hint = None
    d.status = "active"
    d.created_at = MagicMock()
    return d


def _make_workspace() -> Workspace:
    ws = MagicMock(spec=Workspace)
    ws.workspace_id = uuid.uuid4()
    ws.deleted_at = None
    return ws


@pytest.fixture
def net_svc(mock_db, fake_redis) -> NetworkService:
    return NetworkService(db=mock_db, redis=fake_redis)


@pytest.fixture
def dev_svc(mock_db, fake_redis) -> DeviceService:
    return DeviceService(db=mock_db, redis=fake_redis)


class TestNetworkService:

    @pytest.mark.asyncio
    async def test_create_network_success(self, net_svc):
        """C5: workspace validation goes through WorkspaceService.get_active_workspace()."""
        ws = _make_workspace()
        network = _make_network(workspace_id=ws.workspace_id)
        with (
            # Patch the service-layer call — NOT the repository
            patch.object(net_svc._workspace_svc, "get_active_workspace", return_value=ws) as mock_ws,
            patch.object(net_svc._repo, "create", return_value=network),
            patch("app.modules.network.service.publish_event", new_callable=AsyncMock),
        ):
            result = await net_svc.create_network(
                req=CreateNetworkRequest(workspace_id=ws.workspace_id, name="Net1"),
                actor_id="u1",
                correlation_id=str(uuid.uuid4()),
            )
        # Verify C5: the service-layer method was called
        mock_ws.assert_called_once_with(ws.workspace_id)
        assert result.network_id == network.network_id

    @pytest.mark.asyncio
    async def test_create_network_invalid_workspace_raises_404(self, net_svc):
        """C5: 404 from WorkspaceService propagates to the caller."""
        ws_id = uuid.uuid4()
        with patch.object(
            net_svc._workspace_svc,
            "get_active_workspace",
            side_effect=HTTPException(status_code=404, detail="Workspace not found or has been deleted."),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await net_svc.create_network(
                    req=CreateNetworkRequest(workspace_id=ws_id, name="Bad"),
                    actor_id="u1",
                    correlation_id=str(uuid.uuid4()),
                )
        assert exc_info.value.status_code == 404

    def test_c5_no_workspace_repository_direct_call(self, net_svc):
        """C5: NetworkService must hold a WorkspaceService reference, not a WorkspaceRepository."""
        # The _workspace_svc attribute exists and is an OrgWorkspaceService
        from app.modules.organization.service import WorkspaceService as OrgWS
        assert hasattr(net_svc, "_workspace_svc")
        assert isinstance(net_svc._workspace_svc, OrgWS)
        # Must NOT have a _workspace_repo attribute
        assert not hasattr(net_svc, "_workspace_repo")

    def test_c6_no_deferred_topology_methods(self, net_svc):
        """C6: deferred topology endpoint methods must not exist in NetworkService."""
        for forbidden_method in ("get_neighbors", "get_impact", "reconcile"):
            assert not hasattr(net_svc, forbidden_method), (
                f"Deferred method '{forbidden_method}' found in NetworkService — violates C6"
            )


class TestDeviceService:

    @pytest.mark.asyncio
    async def test_add_device_success_publishes_event(self, dev_svc):
        """Adding a device must publish network.device.added to the event bus."""
        network = _make_network()
        device = _make_device(network_id=network.network_id)
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch.object(dev_svc._repo, "create", return_value=device),
            patch("app.modules.network.service.publish_event", new_callable=AsyncMock) as mock_pub,
        ):
            result = await dev_svc.add_device(
                network_id=network.network_id,
                req=CreateDeviceRequest(hostname="router-01", device_type="router"),
                actor_id="u1",
                correlation_id=str(uuid.uuid4()),
            )
        # Event must be published
        mock_pub.assert_called_once()
        call_kwargs = mock_pub.call_args.kwargs
        assert call_kwargs["event_type"] == "network.device.added"
        assert result.device_id == device.device_id

    @pytest.mark.asyncio
    async def test_add_device_to_unknown_network_raises_404(self, dev_svc):
        with patch.object(dev_svc._network_repo, "get_by_id", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await dev_svc.add_device(
                    network_id=uuid.uuid4(),
                    req=CreateDeviceRequest(hostname="h", device_type="switch"),
                    actor_id="u1",
                    correlation_id=str(uuid.uuid4()),
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_add_device_event_type_follows_naming_convention(self, dev_svc):
        """EventAPI.md §1: event_type must follow module.entity.action pattern."""
        network = _make_network()
        device = _make_device(network_id=network.network_id)
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch.object(dev_svc._repo, "create", return_value=device),
            patch("app.modules.network.service.publish_event", new_callable=AsyncMock) as mock_pub,
        ):
            await dev_svc.add_device(
                network_id=network.network_id,
                req=CreateDeviceRequest(hostname="h", device_type="switch"),
                actor_id="u1",
                correlation_id=str(uuid.uuid4()),
            )
        event_type = mock_pub.call_args.kwargs["event_type"]
        parts = event_type.split(".")
        assert len(parts) == 3, f"Event type '{event_type}' does not follow module.entity.action pattern"
