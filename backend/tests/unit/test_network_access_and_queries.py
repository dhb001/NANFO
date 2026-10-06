"""ADR-028: single Network access guard, owner blocking queries and device classifier."""

import subprocess
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.modules.autonomy import queries as autonomy_queries
from app.modules.network import device_types, synthetic_topology
from app.modules.network.access import LockPolicy, NetworkAccessGuard
from app.modules.network.service import NetworkService
from app.modules.simulation import queries as simulation_queries

NETWORK, WORKSPACE, ORG, ACTOR = [uuid.UUID(int=n) for n in range(41, 45)]


def guard(order, *, network=None, membership=None):
    networks = MagicMock()

    async def get_by_id(network_id):
        order.append("read")
        return network if network is not None else SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE)

    async def locked(network_id):
        order.append("lock")

    networks.get_by_id = AsyncMock(side_effect=get_by_id)
    networks.lock_active = AsyncMock(side_effect=locked)
    networks.lock_row = AsyncMock(side_effect=locked)
    workspaces = MagicMock()

    async def member(**kwargs):
        order.append(("member", kwargs["require_write"]))
        if membership is not None:
            raise membership
        return SimpleNamespace(org_id=ORG)

    workspaces.assert_workspace_membership = AsyncMock(side_effect=member)
    db = AsyncMock()
    return NetworkAccessGuard(db, networks=networks, workspaces=workspaces), networks, db


@pytest.mark.parametrize("lock,method", [(LockPolicy.SHARE, "lock_active"), (LockPolicy.EXCLUSIVE, "lock_row")])
async def test_authorize_checks_before_and_after_the_lock(lock, method):
    order = []
    access, networks, db = guard(order)
    grant = await access.authorize(network_id=NETWORK, actor_user_id=str(ACTOR), require_write=True, lock=lock)
    assert order == ["read", ("member", True), "lock", "read", ("member", True)]
    assert (grant.network_id, grant.workspace_id, grant.org_id) == (NETWORK, WORKSPACE, ORG)
    getattr(networks, method).assert_awaited_once_with(NETWORK)
    # External callers may hold ORM objects: the shared fence never expires the session.
    db.run_sync.assert_not_awaited()


async def test_inventory_policy_uses_the_outbox_inventory_lock():
    order = []
    access, _, _ = guard(order)
    with patch("app.modules.network.outbox.NetworkOutboxRepository.lock_inventory", new_callable=AsyncMock) as lock:
        lock.side_effect = lambda network_id: order.append("inventory")
        await access.authorize(network_id=NETWORK, actor_user_id=str(ACTOR), require_write=True,
                               lock=LockPolicy.INVENTORY)
    assert order == ["read", ("member", True), "inventory", "read", ("member", True)]


@pytest.mark.parametrize("denial", ["missing", "workspace", "membership", "claim"])
async def test_denied_callers_never_request_a_lock(denial):
    order = []
    kwargs = {}
    network = SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE)
    membership = None
    if denial == "missing":
        network = None
    elif denial == "workspace":
        kwargs["requested_workspace_id"] = uuid.uuid4()
    elif denial == "membership":
        membership = HTTPException(403, "Insufficient permissions.")
    else:
        kwargs["claim_org_id"] = uuid.uuid4()
    access, networks, _ = guard(order, network=network, membership=membership)
    if network is None:
        access._networks.get_by_id = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await access.authorize(network_id=NETWORK, actor_user_id=str(ACTOR), require_write=True,
                               lock=LockPolicy.EXCLUSIVE, **kwargs)
    assert exc.value.status_code == (404 if denial == "missing" else 403)
    networks.lock_row.assert_not_awaited()


async def test_revocation_while_waiting_for_the_lock_is_denied():
    order = []
    access, _, _ = guard(order)
    access._workspaces.assert_workspace_membership = AsyncMock(
        side_effect=[SimpleNamespace(org_id=ORG), HTTPException(403, "revoked")],
    )
    with pytest.raises(HTTPException) as exc:
        await access.authorize(network_id=NETWORK, actor_user_id=str(ACTOR), require_write=True,
                               lock=LockPolicy.SHARE)
    assert exc.value.status_code == 403


async def test_locks_are_only_taken_for_write_authority():
    access, _, _ = guard([])
    with pytest.raises(ValueError):
        await access.authorize(network_id=NETWORK, actor_user_id=str(ACTOR), lock=LockPolicy.SHARE)


async def test_external_write_contract_keeps_the_shared_fence(mock_db, fake_redis):
    service = NetworkService(mock_db, fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE))
    service._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    service._repo.lock_active = AsyncMock()
    network = await service.assert_network_workspace_access(
        network_id=NETWORK, requested_workspace_id=None, actor_user_id=str(ACTOR), require_write=True,
    )
    assert network.network_id == NETWORK
    service._repo.lock_active.assert_awaited_once_with(NETWORK)
    assert service._workspace_svc.assert_workspace_membership.await_count == 2
    service._repo.lock_active.reset_mock()
    await service.assert_network_workspace_access(network_id=NETWORK, requested_workspace_id=None,
                                                  actor_user_id=str(ACTOR))
    service._repo.lock_active.assert_not_awaited()


def test_network_import_does_not_import_organization():
    code = ("import sys; import app.modules.network.service, app.modules.network.topology;"
            "print('app.modules.organization.service' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                            cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


async def test_has_active_networks_is_an_authorized_existence_probe(mock_db, fake_redis):
    """Organization's WorkspaceInventory port: membership first, then one LIMIT 1 probe."""
    service = NetworkService(mock_db, fake_redis)
    service._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    mock_db.scalar = AsyncMock(return_value=NETWORK)
    assert await service.has_active_networks(workspace_id=WORKSPACE, actor_user_id=str(ACTOR)) is True
    service._workspace_svc.assert_workspace_membership.assert_awaited_once_with(
        workspace_id=WORKSPACE, user_id=str(ACTOR), require_write=False,
    )
    sql = str(mock_db.scalar.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "networks.workspace_id =" in sql and "networks.deleted_at IS NULL" in sql and "LIMIT" in sql
    assert "count" not in sql.lower()
    mock_db.scalar.return_value = None
    assert await service.has_active_networks(workspace_id=WORKSPACE, actor_user_id=str(ACTOR)) is False
    service._workspace_svc.assert_workspace_membership.side_effect = HTTPException(403, "Insufficient permissions.")
    mock_db.scalar.reset_mock()
    with pytest.raises(HTTPException):
        await service.has_active_networks(workspace_id=WORKSPACE, actor_user_id=str(ACTOR))
    mock_db.scalar.assert_not_awaited()


@pytest.mark.parametrize("denial", ["workspace_claim", "org_claim", "membership"])
async def test_workspace_scoped_operations_authorize_through_the_single_guard(mock_db, fake_redis, denial):
    from app.modules.network.schemas import CreateNetworkRequest

    service = NetworkService(mock_db, fake_redis)
    service._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    service._repo.create = AsyncMock()
    service._repo.list_for_workspace = AsyncMock(return_value=([], 0))
    kwargs = {}
    if denial == "workspace_claim":
        kwargs["requested_workspace_id"] = uuid.uuid4()
    elif denial == "org_claim":
        kwargs["claim_org_id"] = uuid.uuid4()
    else:
        service._workspace_svc.assert_workspace_membership.side_effect = HTTPException(403, "denied")
    with pytest.raises(HTTPException) as created:
        await service.create_network(CreateNetworkRequest(workspace_id=WORKSPACE, name="n"), str(ACTOR), "c",
                                     **kwargs)
    with pytest.raises(HTTPException) as listed:
        await service.list_networks(WORKSPACE, str(ACTOR), 1, 20, **kwargs)
    assert created.value.status_code == listed.value.status_code == 403
    service._repo.create.assert_not_awaited()
    service._repo.list_for_workspace.assert_not_awaited()
    if denial == "workspace_claim":
        # A mismatching workspace claim is rejected before any membership read.
        service._workspace_svc.assert_workspace_membership.assert_not_awaited()


def test_dead_accessors_removed():
    from app.modules.network.repository import CampusModelAssetRepository, DeviceRepository, NetworkRepository
    from app.modules.network.topology import TopologyQueryService

    assert not hasattr(NetworkService, "get_network")
    assert not hasattr(DeviceRepository, "update_spatial_ref_id")
    assert not hasattr(TopologyQueryService, "create_device_node")
    # Lock helpers superseded by NetworkAccessGuard's explicit LockPolicy.
    assert not hasattr(NetworkRepository, "lock")
    assert not hasattr(CampusModelAssetRepository, "lock_network")


async def test_simulation_blocking_work_is_one_indexed_probe():
    db = AsyncMock()
    db.scalar.return_value = None
    assert await simulation_queries.has_blocking_work(db, network_id=NETWORK) is False
    sql = db.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "simulations.network_id =" in str(sql) and "simulations.status NOT IN" in str(sql)
    assert set(simulation_queries.TERMINAL_STATUSES) <= set(sql.params["status_1"])
    db.scalar.return_value = uuid.uuid4()
    assert await simulation_queries.has_blocking_work(db, network_id=NETWORK) is True


IDLE = SimpleNamespace(mode="monitor", active_execution_id=None, cancellation_status="none")


@pytest.mark.parametrize("control,override,execution,expected", [
    (None, None, None, False),
    (IDLE, None, None, False),
    (SimpleNamespace(mode="monitor", active_execution_id=None, cancellation_status="verified"), None, None, False),
    (SimpleNamespace(mode="recommend", active_execution_id=None, cancellation_status="none"), None, None, True),
    (SimpleNamespace(mode="monitor", active_execution_id=uuid.uuid4(), cancellation_status="none"), None, None, True),
    (SimpleNamespace(mode="monitor", active_execution_id=None, cancellation_status="uncertain"), None, None, True),
    (SimpleNamespace(mode="monitor", active_execution_id=None, cancellation_status="requested"), None, None, True),
    (None, uuid.uuid4(), None, True),
    # ADR-028: an unreleased (in-flight, uncertain or verified-and-still-applied)
    # autonomous execution blocks deletion even when the control row looks idle.
    (IDLE, None, uuid.uuid4(), True),
    (None, None, uuid.uuid4(), True),
])
async def test_autonomy_blocking_work(control, override, execution, expected):
    db = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = control
    db.execute.return_value = result
    db.scalar.side_effect = [override, execution]
    assert await autonomy_queries.has_blocking_work(db, network_id=NETWORK) is expected
    statement = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "autonomy_controls.network_id =" in statement
    if db.scalar.await_count == 2:
        probe = db.scalar.await_args_list[1].args[0].compile(dialect=postgresql.dialect())
        assert "autonomous_executions.network_id =" in str(probe)
        assert "autonomous_executions.released IS false" in str(probe)


async def test_unresolved_autonomous_execution_is_one_indexed_probe():
    db = AsyncMock()
    db.scalar.return_value = None
    assert await autonomy_queries.has_unresolved_execution(db, network_id=NETWORK) is False
    sql = str(db.scalar.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "released IS false" in sql and "LIMIT" in sql
    db.scalar.return_value = uuid.uuid4()
    assert await autonomy_queries.has_unresolved_execution(db, network_id=NETWORK) is True


def test_single_classifier_serves_tiers_and_functional_groups():
    assert synthetic_topology.device_tier is device_types.device_tier
    assert synthetic_topology.DEVICE_TYPE_TIERS is device_types.DEVICE_TYPE_TIERS
    classification = device_types.classify_device_type("  Wireless_AP ")
    assert classification.normalized == "wireless_ap"
    assert classification.tier == device_types.TIER_LEAF
    assert classification.functional_groups == frozenset({"wireless"})
    assert device_types.classify_device_type("firewall").functional_groups == frozenset({"security"})
    assert device_types.matches_functional_group("core_router", "core")
    assert device_types.matches_functional_group("edge-gateway", "gateway")
    assert not device_types.matches_functional_group(None, "core")
    assert not device_types.matches_functional_group("   ", "core")
    assert device_types.device_tier(None) == device_types.DEFAULT_TIER


def _device(**changes):
    values = {"device_id": uuid.UUID(int=51), "network_id": NETWORK, "hostname": "sw1", "ip_address": "10.0.0.5",
              "device_type": "switch", "vendor": None, "model": None, "location_hint": None,
              "spatial_ref_id": None, "status": "active", "created_at": __import__("datetime").datetime(2026, 9, 1)}
    return SimpleNamespace(**{**values, **changes})


def _read_service(mock_db, fake_redis, *, device=None):
    service = NetworkService(mock_db, fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE))
    service._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    service._device_repo.get_by_id = AsyncMock(return_value=device)
    return service


async def test_public_owner_device_read_returns_ip_and_status_after_authorizing(mock_db, fake_redis):
    """BE-Telemetry request: one authorized device read instead of paging inventory."""
    service = _read_service(mock_db, fake_redis, device=_device())
    result = await service.get_device_for_owner(device_id=uuid.UUID(int=51), actor_user_id=str(ACTOR),
                                                network_id=NETWORK, requested_workspace_id=WORKSPACE)
    assert (result.ip_address, result.status, result.network_id) == ("10.0.0.5", "active", NETWORK)
    service._workspace_svc.assert_workspace_membership.assert_awaited_once_with(
        workspace_id=WORKSPACE, user_id=str(ACTOR), require_write=False)
    # Without network_id the device's own network is authorized.
    result = await service.get_device_for_owner(device_id=uuid.UUID(int=51), actor_user_id=str(ACTOR))
    assert result.device_id == uuid.UUID(int=51)


@pytest.mark.parametrize("case", ["missing", "foreign_network", "denied", "claim"])
async def test_public_owner_device_read_fails_closed(mock_db, fake_redis, case):
    device = None if case == "missing" else _device(network_id=uuid.uuid4() if case == "foreign_network" else NETWORK)
    service = _read_service(mock_db, fake_redis, device=device)
    kwargs = {"network_id": NETWORK}
    if case == "denied":
        service._workspace_svc.assert_workspace_membership.side_effect = HTTPException(403, "denied")
    if case == "claim":
        kwargs["claim_org_id"] = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await service.get_device_for_owner(device_id=uuid.UUID(int=51), actor_user_id=str(ACTOR), **kwargs)
    assert exc.value.status_code == (404 if case in {"missing", "foreign_network"} else 403)
    if case in {"denied", "claim"}:
        # Authorization of the named network precedes any device read.
        service._device_repo.get_by_id.assert_not_awaited()


async def test_batch_owner_device_read_authorizes_once_and_reads_one_bounded_query(mock_db, fake_redis):
    service = _read_service(mock_db, fake_redis)
    rows = [_device(device_id=uuid.UUID(int=n)) for n in (52, 53)]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    mock_db.execute = AsyncMock(return_value=result)
    found = await service.get_devices_for_owner(network_id=NETWORK, actor_user_id=str(ACTOR),
                                                device_ids=[uuid.UUID(int=53), uuid.UUID(int=52), uuid.UUID(int=53)])
    assert set(found) == {uuid.UUID(int=52), uuid.UUID(int=53)} and found[uuid.UUID(int=52)].ip_address == "10.0.0.5"
    service._workspace_svc.assert_workspace_membership.assert_awaited_once()
    sql = mock_db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert "devices.deleted_at IS NULL" in str(sql) and "devices.network_id =" in str(sql)
    with pytest.raises(ValueError):
        await service.get_devices_for_owner(network_id=NETWORK, actor_user_id=str(ACTOR),
                                            device_ids=[uuid.uuid4() for _ in range(1001)])


def test_device_group_selectors_use_the_single_classifier(mock_db, fake_redis):
    from app.modules.network.schemas import UpsertDeviceGroupInput
    from app.modules.network.service import DeviceGroupService

    service = DeviceGroupService(mock_db, fake_redis)
    devices = [SimpleNamespace(device_id=uuid.UUID(int=n), device_type=kind, spatial_ref_id=None, location_hint=None)
               for n, kind in ((1, " Access_Switch "), (2, "core_router"), (3, "Wireless_AP"))]
    by_id = {device.device_id: device for device in devices}

    def resolve(selector):
        group = UpsertDeviceGroupInput(group_key="g", name="g", group_type="custom", selector=selector)
        return service._resolve_group_device_ids(group=group, network_id=NETWORK, devices=devices,
                                                 devices_by_id=by_id)

    assert resolve({"device_type": "ACCESS_SWITCH"}) == [uuid.UUID(int=1)]
    assert resolve({"functional_group": "core"}) == [uuid.UUID(int=2)]
    assert resolve({"functional_group": "wireless"}) == [uuid.UUID(int=3)]
    for device in devices:
        assert device_types.normalize_device_type(device.device_type) == device.device_type.strip().lower()
