"""ADR026 inventory validation, exact deltas, tenancy and deletion policy."""

import json
import uuid
from datetime import UTC, datetime
from ipaddress import ip_address
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.network.deletion import InventoryDeletionService, InventoryDependencyRepository
from app.modules.network.schemas import (
    CreateDeviceRequest,
    CreateNetworkRequest,
    UpdateDeviceRequest,
    UpdateNetworkRequest,
)
from app.modules.network.service import DeviceService, NetworkService

NETWORK, WORKSPACE, ORG, DEVICE, ACTOR = [uuid.UUID(int=n) for n in range(1, 6)]


@pytest.mark.parametrize("schema,values", [
    (CreateNetworkRequest, {"workspace_id": WORKSPACE, "name": " "}),
    (CreateNetworkRequest, {"workspace_id": WORKSPACE, "name": "x" * 254}),
    (CreateNetworkRequest, {"workspace_id": WORKSPACE, "name": "n", "cidr": "nope"}),
    (UpdateNetworkRequest, {}), (UpdateNetworkRequest, {"name": None}),
    (UpdateNetworkRequest, {"cidr": "10.1.1.1/24"}),
    (UpdateNetworkRequest, {"cidr": "10.1.1.1"}),
    (UpdateNetworkRequest, {"description": "x" * 4097}),
    (UpdateNetworkRequest, {"workspace_id": str(WORKSPACE)}),
    (UpdateDeviceRequest, {}), (UpdateDeviceRequest, {"hostname": None}),
    (UpdateDeviceRequest, {"device_type": None}),
    (UpdateDeviceRequest, {"device_type": " "}),
    (UpdateDeviceRequest, {"device_type": "x" * 65}),
    (UpdateDeviceRequest, {"ip_address": "300.1.1.1"}),
    (UpdateDeviceRequest, {"ip_address": "fe80::1%eth0"}),
    (UpdateDeviceRequest, {"ip_address": "10.0.0.1/24"}),
    (UpdateDeviceRequest, {"hostname": " "}),
    (UpdateDeviceRequest, {"vendor": "x" * 254}),
    (UpdateDeviceRequest, {"location_hint": "x" * 1025}),
    (UpdateDeviceRequest, {"spatial_ref_id": "x" * 513}),
    (UpdateDeviceRequest, {"status": "deleted"}),
    (CreateDeviceRequest, {"hostname": "h", "device_type": "router", "ip_address": "bad"}),
])
def test_invalid_inventory_values(schema, values):
    with pytest.raises(ValidationError):
        schema.model_validate(values)


def test_valid_normalization_and_nullable_omission():
    req = CreateDeviceRequest(hostname=" edge ", device_type=" custom-ap ", ip_address="2001:0db8::1")
    assert (req.hostname, req.device_type, req.ip_address, req.spatial_ref_id) == (
        "edge", "custom-ap", "2001:db8::1", None,
    )
    assert UpdateDeviceRequest(spatial_ref_id=None).model_dump(exclude_unset=True) == {"spatial_ref_id": None}
    assert UpdateNetworkRequest(cidr=None).model_dump(exclude_unset=True) == {"cidr": None}


@pytest.fixture
def inventory(mock_db, fake_redis):
    network = SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE, name="Original", cidr="10.0.0.0/24",
                              description="Before", created_at=datetime.now(UTC), deleted_at=None)
    device = SimpleNamespace(device_id=DEVICE, network_id=NETWORK, hostname="edge", device_type="switch",
                             ip_address=ip_address("10.0.0.1"), vendor="v", model="m", location_hint="room",
                             spatial_ref_id="site/rack", status="active", created_at=datetime.now(UTC), deleted_at=None)
    net, dev = NetworkService(mock_db, fake_redis), DeviceService(mock_db, fake_redis)
    for svc in (net, dev):
        svc._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    net._repo.get_by_id = AsyncMock(return_value=network)
    dev._network_repo.get_by_id = AsyncMock(return_value=network)
    dev._repo.get_by_id = AsyncMock(return_value=device)
    dev._repo.lock = AsyncMock(return_value=device)
    return net, dev, network, device


async def test_exact_device_delta_nullable_clear_and_noop(inventory, mock_db):
    _, svc, _, device = inventory
    req = UpdateDeviceRequest(hostname="edge-router", ip_address="2001:db8::1", device_type="router",
                              vendor=None, model=None, location_hint=None, spatial_ref_id=None)
    result = await svc.update_device_spatial_ref(NETWORK, DEVICE, req, str(ACTOR), "delta")
    expected = req.model_dump(exclude_unset=True)
    assert all(getattr(result, key) == value for key, value in expected.items())
    payload = json.loads(mock_db.add.call_args.args[0].envelope["payload"])
    sequence = payload.pop("sequence")
    assert type(sequence) is int and sequence >= 1
    assert payload == {"network_id": str(NETWORK), "device_id": str(DEVICE), "workspace_id": str(WORKSPACE),
                       "org_id": str(ORG), "actor_id": str(ACTOR), "changed_fields": expected}
    mock_db.add.reset_mock()
    await svc.update_device_spatial_ref(NETWORK, DEVICE, req, str(ACTOR), "no-op")
    mock_db.add.assert_not_called()
    assert device.spatial_ref_id is None


async def test_network_patch_exact_fields_and_org_event(inventory, mock_db):
    svc, _, network, _ = inventory
    result = await svc.update_network(NETWORK, UpdateNetworkRequest(name="Renamed", description=None), str(ACTOR), "n")
    assert result.name == "Renamed" and result.description is None and result.cidr == network.cidr
    event = mock_db.add.call_args.args[0].envelope
    assert event["event_type"] == "network.network.updated"
    assert json.loads(event["payload"])["changed_fields"] == {"name": "Renamed", "description": None}
    assert json.loads(event["payload"])["org_id"] == str(ORG)


@pytest.mark.parametrize("operation", ["network_patch", "network_delete", "device_patch", "device_delete"])
@pytest.mark.parametrize("denial", ["org", "workspace", "revoked"])
async def test_mutations_deny_tenant_or_current_authority(inventory, mock_db, operation, denial):
    net, dev, _, _ = inventory
    kwargs = {}
    if denial == "org":
        kwargs["claim_org_id"] = uuid.UUID(int=99)
    elif denial == "workspace":
        kwargs["requested_workspace_id"] = uuid.UUID(int=99)
    else:
        for svc in (net, dev):
            svc._workspace_svc.assert_workspace_membership.side_effect = HTTPException(403, "Insufficient permissions.")
    with pytest.raises(HTTPException) as exc:
        if operation == "network_patch":
            await net.update_network(NETWORK, UpdateNetworkRequest(name="denied"), str(ACTOR), "deny", **kwargs)
        elif operation == "network_delete":
            await net.delete_network(NETWORK, str(ACTOR), "deny", **kwargs)
        elif operation == "device_patch":
            await dev.update_device_spatial_ref(NETWORK, DEVICE, UpdateDeviceRequest(hostname="denied"),
                                                str(ACTOR), "deny", **kwargs)
        else:
            await dev.delete_device(NETWORK, DEVICE, str(ACTOR), "deny", **kwargs)
    assert exc.value.status_code == 403
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()


@pytest.mark.parametrize("device_delete", [False, True])
async def test_soft_delete_atomic_event_and_dependency_conflict(inventory, mock_db, device_delete):
    net, dev, network, device = inventory
    with patch.object(InventoryDeletionService, "assert_safe", new_callable=AsyncMock) as safe:
        safe.side_effect = HTTPException(409, "dependencies")
        with pytest.raises(HTTPException) as exc:
            if device_delete:
                await dev.delete_device(NETWORK, DEVICE, str(ACTOR), "delete")
            else:
                await net.delete_network(NETWORK, str(ACTOR), "delete")
        assert exc.value.status_code == 409
        mock_db.add.assert_not_called()
        assert network.deleted_at is None and device.deleted_at is None
        safe.side_effect = None
        if device_delete:
            await dev.delete_device(NETWORK, DEVICE, str(ACTOR), "delete")
            assert device.deleted_at is not None and device.status == "deleted"
        else:
            await net.delete_network(NETWORK, str(ACTOR), "delete")
            assert network.deleted_at is not None
    event = mock_db.add.call_args.args[0].envelope
    assert event["event_type"] == ("network.device.deleted" if device_delete else "network.network.deleted")
    assert json.loads(event["payload"])["org_id"] == str(ORG)
    mock_db.commit.assert_awaited_once()


@pytest.mark.parametrize("device,results", [
    (False, [NETWORK]), (False, [None, NETWORK]), (False, [None, None, NETWORK]),
    (False, [None, None, None, NETWORK]),
    (False, [None, None, None, None, {"objects": [{"id": "building"}]}]),
    (True, [DEVICE]), (True, [None, NETWORK]),
    (True, [None, None, {"objects": [{"device_id": str(DEVICE)}]}]),
])
async def test_each_owned_dependency_blocks(mock_db, device, results):
    mock_db.execute.return_value.all = lambda: []
    mock_db.scalar.side_effect = results
    with pytest.raises(HTTPException) as exc:
        await InventoryDependencyRepository(mock_db).assert_safe(NETWORK, DEVICE if device else None)
    assert exc.value.status_code == 409


OWNER_QUERIES = {
    "simulations": "app.modules.simulation.queries.has_blocking_work",
    "intents": "app.modules.intent.queries.has_blocking_work",
    "autonomy or timed overrides": "app.modules.autonomy.queries.has_blocking_work",
}


@pytest.mark.parametrize("blocking", list(OWNER_QUERIES))
async def test_workflow_dependency_via_owner_query(inventory, mock_db, fake_redis, blocking):
    _, _, network, _ = inventory
    with (
        patch(OWNER_QUERIES["simulations"], new_callable=AsyncMock, return_value=blocking == "simulations") as sim,
        patch(OWNER_QUERIES["intents"], new_callable=AsyncMock, return_value=blocking == "intents"),
        patch(OWNER_QUERIES["autonomy or timed overrides"], new_callable=AsyncMock,
              return_value=blocking == "autonomy or timed overrides"),
        pytest.raises(HTTPException) as exc,
    ):
        await InventoryDeletionService(mock_db, fake_redis)._assert_workflows_safe(network, str(ACTOR))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "INVENTORY_DEPENDENCIES_ACTIVE"
    assert blocking in exc.value.detail["message"]
    # Owners answer from their own tables by network only; no Network-side SQL.
    sim.assert_awaited_once_with(mock_db, network_id=NETWORK)


async def test_workflow_owner_queries_all_clear(inventory, mock_db, fake_redis):
    _, _, network, _ = inventory
    with (
        patch(OWNER_QUERIES["simulations"], new_callable=AsyncMock, return_value=False) as sim,
        patch(OWNER_QUERIES["intents"], new_callable=AsyncMock, return_value=False) as intent,
        patch(OWNER_QUERIES["autonomy or timed overrides"], new_callable=AsyncMock, return_value=False) as auto,
    ):
        await InventoryDeletionService(mock_db, fake_redis)._assert_workflows_safe(network, str(ACTOR))
    for query in (sim, intent, auto):
        query.assert_awaited_once_with(mock_db, network_id=NETWORK)


def test_deletion_policy_no_longer_imports_intent_internals():
    import inspect

    from app.modules.network import deletion

    source = inspect.getsource(deletion)
    for internal in ("intent.lab", "intent.service", "IntentExecutionService", "IntentHistoryService",
                     "SimulationHistoryService", "AutonomyService"):
        assert internal not in source


@pytest.mark.parametrize("device_delete", [False, True])
async def test_deletion_checks_before_lock_and_rechecks_under_lock(inventory, mock_db, device_delete):
    net, dev, _, _ = inventory
    order: list[str] = []

    async def lock(_repo, network_id):
        order.append("lock")

    async def blocking(db, *, network_id):
        order.append("check")
        # Work created while the deleter waited for the lock is seen by the re-check.
        return order.count("lock") > 0

    with (
        patch("app.modules.network.outbox.NetworkOutboxRepository.lock_inventory", lock),
        patch("app.modules.network.deletion.InventoryDependencyRepository.assert_safe", new_callable=AsyncMock),
        patch(OWNER_QUERIES["simulations"], side_effect=blocking),
        patch(OWNER_QUERIES["intents"], new_callable=AsyncMock, return_value=False),
        patch(OWNER_QUERIES["autonomy or timed overrides"], new_callable=AsyncMock, return_value=False),
        pytest.raises(HTTPException) as exc,
    ):
        if device_delete:
            await dev.delete_device(NETWORK, DEVICE, str(ACTOR), "delete")
        else:
            await net.delete_network(NETWORK, str(ACTOR), "delete")
    assert exc.value.status_code == 409
    assert order == ["check", "lock", "check"]
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()


async def test_unauthorized_deleter_never_takes_inventory_lock(inventory, mock_db):
    net, _, _, _ = inventory
    net._workspace_svc.assert_workspace_membership.side_effect = HTTPException(403, "Insufficient permissions.")
    with (
        patch("app.modules.network.outbox.NetworkOutboxRepository.lock_inventory", new_callable=AsyncMock) as lock,
        patch("app.modules.network.deletion.InventoryDeletionService.assert_safe", new_callable=AsyncMock) as safe,
        pytest.raises(HTTPException) as exc,
    ):
        await net.delete_network(NETWORK, str(ACTOR), "delete")
    assert exc.value.status_code == 403
    lock.assert_not_awaited()
    safe.assert_not_awaited()
