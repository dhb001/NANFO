"""ADR026 regression against opt-in isolated PostgreSQL schemas, full current schema.

Run with NETWORK_OUTBOX_TEST_DSN naming a disposable database. Redis is in-memory.
"""
# ruff: noqa: F811 -- shared pytest fixture injection

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, update

from app.modules.network.models import Device, Network
from app.modules.network.outbox import NetworkOutboxPublisher
from app.modules.network.outbox_models import NetworkOutbox
from app.modules.network.repository import DeviceRepository, NetworkRepository
from app.modules.network.schemas import (
    CreateDeviceRequest,
    CreateNetworkRequest,
    UpdateDeviceRequest,
    UpdateNetworkRequest,
)
from app.modules.network.service import DeviceService, NetworkService
from app.modules.organization.models import Organization, OrgMember, Workspace
from tests.integration.test_network_outbox_postgres import sessions  # noqa: F401

def _migration_head() -> str:
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


# The full current schema (ADR-028 relies on migration 0030's unique active
# campus-building index for ON CONFLICT upserts).
pytestmark = [pytest.mark.skipif(not os.environ.get("NETWORK_OUTBOX_TEST_DSN"),
                               reason="NETWORK_OUTBOX_TEST_DSN not configured"),
              pytest.mark.parametrize("sessions", [_migration_head()], indirect=True)]
ORG, WORKSPACE, ACTOR, OTHER_ORG, OTHER_WORKSPACE, OTHER_ACTOR = [uuid.UUID(int=n) for n in range(11, 17)]


async def seed(sessions):
    async with sessions() as db:
        for org, workspace, actor, slug in ((ORG, WORKSPACE, ACTOR, "inventory-test"),
                                            (OTHER_ORG, OTHER_WORKSPACE, OTHER_ACTOR, "foreign-test")):
            db.add(Organization(org_id=org, name=slug, slug=slug))
            await db.flush()
            db.add(Workspace(workspace_id=workspace, org_id=org, name=slug))
            db.add(OrgMember(org_id=org, user_id=actor, org_role="Operator"))
        await db.commit()


async def test_fields_soft_delete_outbox_org_audit_and_tenant(sessions, fake_redis):
    await seed(sessions)
    correlation = str(uuid.UUID(int=20))
    async with sessions() as db:
        network = await NetworkService(db, fake_redis).create_network(
            CreateNetworkRequest(workspace_id=WORKSPACE, name="North", description="Original", cidr="192.0.2.0/24"),
            str(ACTOR), correlation,
        )
        nid = network.network_id
        device = await DeviceService(db, fake_redis).add_device(
            nid, CreateDeviceRequest(hostname="ap-north", ip_address="192.0.2.5", device_type="ap", vendor="vendor",
                                     model="model", location_hint="Room 5"), str(ACTOR), correlation,
        )
        did = device.device_id
        assert device.spatial_ref_id is None
    async with sessions() as db:
        changed = await DeviceService(db, fake_redis).update_device_spatial_ref(nid, did, UpdateDeviceRequest(
            hostname="router-north", ip_address="2001:db8::5", device_type="router", vendor=None, model=None,
            location_hint=None, spatial_ref_id="north/rack-5",
        ), str(ACTOR), correlation)
        assert changed.ip_address == "2001:db8::5" and changed.hostname == "router-north"
        assert changed.vendor is None and changed.model is None and changed.location_hint is None
        changed_network = await NetworkService(db, fake_redis).update_network(
            nid, UpdateNetworkRequest(name="North Updated", description=None, cidr=None), str(ACTOR), correlation,
        )
        assert changed_network.name == "North Updated" and changed_network.cidr is None
    for kwargs in ({"actor_id": str(OTHER_ACTOR)}, {"actor_id": str(ACTOR), "claim_org_id": OTHER_ORG},
                   {"actor_id": str(ACTOR), "requested_workspace_id": OTHER_WORKSPACE}):
        async with sessions() as db:
            with pytest.raises(HTTPException) as exc:
                await NetworkService(db, fake_redis).delete_network(nid, correlation_id=correlation, **kwargs)
            assert exc.value.status_code == 403
    async with sessions() as db:
        with pytest.raises(HTTPException) as exc:
            await NetworkService(db, fake_redis).delete_network(nid, str(ACTOR), correlation)
        assert exc.value.status_code == 409
    async with sessions() as db:
        await DeviceService(db, fake_redis).delete_device(nid, did, str(ACTOR), correlation)
    async with sessions() as db:
        assert (await db.get(Device, did)).deleted_at is not None
        assert await DeviceRepository(db).get_by_id(did) is None
        await NetworkService(db, fake_redis).delete_network(nid, str(ACTOR), correlation)
    async with sessions() as db:
        assert (await db.get(Network, nid)).deleted_at is not None
        assert await NetworkRepository(db).get_by_id(nid) is None
        rows = list((await db.scalars(select(NetworkOutbox).order_by(NetworkOutbox.sequence))).all())
        assert [r.envelope["event_type"] for r in rows] == [
            "network.network.created", "network.device.added", "network.device.updated", "network.network.updated",
            "network.device.deleted", "network.network.deleted",
        ]
        assert all(json.loads(r.envelope["payload"])["org_id"] == str(ORG) for r in rows)
        assert json.loads(rows[2].envelope["payload"])["changed_fields"] == {
            "hostname": "router-north", "ip_address": "2001:db8::5", "device_type": "router", "vendor": None,
            "model": None, "location_hint": None, "spatial_ref_id": "north/rack-5",
        }
    assert await NetworkOutboxPublisher(sessions=sessions, redis=fake_redis).drain() == 6
    from app.events.consumers.audit_consumer import AUDIT_HANDLERS
    from app.modules.identity.repository import AuditLogRepository

    with patch("app.events.consumers.audit_consumer.AsyncSessionLocal", sessions):
        for _, wire in await fake_redis.xrange("stream:network"):
            event = {**wire, "payload": json.loads(wire["payload"])}
            await AUDIT_HANDLERS[event["event_type"]](event)
            await AUDIT_HANDLERS[event["event_type"]](event)
    async with sessions() as db:
        rows, total = await AuditLogRepository(db).list_entries(org_id=ORG)
        assert total == 6 and all(row.actor_id == ACTOR for row in rows)
        _, foreign_total = await AuditLogRepository(db).list_entries(org_id=OTHER_ORG)
        assert foreign_total == 0


async def test_stable_scoped_pagination_and_invalid_values(sessions, fake_redis):
    await seed(sessions)
    created = datetime(2026, 1, 1, tzinfo=UTC)
    nid = uuid.UUID(int=100)
    async with sessions() as db:
        for n in reversed(range(100, 141)):
            db.add(Network(network_id=uuid.UUID(int=n), workspace_id=WORKSPACE, name=f"n{n}", created_at=created))
        db.add(Network(network_id=uuid.UUID(int=99), workspace_id=OTHER_WORKSPACE, name="foreign", created_at=created))
        await db.flush()
        for n in reversed(range(200, 241)):
            db.add(Device(device_id=uuid.UUID(int=n), network_id=nid, hostname=f"h{n}", device_type="switch",
                          created_at=created))
        await db.commit()
    async with sessions() as db:
        for service, key, start in ((NetworkService(db, fake_redis), "network_id", 100),
                                    (DeviceService(db, fake_redis), "device_id", 200)):
            async def page(number, size=20):
                if key == "network_id":
                    return await service.list_networks(WORKSPACE, str(ACTOR), number, size)
                return await service.list_devices(nid, str(ACTOR), number, size)
            pages = [await page(n) for n in (1, 2, 3)]
            assert all(p.total == 41 for p in pages)
            assert [getattr(item, key).int for p in pages for item in p.items] == list(range(start, start + 41))
            assert (await page(4)).items == []
            assert len((await page(1, 500)).items) == 41
            for number, size in ((0, 20), (1, -1), (1, 501)):
                with pytest.raises(ValueError):
                    await page(number, size)
        for values in ({"ip_address": "bad"}, {"hostname": " "}, {"device_type": None}):
            with pytest.raises(ValidationError):
                UpdateDeviceRequest.model_validate(values)
        assert await db.scalar(select(func.count()).select_from(Device)) == 41


async def test_current_membership_rechecked_after_inventory_lock_wait(sessions, fake_redis):
    await seed(sessions)
    async with sessions() as db:
        network = await NetworkService(db, fake_redis).create_network(
            CreateNetworkRequest(workspace_id=WORKSPACE, name="Before"), str(ACTOR), "create",
        )
        nid = network.network_id
    async with sessions() as blocker, sessions() as writer:
        # Prime the writer's identity map and then force an actual parent row wait.
        member = await writer.get(OrgMember, (ORG, ACTOR))
        assert member.org_role == "Operator"
        await blocker.scalar(select(Network.network_id).where(Network.network_id == nid).with_for_update())
        task = asyncio.create_task(NetworkService(writer, fake_redis).update_network(
            nid, UpdateNetworkRequest(name="Denied"), str(ACTOR), "update",
        ))
        try:
            await asyncio.sleep(0.05)
            assert not task.done()
            async with sessions() as revoker:
                await revoker.execute(update(OrgMember).where(
                    OrgMember.org_id == ORG, OrgMember.user_id == ACTOR,
                ).values(org_role="Read-Only"))
                await revoker.commit()
            await blocker.rollback()
            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(task, 5)
            assert exc.value.status_code == 403
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    async with sessions() as db:
        assert (await db.get(Network, nid)).name == "Before"
        assert await db.scalar(select(func.count()).select_from(NetworkOutbox)) == 1


async def test_spatial_reference_blocks_delete_and_outbox_failure_rolls_back(sessions, fake_redis):
    from app.modules.network.outbox import NetworkOutboxRepository
    from app.modules.network.spatial_service import SpatialSceneService
    from app.modules.network.spatial_schemas import ReplaceSpatialSceneRequest
    from tests.spatial_support import replace_payload, spatial_object

    await seed(sessions)
    async with sessions() as db:
        network = await NetworkService(db, fake_redis).create_network(
            CreateNetworkRequest(workspace_id=WORKSPACE, name="Scene"), str(ACTOR), "create",
        )
        nid = network.network_id
        device = await DeviceService(db, fake_redis).add_device(
            nid, CreateDeviceRequest(hostname="scene-device", device_type="ap"), str(ACTOR), "add",
        )
        did = device.device_id
        await SpatialSceneService(db, fake_redis).replace_scene(
            network_id=nid, actor_user_id=str(ACTOR), correlation_id=str(uuid.UUID(int=90)),
            req=ReplaceSpatialSceneRequest.model_validate(replace_payload(objects=[spatial_object(device_id=str(did))])),
        )
    async with sessions() as db:
        with pytest.raises(HTTPException) as exc:
            await DeviceService(db, fake_redis).delete_device(nid, did, str(ACTOR), "delete")
        assert exc.value.status_code == 409
        payload = replace_payload(objects=[])
        payload["expected_revision"] = 1
        await SpatialSceneService(db, fake_redis).replace_scene(
            network_id=nid, actor_user_id=str(ACTOR), correlation_id=str(uuid.UUID(int=91)),
            req=ReplaceSpatialSceneRequest.model_validate(payload),
        )
    original = NetworkOutboxRepository.enqueue

    async def fail_after_flush(repo, **kwargs):
        await original(repo, **kwargs)
        raise RuntimeError("outbox commit failure")

    async with sessions() as db:
        with patch.object(NetworkOutboxRepository, "enqueue", fail_after_flush), pytest.raises(RuntimeError):
            await DeviceService(db, fake_redis).delete_device(nid, did, str(ACTOR), "fail")
    async with sessions() as db:
        assert (await DeviceRepository(db).get_by_id(did)).status == "active"
        assert await db.scalar(select(func.count()).select_from(NetworkOutbox)) == 2
        await DeviceService(db, fake_redis).delete_device(nid, did, str(ACTOR), "delete")
    async with sessions() as db:
        # Historical scene association survives; only the current scene blocks.
        await NetworkService(db, fake_redis).delete_network(nid, str(ACTOR), "delete")


async def test_asset_retirement_retains_bytes_and_unblocks_inventory(sessions, fake_redis, tmp_path):
    from app.modules.network.asset_settings import AssetSettings
    from app.modules.network.asset_storage import LocalAssetStore
    from app.modules.network.models import CampusModelAssetRecord
    from app.modules.network.service import CampusModelAssetService
    from tests.asset_support import request

    await seed(sessions)
    tmp_path.chmod(0o700)
    store = LocalAssetStore(AssetSettings(root=tmp_path))
    async with sessions() as db:
        network = await NetworkService(db, fake_redis).create_network(
            CreateNetworkRequest(workspace_id=WORKSPACE, name="Assets"), str(ACTOR), "create",
        )
        nid = network.network_id
        device = await DeviceService(db, fake_redis).add_device(
            nid, CreateDeviceRequest(hostname="mapped", device_type="ap"), str(ACTOR), "add",
        )
        did = device.device_id
        assets = await CampusModelAssetService(db, fake_redis, asset_store=store).upsert_asset(
            network_id=nid, actor_id=str(ACTOR), req=request(mapping_by_device_id={str(did): "room"}),
        )
        asset = assets.items[0]
        aid = asset.campus_model_asset_id
    async with sessions() as db:
        with pytest.raises(HTTPException) as exc:
            await DeviceService(db, fake_redis).delete_device(nid, did, str(ACTOR), "delete")
        assert exc.value.status_code == 409
        with pytest.raises(HTTPException) as exc:
            await CampusModelAssetService(db, fake_redis, asset_store=store).retire_asset(
                network_id=nid, asset_id=aid, actor_id=str(OTHER_ACTOR),
            )
        assert exc.value.status_code == 403
    async with sessions() as db:
        with patch.object(db, "commit", side_effect=RuntimeError("commit failed")), pytest.raises(RuntimeError):
            await CampusModelAssetService(db, fake_redis, asset_store=store).retire_asset(
                network_id=nid, asset_id=aid, actor_id=str(ACTOR),
            )
    async with sessions() as db:
        assert (await db.get(CampusModelAssetRecord, aid)).deleted_at is None
        await CampusModelAssetService(db, fake_redis, asset_store=store).retire_asset(
            network_id=nid, asset_id=aid, actor_id=str(ACTOR),
        )
    async with sessions() as db:
        stored = await db.get(CampusModelAssetRecord, aid)
        assert stored.deleted_at is not None and stored.mapping_by_device_id == {str(did): "room"}
        assert stored.model_sha256 == asset.model_sha256 and stored.model_size_bytes == asset.model_size_bytes
        assert store.read(stored.model_sha256, stored.model_size_bytes) == b"campus-model"
        service = CampusModelAssetService(db, fake_redis, asset_store=store)
        assert (await service.list_assets(network_id=nid, actor_user_id=str(ACTOR))).total == 0
        with pytest.raises(HTTPException) as exc:
            await service.retire_asset(network_id=nid, asset_id=aid, actor_id=str(ACTOR))
        assert exc.value.status_code == 404
        await DeviceService(db, fake_redis).delete_device(nid, did, str(ACTOR), "delete")
    async with sessions() as db:
        await NetworkService(db, fake_redis).delete_network(nid, str(ACTOR), "delete")
        assert (await db.get(CampusModelAssetRecord, aid)).deleted_at is not None


@pytest.mark.parametrize("restore", [False, True])
async def test_intent_owner_detail_proof_required_for_inventory_delete(sessions, fake_redis, restore):
    from app.modules.intent.models import Intent
    from app.modules.intent.service import IntentExecutionService
    from tests.unit.test_inventory_restoration import restored_detail

    await seed(sessions)
    async with sessions() as db:
        network = await NetworkService(db, fake_redis).create_network(
            CreateNetworkRequest(workspace_id=WORKSPACE, name="Restored"), str(ACTOR), "create",
        )
        nid = network.network_id
        proof = restored_detail(restore=restore)
        provenance = proof["execution_provenance"]
        # Begin with incomplete proof; same persisted owner record is later verified.
        incomplete = {**provenance, "blocks_lab": True}
        row = Intent(workspace_id=WORKSPACE, network_id=nid, intent_kind="throttle_qos",
                     status=proof["status"], execution_provenance=incomplete,
                     correlation_id=uuid.UUID(int=91), requested_by_user_id=str(ACTOR), requested_at=datetime.now(UTC))
        db.add(row)
        await db.commit()
        iid = row.intent_id
    async with sessions() as db:
        with pytest.raises(HTTPException) as exc:
            await NetworkService(db, fake_redis).delete_network(nid, str(ACTOR), "delete")
        assert exc.value.status_code == 409
        # Seed owner-confirmed restoration evidence, then use the real owner detail
        # serializer in the deletion flow (no mocking of detail or dependency guard).
        intent = await db.get(Intent, iid)
        intent.execution_provenance = provenance
        await db.commit()
    async with sessions() as db:
        detail = await IntentExecutionService(db=db, redis=fake_redis).get_intent_detail(
            workspace_id=WORKSPACE, intent_id=iid, user_id=str(ACTOR),
        )
        assert detail["execution_provenance"]["blocks_lab"] is False
        await NetworkService(db, fake_redis).delete_network(nid, str(ACTOR), "delete")
    async with sessions() as db:
        assert (await db.get(Intent, iid)).execution_provenance == provenance
        assert (await db.get(Network, nid)).deleted_at is not None


@pytest.mark.parametrize("variant", ["uppercase", "compact", "braced", "invalid", "conflicting"])
async def test_legacy_asset_uuid_aliases_block_device_delete_until_retired(sessions, fake_redis, variant):
    from app.modules.network.models import CampusModelAssetRecord
    from app.modules.network.service import CampusModelAssetService
    from tests.asset_support import row

    await seed(sessions)
    nid, did = uuid.UUID(int=101), uuid.UUID("abcdefab-1234-5678-9abc-abcdef123456")
    key = {"uppercase": str(did).upper(), "compact": did.hex, "braced": "{" + str(did).upper() + "}",
           "invalid": "legacy-invalid-uuid", "conflicting": did.hex}[variant]
    mapping = {key: "room"}
    if variant == "conflicting":
        mapping[str(did)] = "different-room"
    async with sessions() as db:
        db.add(Network(network_id=nid, workspace_id=WORKSPACE, name="Historical mapping"))
        await db.flush()
        db.add(Device(device_id=did, network_id=nid, hostname="legacy", device_type="ap"))
        await db.flush()
        asset = row(network_id=nid, mapping_by_device_id=mapping)
        db.add(asset)
        await db.commit()
        aid = asset.campus_model_asset_id
    async with sessions() as db:
        with pytest.raises(HTTPException) as error:
            await DeviceService(db, fake_redis).delete_device(nid, did, str(ACTOR), "must-block")
        assert error.value.status_code == 409
    async with sessions() as db:
        assert (await db.get(Device, did)).deleted_at is None
        assert (await db.get(CampusModelAssetRecord, aid)).mapping_by_device_id == mapping
        assert await db.scalar(select(func.count()).select_from(NetworkOutbox)) == 0
        await CampusModelAssetService(db, fake_redis).retire_asset(network_id=nid, asset_id=aid, actor_id=str(ACTOR))
        await DeviceService(db, fake_redis).delete_device(nid, did, str(ACTOR), "safe-after-retirement")
    async with sessions() as db:
        assert (await db.get(Device, did)).deleted_at is not None
        assert (await db.get(CampusModelAssetRecord, aid)).mapping_by_device_id == mapping


async def test_new_asset_mapping_persists_canonical_uuid_and_rejects_conflicts(sessions, fake_redis, tmp_path):
    from app.modules.network.asset_settings import AssetSettings
    from app.modules.network.asset_storage import LocalAssetStore
    from app.modules.network.models import CampusModelAssetRecord
    from app.modules.network.service import CampusModelAssetService
    from tests.asset_support import request

    await seed(sessions)
    tmp_path.chmod(0o700)
    store = LocalAssetStore(AssetSettings(root=tmp_path))
    nid, did = uuid.UUID(int=101), uuid.UUID("abcdefab-1234-5678-9abc-abcdef123456")
    async with sessions() as db:
        db.add(Network(network_id=nid, workspace_id=WORKSPACE, name="New mapping"))
        await db.flush()
        db.add(Device(device_id=did, network_id=nid, hostname="canonical", device_type="ap"))
        await db.commit()
        result = await CampusModelAssetService(db, fake_redis, asset_store=store).upsert_asset(
            network_id=nid, actor_id=str(ACTOR), req=request(mapping_by_device_id={
                str(did).upper(): "room", did.hex: "room", "{" + str(did) + "}": "room",
            }),
        )
        aid = result.items[0].campus_model_asset_id
        assert result.items[0].mapping_by_device_id == {str(did): "room"}
    async with sessions() as db:
        assert (await db.get(CampusModelAssetRecord, aid)).mapping_by_device_id == {str(did): "room"}
        with pytest.raises(ValidationError, match="conflicting"):
            request(mapping_by_device_id={str(did): "room", did.hex: "different"})
        assert await db.scalar(select(func.count()).select_from(CampusModelAssetRecord)) == 1


async def _network_with_devices(sessions, fake_redis, *hostnames):
    await seed(sessions)
    async with sessions() as db:
        network = await NetworkService(db, fake_redis).create_network(
            CreateNetworkRequest(workspace_id=WORKSPACE, name="Groups"), str(ACTOR), "create",
        )
        devices = [await DeviceService(db, fake_redis).add_device(
            network.network_id, CreateDeviceRequest(hostname=name, device_type="ap"), str(ACTOR), "add",
        ) for name in hostnames]
    return network.network_id, [device.device_id for device in devices]


def _group(key="floor", *device_ids, **changes):
    from app.modules.network.schemas import UpsertDeviceGroupInput

    return UpsertDeviceGroupInput.model_validate({
        "group_key": key, "name": changes.pop("name", "Floor"), "group_type": "custom",
        "device_ids": [str(device_id) for device_id in device_ids], **changes,
    })


async def test_group_update_returns_real_updated_at_after_commit_and_enforces_c8(sessions, fake_redis):
    """Regression: update_group only flushed; reading updated_at after commit raised MissingGreenlet."""
    from app.modules.network.models import DeviceGroup, DeviceGroupMember
    from app.modules.network.schemas import UpsertDeviceGroupsRequest
    from app.modules.network.service import DeviceGroupService

    nid, (first, second, third) = await _network_with_devices(sessions, fake_redis, "a", "b", "c")
    async with sessions() as db:
        created = (await DeviceGroupService(db, fake_redis).upsert_groups(
            network_id=nid, actor_id=str(ACTOR), correlation_id="create",
            req=UpsertDeviceGroupsRequest(groups=[_group("floor", first, second)]),
        )).items[0]
    async with sessions() as db:
        kept_member = await db.scalar(select(DeviceGroupMember.device_group_member_id).where(
            DeviceGroupMember.device_id == first, DeviceGroupMember.deleted_at.is_(None)))
    async with sessions() as db:
        updated = (await DeviceGroupService(db, fake_redis).upsert_groups(
            network_id=nid, actor_id=str(ACTOR), correlation_id="update",
            req=UpsertDeviceGroupsRequest(groups=[_group(
                "floor", first, third, name="Renamed", expected_updated_at=created.updated_at.isoformat(),
            )]),
        )).items[0]
    assert updated.device_group_id == created.device_group_id and updated.name == "Renamed"
    assert updated.updated_at > created.updated_at and set(updated.device_ids) == {first, third}
    async with sessions() as db:
        stored = await db.get(DeviceGroup, created.device_group_id)
        assert stored.updated_at == updated.updated_at
        # Membership diff: the kept device keeps its membership row; only b/c change.
        assert await db.scalar(select(DeviceGroupMember.device_group_member_id).where(
            DeviceGroupMember.device_id == first, DeviceGroupMember.deleted_at.is_(None))) == kept_member
    for stale in (created.updated_at, None):
        async with sessions() as db:
            with pytest.raises(HTTPException) as exc:
                await DeviceGroupService(db, fake_redis).upsert_groups(
                    network_id=nid, actor_id=str(ACTOR),
                    req=UpsertDeviceGroupsRequest(groups=[_group(
                        "floor" if stale else "absent", first,
                        expected_updated_at=(stale or updated.updated_at).isoformat(),
                    )]),
                )
            assert exc.value.status_code == 409 and exc.value.detail["code"] == "DEVICE_GROUP_CONFLICT"
    async with sessions() as db:
        from app.modules.identity.models import AuditLog

        audits = (await db.scalars(select(AuditLog).where(AuditLog.event_type == "network.device_groups.upserted"))).all()
        assert len(audits) == 2 and all(audit.org_id == ORG for audit in audits)
        assert {audit.metadata_.get("request_id") for audit in audits} == {"create", "update"}


async def test_concurrent_group_creates_never_raise_integrity_errors(sessions, fake_redis):
    from app.modules.network.models import DeviceGroup
    from app.modules.network.schemas import UpsertDeviceGroupsRequest
    from app.modules.network.service import DeviceGroupService

    nid, (first,) = await _network_with_devices(sessions, fake_redis, "a")

    async def create():
        async with sessions() as db:
            return await DeviceGroupService(db, fake_redis).upsert_groups(
                network_id=nid, actor_id=str(ACTOR), req=UpsertDeviceGroupsRequest(groups=[_group("race", first)]),
            )

    results = await asyncio.wait_for(asyncio.gather(*(create() for _ in range(4))), 20)
    assert len({result.items[0].device_group_id for result in results}) == 1
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DeviceGroup).where(
            DeviceGroup.deleted_at.is_(None))) == 1


def _building(building_id, **changes):
    from app.modules.network.schemas import UpsertCampusBuildingInput

    return UpsertCampusBuildingInput(**{
        "building_id": building_id, "campus_key": "campus", "building_key": building_id, "label": building_id,
        "geometry": "box", "x": 1.0, "z": 2.0, "base_y": 0.0, "width": 10.0, "depth": 8.0, "height": 6.0,
        "floors": 2, "footprint": [[0, 0], [1, 0], [1, 1]], **changes,
    })


async def test_building_upserts_update_in_place_and_replace_retires_absent(sessions, fake_redis):
    """Regression: replace_existing=false updates read updated_at after commit (MissingGreenlet)."""
    from app.modules.identity.models import AuditLog
    from app.modules.network.models import CampusBuildingRecord
    from app.modules.network.schemas import UpsertCampusBuildingsRequest
    from app.modules.network.service import CampusBuildingService

    nid, _ = await _network_with_devices(sessions, fake_redis)
    async with sessions() as db:
        created = await CampusBuildingService(db, fake_redis).upsert_buildings(
            network_id=nid, actor_id=str(ACTOR), correlation_id="create",
            req=UpsertCampusBuildingsRequest(buildings=[_building("a"), _building("b")]),
        )
    ids = {item.building_id: item.campus_building_id for item in created.items}
    async with sessions() as db:
        updated = await CampusBuildingService(db, fake_redis).upsert_buildings(
            network_id=nid, actor_id=str(ACTOR), correlation_id="update",
            req=UpsertCampusBuildingsRequest(replace_existing=False, buildings=[_building("a", label="A2")]),
        )
    assert updated.items[0].campus_building_id == ids["a"] and updated.items[0].label == "A2"
    assert updated.items[0].updated_at > created.items[0].updated_at
    async with sessions() as db:
        replaced = await CampusBuildingService(db, fake_redis).upsert_buildings(
            network_id=nid, actor_id=str(ACTOR), correlation_id="replace",
            req=UpsertCampusBuildingsRequest(replace_existing=True, buildings=[_building("a", label="A3")]),
        )
    assert [item.campus_building_id for item in replaced.items] == [ids["a"]]
    async with sessions() as db:
        rows = (await db.scalars(select(CampusBuildingRecord))).all()
        # No soft-delete + reinsert churn: two identities in total, b retired in place.
        assert len(rows) == 2
        by_id = {row.building_id: row for row in rows}
        assert by_id["a"].deleted_at is None and by_id["a"].label == "A3"
        assert by_id["b"].deleted_at is not None
        audits = (await db.scalars(select(AuditLog).where(
            AuditLog.event_type == "network.campus_buildings.upserted"))).all()
        assert len(audits) == 3 and all(audit.org_id == ORG for audit in audits)


async def test_owner_blocking_queries_run_against_real_owner_tables(sessions, fake_redis):
    from app.modules.autonomy import queries as autonomy_queries
    from app.modules.autonomy.models import AutonomyControl
    from app.modules.intent import queries as intent_queries
    from app.modules.intent.models import Intent
    from app.modules.simulation import queries as simulation_queries
    from app.modules.simulation.models import Simulation

    nid, _ = await _network_with_devices(sessions, fake_redis)
    async with sessions() as db:
        for owner in (simulation_queries, intent_queries, autonomy_queries):
            assert await owner.has_blocking_work(db, network_id=nid) is False
        now = datetime.now(UTC)
        db.add(Simulation(network_id=nid, workspace_id=WORKSPACE, scenario_id=uuid.uuid4(), scenario_name="s",
                          state="running", status="running", risk_gate="pending", requested_by_user_id=str(ACTOR),
                          requested_at=now))
        db.add(Intent(workspace_id=WORKSPACE, network_id=nid, intent_kind="throttle_qos", status="validated",
                      correlation_id=uuid.uuid4(), requested_by_user_id=str(ACTOR), requested_at=now))
        db.add(AutonomyControl(network_id=nid, workspace_id=WORKSPACE, mode="recommend"))
        await db.commit()
    async with sessions() as db:
        for owner in (simulation_queries, intent_queries, autonomy_queries):
            assert await owner.has_blocking_work(db, network_id=nid) is True
        with pytest.raises(HTTPException) as exc:
            await NetworkService(db, fake_redis).delete_network(nid, str(ACTOR), "delete")
        assert exc.value.status_code == 409


async def test_unreleased_autonomous_execution_blocks_network_deletion(sessions, fake_redis):
    """ADR-028: a verified/in-flight autonomous execution still owns device state."""
    from app.modules.autonomy import queries as autonomy_queries
    from app.modules.autonomy.execution_models import AutonomousExecution
    from app.modules.autonomy.models import AutonomyControl

    nid, _ = await _network_with_devices(sessions, fake_redis)
    execution_id = uuid.uuid4()
    async with sessions() as db:
        db.add(AutonomyControl(network_id=nid, workspace_id=WORKSPACE, mode="monitor"))
        await db.flush()
        db.add(AutonomousExecution(
            execution_id=execution_id, decision_id=uuid.uuid4(), network_id=nid, workspace_id=WORKSPACE,
            resource_id=f"network:{nid}", fence=1, command={}, phase="verified", released=False,
            cancel_requested=False,
        ))
        await db.commit()
    async with sessions() as db:
        assert await autonomy_queries.has_unresolved_execution(db, network_id=nid) is True
        assert await autonomy_queries.has_blocking_work(db, network_id=nid) is True
        with pytest.raises(HTTPException) as exc:
            await NetworkService(db, fake_redis).delete_network(nid, str(ACTOR), "delete")
        assert exc.value.status_code == 409 and "autonomy" in exc.value.detail["message"]
    async with sessions() as db:
        await db.execute(update(AutonomousExecution).where(AutonomousExecution.execution_id == execution_id)
                         .values(phase="cancelled", released=True))
        await db.commit()
    async with sessions() as db:
        assert await autonomy_queries.has_blocking_work(db, network_id=nid) is False
        await NetworkService(db, fake_redis).delete_network(nid, str(ACTOR), "delete")
    async with sessions() as db:
        assert await NetworkRepository(db).get_by_id(nid) is None


async def test_workspace_inventory_port_answers_from_active_networks(sessions, fake_redis):
    """Organization's WorkspaceInventory port (ADR-028 fix 14): member-only existence probe."""
    await seed(sessions)
    async with sessions() as db:
        service = NetworkService(db, fake_redis)
        assert await service.has_active_networks(workspace_id=WORKSPACE, actor_user_id=str(ACTOR)) is False
        network = await service.create_network(
            CreateNetworkRequest(workspace_id=WORKSPACE, name="Port"), str(ACTOR), "create",
        )
    async with sessions() as db:
        service = NetworkService(db, fake_redis)
        assert await service.has_active_networks(workspace_id=WORKSPACE, actor_user_id=str(ACTOR)) is True
        with pytest.raises(HTTPException):
            await service.has_active_networks(workspace_id=WORKSPACE, actor_user_id=str(OTHER_ACTOR))
        await db.rollback()
        await service.delete_network(network.network_id, str(ACTOR), "delete")
    async with sessions() as db:
        assert await NetworkService(db, fake_redis).has_active_networks(
            workspace_id=WORKSPACE, actor_user_id=str(ACTOR)) is False


async def test_public_owner_device_reads_return_current_ip_and_status(sessions, fake_redis):
    """BE-Telemetry request (ADR-028 fix 17): device-by-id read instead of paging."""
    await seed(sessions)
    async with sessions() as db:
        network = await NetworkService(db, fake_redis).create_network(
            CreateNetworkRequest(workspace_id=WORKSPACE, name="Reads"), str(ACTOR), "create",
        )
        kept, gone = [await DeviceService(db, fake_redis).add_device(
            network.network_id, CreateDeviceRequest(hostname=name, device_type="switch", ip_address=ip),
            str(ACTOR), "add",
        ) for name, ip in (("kept", "10.9.0.1"), ("gone", "10.9.0.2"))]
        await DeviceService(db, fake_redis).delete_device(network.network_id, gone.device_id, str(ACTOR), "delete")
    async with sessions() as db:
        service = NetworkService(db, fake_redis)
        one = await service.get_device_for_owner(device_id=kept.device_id, actor_user_id=str(ACTOR),
                                                 network_id=network.network_id, requested_workspace_id=WORKSPACE)
        assert (one.ip_address, one.status) == ("10.9.0.1", "active")
        batch = await service.get_devices_for_owner(network_id=network.network_id, actor_user_id=str(ACTOR),
                                                    device_ids=[kept.device_id, gone.device_id, uuid.uuid4()])
        assert list(batch) == [kept.device_id]
        with pytest.raises(HTTPException) as missing:
            await service.get_device_for_owner(device_id=gone.device_id, actor_user_id=str(ACTOR))
        assert missing.value.status_code == 404
        with pytest.raises(HTTPException) as denied:
            await service.get_device_for_owner(device_id=kept.device_id, actor_user_id=str(OTHER_ACTOR))
        assert denied.value.status_code == 403
