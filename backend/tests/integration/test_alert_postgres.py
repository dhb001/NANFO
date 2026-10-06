"""Disposable schema migrations and measured-typed fixtures, never live lab capture.

ALERT_TEST_DSN must explicitly point to a disposable PostgreSQL database.
"""

import asyncio
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.events.consumers import alert_consumer, audit_consumer, telemetry_consumer
from app.modules.alert.detector import DetectorRule, DetectorSettings
from app.modules.alert.measured import MeasuredAlertService
from app.modules.alert.models import AlertConsumedEvent, AlertDetectorState, AlertHistory, AlertObservation, AlertOutbox, AlertRecord
from app.modules.alert.repository import AlertRepository
from app.modules.alert.service import AlertService
from app.modules.identity.models import AuditLog, User, UserRole, Role
from app.modules.network.emulation import EmulationBinding
from app.modules.network.models import Device, Network
from app.modules.organization.models import Organization, OrgMember, Workspace
from app.modules.telemetry.service import TelemetryPersistenceService
from tests.alert_support import ACTOR, DEVICE, NETWORK, ORG, RUN, START, WORKSPACE, event_for, observation

pytestmark = pytest.mark.skipif(not os.environ.get("ALERT_TEST_DSN"), reason="ALERT_TEST_DSN not configured")


@pytest.fixture
async def sessions():
    schema = "alert_test_" + uuid.uuid4().hex
    url = make_url(os.environ["ALERT_TEST_DSN"])
    sync = create_engine(url.set(drivername="postgresql+psycopg2"))
    engine = None
    with sync.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        with sync.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            # Head, not a pinned revision: the ORM maps the ADR-028 tenancy columns (0030).
            with EnvironmentContext(config, scripts, fn=lambda rev, _: scripts._upgrade_revs("head", rev)) as context:
                context.configure(connection=connection)
                context.run_migrations()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == scripts.get_current_head()
        engine = create_async_engine(url.set(drivername="postgresql+asyncpg"),
            connect_args={"server_settings": {"search_path": schema}})
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if engine:
            await engine.dispose()
        with sync.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        sync.dispose()


async def apply(sessions, seconds, value=85, **overrides):
    sample = observation(seconds, value, **overrides)
    async with sessions() as db:
        await TelemetryPersistenceService(db).persist_event(event_for(sample))
        await db.commit()
    async with sessions() as db:
        service = MeasuredAlertService(db=db, clock=lambda: sample.observed_at)
        service.authorize_observation = AsyncMock(return_value=ORG)
        await service.apply_observation(sample, ORG)


async def rows(sessions, model):
    async with sessions() as db:
        return list((await db.scalars(select(model))).all())


async def generate(sessions):
    for seconds in [0, 5, 10]:
        await apply(sessions, seconds)
    return (await rows(sessions, AlertRecord))[0]


async def seed_scope(sessions):
    async with sessions() as db:
        db.add(Organization(org_id=ORG, name="Fixture", slug="fixture"))
        db.add(User(user_id=ACTOR, email="alert-fixture@example.invalid", hashed_password="not-a-login-hash"))
        await db.flush()
        role_id = await db.scalar(select(Role.role_id).where(Role.name == "Admin"))
        db.add(UserRole(user_id=ACTOR, role_id=role_id))
        db.add(OrgMember(org_id=ORG, user_id=ACTOR, org_role="Admin"))
        db.add(Workspace(workspace_id=WORKSPACE, org_id=ORG, name="Fixture"))
        db.add(Network(network_id=NETWORK, workspace_id=WORKSPACE, name="Fixture"))
        await db.flush()
        db.add(Device(device_id=DEVICE, network_id=NETWORK, hostname="s1", device_type="switch", status="active"))
        await db.commit()


async def test_sustained_recovery_dedup_restart_and_new_run(sessions):
    incident = await generate(sessions)
    assert incident.status == "active"
    for _ in range(3):
        await apply(sessions, 10)
    assert len(await rows(sessions, AlertObservation)) == 3
    for seconds in [15, 20, 25]:
        tags = observation().tags.model_dump()
        tags["run_id"] = uuid.UUID(int=100)
        await apply(sessions, seconds, 0, tags=tags)
    assert (await rows(sessions, AlertRecord))[0].status == "active"
    for seconds in [30, 35, 40]:
        await apply(sessions, seconds, 69)
    records = await rows(sessions, AlertRecord)
    assert len(records) == 1 and records[0].alert_id == incident.alert_id and records[0].status == "resolved"
    history = await rows(sessions, AlertHistory)
    assert {row.event_type for row in history} == {"alert.generated", "alert.resolved"}
    assert len(await rows(sessions, AlertOutbox)) == 2
    for seconds in [45, 50, 55]:
        await apply(sessions, seconds)
    assert len(await rows(sessions, AlertRecord)) == 2


async def test_concurrent_generation_and_unique_index(sessions):
    for seconds in [0, 5]:
        await apply(sessions, seconds)
    await asyncio.gather(*(apply(sessions, 10) for _ in range(6)))
    incident = (await rows(sessions, AlertRecord))[0]
    assert len(await rows(sessions, AlertHistory)) == 1
    async with sessions() as db:
        with pytest.raises(IntegrityError):
            await AlertRepository(db).create_generated(alert_id=uuid.uuid4(), alert_key=incident.alert_key,
                source="telemetry", severity="warning", correlation_id=RUN, payload=incident.payload,
                generated_event_id=uuid.uuid4(), created_at=START, detector_key=incident.detector_key)


@pytest.mark.parametrize("operation", ["acknowledge_alert", "resolve_alert"])
async def test_ack_or_manual_resolve_races_recovery_atomic_history(sessions, operation):
    await seed_scope(sessions)
    incident = await generate(sessions)
    for seconds in [15, 20]:
        await apply(sessions, seconds, 0)

    async def action():
        async with sessions() as db:
            try:
                return await getattr(AlertService(db=db, redis=None), operation)(alert_id=incident.alert_id,
                    correlation_id=str(RUN), requested_by_user_id=str(ACTOR),
                    requested_workspace_id=WORKSPACE, claim_org_id=ORG)
            except HTTPException as exc:
                assert operation == "acknowledge_alert" and exc.status_code == 409

    await asyncio.gather(action(), apply(sessions, 25, 0))
    final = (await rows(sessions, AlertRecord))[0]
    assert final.status == "resolved"
    history = await rows(sessions, AlertHistory)
    assert sum(row.event_type == "alert.resolved" for row in history) == 1
    assert len(await rows(sessions, AlertOutbox)) == len(history)
    for row in history:
        assert row.payload["org_id"] == str(ORG)
        assert row.payload["run_id"] == str(RUN)
        assert row.payload["alert_id"] == str(incident.alert_id)
    if operation == "resolve_alert":
        assert (await action()).idempotent_replay
        assert len(await rows(sessions, AlertHistory)) == len(history)


async def test_history_is_database_immutable(sessions):
    await generate(sessions)
    async with sessions() as db:
        with pytest.raises(DBAPIError, match="immutable"):
            await db.execute(update(AlertHistory).values(event_type="alert.resolved"))


async def test_state_and_history_roll_back_when_outbox_fails(sessions, monkeypatch):
    for seconds in [0, 5]:
        await apply(sessions, seconds)
    async def fail(*args, **kwargs):
        raise RuntimeError("fixture storage failure")
    monkeypatch.setattr(AlertRepository, "append_history", fail)
    with pytest.raises(RuntimeError):
        await apply(sessions, 10)
    assert not await rows(sessions, AlertRecord)
    assert not await rows(sessions, AlertHistory)
    assert len(await rows(sessions, AlertObservation)) == 2
    assert (await rows(sessions, AlertDetectorState))[0].sample_count == 2


async def test_outbox_retry_same_event_and_audit_dedup(sessions, fake_redis, monkeypatch):
    await generate(sessions)
    original = fake_redis.xadd
    async def publish_then_fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("fixture disconnect after server write")
    monkeypatch.setattr(fake_redis, "xadd", publish_then_fail)
    async with sessions() as db:
        with pytest.raises(RuntimeError):
            await AlertRepository(db).publish_one(fake_redis)
    assert (await rows(sessions, AlertOutbox))[0].published_at is None
    monkeypatch.setattr(fake_redis, "xadd", original)
    async with sessions() as db:
        assert await AlertRepository(db).publish_one(fake_redis)
    messages = await fake_redis.xrange("stream:alert")
    assert len(messages) == 2 and messages[0][1]["event_id"] == messages[1][1]["event_id"]
    monkeypatch.setattr(audit_consumer, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(alert_consumer, "AsyncSessionLocal", sessions)
    for _, message in messages:
        message["payload"] = json.loads(message["payload"])
        await audit_consumer.handle_audit_event(message)
        await alert_consumer.handle_alert_lifecycle_event(message)
    audit = await rows(sessions, AuditLog)
    assert len(audit) == 1 and str(audit[0].event_id) == messages[0][1]["event_id"]
    assert len(await rows(sessions, AlertHistory)) == 1


async def test_rule_change_without_version_rejected(sessions):
    await apply(sessions, 0)
    async with sessions() as db:
        service = MeasuredAlertService(db=db, clock=lambda: START + timedelta(seconds=5),
            rules=DetectorSettings(utilization=DetectorRule(breach=90, recover=70)))
        with pytest.raises(ValueError, match="without a new version"):
            await service.apply_observation(observation(5), ORG)
    assert len(await rows(sessions, AlertObservation)) == 1


async def test_real_consumer_persisted_fixture_and_duplicate_retry(sessions, fake_redis, monkeypatch):
    await seed_scope(sessions)
    binding = EmulationBinding(version=1, topology_id="campus-small-v1", network_id=NETWORK,
        workspace_id=WORKSPACE, actor_user_id=ACTOR, switches={"0000000000000001": DEVICE},
        hosts={}, port_capacities_mbps={"0000000000000001:1": 100.0})
    import app.modules.alert.measured as measured
    monkeypatch.setattr(measured, "load_binding", AsyncMock(return_value=binding))
    monkeypatch.setattr(measured, "get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation",
        EMULATION_BINDING_PATH="/fixture/binding", EMULATION_SNAPSHOT_PATH="/fixture/snapshot"))
    monkeypatch.setattr(telemetry_consumer, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(alert_consumer, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(telemetry_consumer, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(telemetry_consumer, "_push_telemetry_delta", AsyncMock())
    clock = [START]
    original = MeasuredAlertService.__init__
    def init(self, **kwargs):
        original(self, **kwargs, clock=lambda: clock[0])
    monkeypatch.setattr(MeasuredAlertService, "__init__", init)
    for seconds in [0, 5, 10, 15, 20, 25]:
        clock[0] = START + timedelta(seconds=seconds)
        event = event_for(observation(seconds, 85 if seconds <= 10 else 0))
        await telemetry_consumer.handle_telemetry_event(event)
        await telemetry_consumer.handle_telemetry_event(event)
    incident = (await rows(sessions, AlertRecord))[0]
    assert incident.status == "resolved"
    assert incident.payload["synthetic"] is False
    assert len(await rows(sessions, AlertHistory)) == 2
    assert len(await rows(sessions, AlertObservation)) == 6
    async with sessions() as db:
        await db.execute(update(OrgMember).values(deleted_at=START))
        await db.commit()
    clock[0] = START + timedelta(seconds=30)
    await telemetry_consumer.handle_telemetry_event(event_for(observation(30)))
    assert len(await rows(sessions, AlertObservation)) == 6


async def test_persisted_values_not_replayed_payload_are_evidence(sessions, monkeypatch):
    sample = observation()
    event = event_for(sample)
    async with sessions() as db:
        await TelemetryPersistenceService(db).persist_event(event)
        await db.commit()
    event["payload"]["value"] = 0
    async with sessions() as db:
        service = MeasuredAlertService(db=db, clock=lambda: START)
        service.authorize_observation = AsyncMock(return_value=ORG)
        service.apply_observation = AsyncMock()
        await service.ingest_persisted_event(event)
        assert service.apply_observation.await_args.args[0].value == 85


async def test_list_scope_before_limit_and_strict_read_history(sessions):
    await seed_scope(sessions)
    incident = await generate(sessions)
    async with sessions() as db:
        repo = AlertRepository(db)
        for i in range(12):
            await repo.create_generated(alert_id=uuid.uuid4(), alert_key=f"foreign:{i}", source="telemetry",
                severity="warning", correlation_id=RUN, payload={"workspace_id": str(uuid.uuid4())},
                generated_event_id=uuid.uuid4(), created_at=START + timedelta(days=1))
        # Nested legacy scope and network-only legacy scope remain readable.
        for payload in [{"scope": {"workspace_id": str(WORKSPACE), "org_id": str(ORG)}},
                        {"network_id": str(NETWORK)}]:
            await repo.create_generated(alert_id=uuid.uuid4(), alert_key=str(uuid.uuid4()), source="telemetry",
                severity="warning", correlation_id=RUN, payload=payload,
                generated_event_id=uuid.uuid4(), created_at=START - timedelta(days=1))
        await db.commit()
    async with sessions() as db:
        service = AlertService(db=db, redis=None)
        result = await service.list_alerts(status_filter=None, severity_filter=None, source_filter=None,
            correlation_id_filter=None, search_filter=None, limit=1, actor_user_id=str(ACTOR),
            requested_workspace_id=WORKSPACE, claim_org_id=ORG)
        # ADR-028: counts describe every authorized match, items stay bounded by limit.
        assert len(result.items) == 1 and result.items[0].alert_id == incident.alert_id
        assert result.total == 3
        assert result.status_counts == {"active": 3, "acknowledged": 0, "resolved": 0}
        scope = dict(alert_id=incident.alert_id, actor_user_id=str(ACTOR), requested_workspace_id=WORKSPACE, claim_org_id=ORG)
        assert (await service.get_history(**scope)).total == 1
        with pytest.raises(HTTPException) as denied:
            await service.get_alert(**{**scope, "requested_workspace_id": uuid.uuid4()})
        assert denied.value.status_code == 403
        result = await service.list_alerts(status_filter=None, severity_filter=None, source_filter=None,
            correlation_id_filter=None, search_filter=None, limit=20, actor_user_id=str(ACTOR),
            requested_workspace_id=WORKSPACE, claim_org_id=ORG)
        assert result.total == 3


async def test_delayed_wrong_scope_lifecycle_cannot_resolve_measured(sessions):
    incident = await generate(sessions)
    for changes in [{}, {"workspace_id": str(uuid.uuid4())}, {"run_id": str(uuid.uuid4())}]:
        async with sessions() as db:
            await AlertService(db=db, redis=None).ingest_alert_event({"event_type": "alert.resolved",
                "event_id": str(uuid.uuid4()), "source": "telemetry", "correlation_id": str(RUN),
                "timestamp": START.isoformat(), "payload": {**incident.payload, **changes}})
    assert (await rows(sessions, AlertRecord))[0].status == "active"
    assert len(await rows(sessions, AlertHistory)) == 1


async def test_stale_duplicate_out_of_order_recovery_cannot_resolve(sessions):
    incident = await generate(sessions)
    await apply(sessions, 15, 0)
    await apply(sessions, 20, 0)
    # Neither stale freshness nor a new UUID at an old timestamp adds evidence.
    async with sessions() as db:
        await MeasuredAlertService(db=db, clock=lambda: START + timedelta(seconds=100)).apply_observation(
            observation(25, 0), ORG)
    await apply(sessions, 19, 0, event_id=uuid.uuid4())
    await apply(sessions, 20, 0, event_id=uuid.uuid4())
    assert (await rows(sessions, AlertRecord))[0].status == "active"
    window = (await rows(sessions, AlertDetectorState))[0]
    assert window.sample_count == 2 and window.last_observed_at == START + timedelta(seconds=20)
    # A missing-data gap resets recovery; a fresh three-sample window is needed.
    await apply(sessions, 31, 0)
    await apply(sessions, 36, 0)
    assert (await rows(sessions, AlertRecord))[0].status == "active"
    await apply(sessions, 41, 0)
    assert (await rows(sessions, AlertRecord))[0].alert_id == incident.alert_id
    assert (await rows(sessions, AlertRecord))[0].status == "resolved"


async def test_ack_replay_and_manual_resolve_reset_window(sessions):
    await seed_scope(sessions)
    incident = await generate(sessions)
    scope = dict(alert_id=incident.alert_id, correlation_id=str(RUN), requested_by_user_id=str(ACTOR),
                 requested_workspace_id=WORKSPACE, claim_org_id=ORG)
    for replay in [False, True]:
        async with sessions() as db:
            result = await AlertService(db=db, redis=None).acknowledge_alert(**scope)
            assert result.idempotent_replay is replay
    assert len(await rows(sessions, AlertHistory)) == 2
    async with sessions() as db:
        await AlertService(db=db, redis=None).resolve_alert(**scope)
    await apply(sessions, 15)
    assert len(await rows(sessions, AlertRecord)) == 1
    for seconds in [20, 25]:
        await apply(sessions, seconds)
    assert len(await rows(sessions, AlertRecord)) == 1
    await apply(sessions, 30)
    assert len(await rows(sessions, AlertRecord)) == 2


@pytest.mark.parametrize("metric,value", [("latency_ms", 100), ("packet_loss_percent", 2), ("queue_backlog_packets", 80)])
async def test_all_rule_incidents_and_recovery_persist(sessions, metric, value):
    for seconds in [0, 5, 10]:
        await apply(sessions, seconds, value, metric=metric)
    incident = (await rows(sessions, AlertRecord))[0]
    for seconds in [15, 20, 25]:
        await apply(sessions, seconds, 0, metric=metric)
    record = (await rows(sessions, AlertRecord))[0]
    assert record.alert_id == incident.alert_id and record.status == "resolved"
    assert record.payload["metric"] == metric


async def test_outbox_preserves_lifecycle_order_for_multiple_workers(sessions, fake_redis):
    await seed_scope(sessions)
    incident = await generate(sessions)
    async with sessions() as db:
        await AlertService(db=db, redis=None).acknowledge_alert(alert_id=incident.alert_id,
            correlation_id=str(RUN), requested_by_user_id=str(ACTOR), requested_workspace_id=WORKSPACE, claim_org_id=ORG)
    for seconds in [15, 20, 25]:
        await apply(sessions, seconds, 0)
    async def drain():
        for _ in range(4):
            async with sessions() as db:
                await AlertRepository(db).publish_one(fake_redis)
    await asyncio.gather(drain(), drain())
    messages = await fake_redis.xrange("stream:alert")
    assert [message["event_type"] for _, message in messages] == ["alert.generated", "alert.acknowledged", "alert.resolved"]


async def test_legacy_unknown_scope_denied_even_for_current_admin(sessions):
    await seed_scope(sessions)
    async with sessions() as db:
        incident = await AlertRepository(db).create_generated(alert_id=uuid.uuid4(), alert_key="infrastructure",
            source="telemetry", severity="warning", correlation_id=RUN, payload={},
            generated_event_id=uuid.uuid4(), created_at=START)
        await db.commit()
        service = AlertService(db=db, redis=None)
        with pytest.raises(HTTPException) as denied:
            await service.get_history(alert_id=incident.alert_id, actor_user_id=str(ACTOR))
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException) as denied:
            await service.resolve_alert(alert_id=incident.alert_id, correlation_id=str(RUN), requested_by_user_id=str(ACTOR))
        assert denied.value.status_code == 403


@pytest.mark.parametrize("barrier", ["detector", "incident", "precommit"])
@pytest.mark.parametrize("fault", ["expires", "membership", "inactive_actor"])
async def test_lock_barrier_rechecks_authority_and_wall_clock(sessions, monkeypatch, barrier, fault):
    await seed_scope(sessions)
    incident = await generate(sessions)
    for seconds in [15, 20]:
        await apply(sessions, seconds, 0)
    import app.modules.alert.measured as measured
    async with sessions() as source_db:
        await TelemetryPersistenceService(source_db).persist_event(event_for(observation(25, 0)))
        await source_db.commit()
    binding = EmulationBinding(version=1, topology_id="campus-small-v1", network_id=NETWORK,
        workspace_id=WORKSPACE, actor_user_id=ACTOR, switches={"0000000000000001": DEVICE},
        hosts={}, port_capacities_mbps={"0000000000000001:1": 100.0})
    monkeypatch.setattr(measured, "load_binding", AsyncMock(return_value=binding))
    monkeypatch.setattr(measured, "get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation",
        EMULATION_BINDING_PATH="/fixture/binding", EMULATION_SNAPSHOT_PATH="/fixture/snapshot"))
    clock = [START + timedelta(seconds=25)]
    arrived, release = asyncio.Event(), asyncio.Event()
    method = "lock_detector" if barrier == "detector" else "get_by_id" if barrier == "incident" else "append_history"
    original = getattr(AlertRepository, method)
    async def blocked(self, *args, **kwargs):
        if barrier == "precommit":
            result = await original(self, *args, **kwargs)
            arrived.set()
            await release.wait()
            return result
        arrived.set()
        return await original(self, *args, **kwargs)
    monkeypatch.setattr(AlertRepository, method, blocked)
    async with sessions() as holder, sessions() as db:
        if barrier == "detector":
            await holder.execute(select(AlertDetectorState).with_for_update())
        elif barrier == "incident":
            await holder.execute(select(AlertRecord).with_for_update())
        service = MeasuredAlertService(db=db, clock=lambda: clock[0])
        sample = observation(25, 0)
        # Populate the exact long-lived session's identity map before waiting.
        assert await service.authorize_observation(sample) == ORG
        task = asyncio.create_task(service.apply_observation(sample, ORG))
        try:
            await asyncio.wait_for(arrived.wait(), 5)
            if fault == "expires":
                clock[0] += timedelta(seconds=31)
            else:
                async with sessions() as admin:
                    if fault == "membership":
                        await admin.execute(update(OrgMember).values(deleted_at=clock[0]))
                    else:
                        await admin.execute(update(User).values(is_active=False))
                    await admin.commit()
            await holder.commit()
            release.set()
            await asyncio.wait_for(task, 5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    current = (await rows(sessions, AlertRecord))[0]
    assert current.alert_id == incident.alert_id and current.status == "active"
    assert len(await rows(sessions, AlertHistory)) == len(await rows(sessions, AlertOutbox)) == 1
    assert len(await rows(sessions, AlertObservation)) == 5
    assert (await rows(sessions, AlertDetectorState))[0].last_observed_at == START + timedelta(seconds=20)


async def test_legacy_same_key_two_tenants_scoped_recovery_and_durable_suppression(sessions):
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    correlation = str(uuid.uuid4())
    first, suppressed, other = [uuid.uuid4() for _ in range(3)]
    def event(event_id, workspace, event_type="alert.generated", **payload):
        return {"event_id": str(event_id), "event_type": event_type, "source": "telemetry",
            "correlation_id": correlation, "timestamp": (START + timedelta(seconds=30)).isoformat(),
            "payload": {"alert_key": "shared-link-rule", "scope": {"workspace_id": str(workspace),
                "port_no": 1, "peer_host": "peer", "rule": {"threshold": 85}}, **payload}}
    async def ingest(value):
        async with sessions() as db:
            await AlertService(db=db, redis=None).ingest_alert_event(value)
    await ingest(event(first, tenant_a))
    await ingest(event(other, tenant_b))
    await ingest(event(suppressed, tenant_a))
    incidents = await rows(sessions, AlertRecord)
    assert len(incidents) == 2
    a = next(row for row in incidents if row.payload["workspace_id"] == str(tenant_a))
    b = next(row for row in incidents if row.payload["workspace_id"] == str(tenant_b))
    receipts = await rows(sessions, AlertConsumedEvent)
    assert len(receipts) == 3
    assert next(row for row in receipts if row.event_id == suppressed).alert_id == a.alert_id
    await ingest(event(uuid.uuid4(), tenant_a, "alert.resolved"))
    incidents = {row.alert_id: row for row in await rows(sessions, AlertRecord)}
    assert incidents[a.alert_id].status == "resolved" and incidents[b.alert_id].status == "active"
    # Identical or malicious changed-content reuse remains consumed after resolution.
    await ingest(event(suppressed, tenant_a))
    await ingest(event(first, tenant_a))
    await ingest(event(suppressed, uuid.uuid4(), message="conflicting replay"))
    assert len(await rows(sessions, AlertRecord)) == 2
    history = await rows(sessions, AlertHistory)
    assert len(history) == 3
    assert sum(row.alert_id == a.alert_id for row in history) == 2
    assert sum(row.alert_id == b.alert_id for row in history) == 1
    assert len(await rows(sessions, AlertConsumedEvent)) == 3


async def test_legacy_scope_rule_and_unknown_scope_do_not_match_measured(sessions):
    measured = await generate(sessions)
    for payload in [{"alert_key": measured.alert_key},
                    {"alert_key": "same", "workspace_id": str(WORKSPACE), "rule": {"x": 1}},
                    {"alert_key": "same", "scope": {"workspace_id": str(WORKSPACE), "rule": {"x": 2}}}]:
        async with sessions() as db:
            await AlertService(db=db, redis=None).ingest_alert_event({"event_id": str(uuid.uuid4()),
                "event_type": "alert.generated", "correlation_id": str(RUN), "source": "telemetry",
                "timestamp": START.isoformat(), "payload": payload})
    assert len(await rows(sessions, AlertRecord)) == 4


async def test_concurrent_legacy_generations_have_receipts_for_single_incident(sessions):
    async def ingest(event_id):
        async with sessions() as db:
            await AlertService(db=db, redis=None).ingest_alert_event({"event_id": str(event_id),
                "event_type": "alert.generated", "correlation_id": str(RUN), "source": "telemetry",
                "timestamp": START.isoformat(), "payload": {"alert_key": "concurrent", "workspace_id": str(WORKSPACE)}})
    ids = [uuid.uuid4() for _ in range(5)]
    await asyncio.gather(*(ingest(event_id) for event_id in ids))
    incidents = await rows(sessions, AlertRecord)
    assert len(incidents) == len(await rows(sessions, AlertHistory)) == 1
    receipts = await rows(sessions, AlertConsumedEvent)
    assert {row.event_id for row in receipts} == set(ids)
    assert {row.alert_id for row in receipts} == {incidents[0].alert_id}


async def test_observation_retention_keeps_open_windows_and_incident_evidence(sessions):
    from datetime import UTC, datetime

    from sqlalchemy import insert as core_insert

    now = datetime.now(UTC)
    old, young = now - timedelta(days=40), now - timedelta(days=1)
    open_alert, resolved_alert, evidence = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    observations = {
        "open-old": ("open", old, uuid.uuid4()),              # unresolved incident: open window
        "resolved-old": ("resolved", old, uuid.uuid4()),
        "resolved-evidence": ("resolved", old, evidence),      # generating sample named by history
        "window-before": ("window", old, uuid.uuid4()),
        "window-inside": ("window", now - timedelta(days=34), uuid.uuid4()),  # current phase run
        "idle-young": ("idle", young, uuid.uuid4()),           # inside retention
        "idle-old": ("idle", old, uuid.uuid4()),  # (receipts always have a detector row: FK, 0030)
    }
    async with sessions() as db:
        # Core inserts: fixture rows only, no measured evidence pins involved.
        for alert_id, status in ((open_alert, "active"), (resolved_alert, "resolved")):
            await db.execute(core_insert(AlertRecord).values(
                alert_id=alert_id, alert_key=f"measured:{alert_id}", source="telemetry", status=status,
                correlation_id=uuid.uuid4(), payload={}, created_at=old, updated_at=old))
        await db.execute(core_insert(AlertHistory).values(
            event_id=uuid.uuid4(), alert_id=resolved_alert, event_type="alert.generated", correlation_id=uuid.uuid4(),
            occurred_at=old, payload={"observation_event_id": str(evidence)}))
        for key, values in {"open": {"incident_id": open_alert}, "resolved": {"incident_id": resolved_alert},
                            "window": {"phase": "breach", "phase_since": now - timedelta(days=35)},
                            "idle": {}}.items():
            await db.execute(core_insert(AlertDetectorState).values(
                detector_key=key, identity={}, rule={}, sample_count=0, **values))
        for detector_key, observed_at, event_id in observations.values():
            await db.execute(core_insert(AlertObservation).values(
                event_id=event_id, detector_key=detector_key, observed_at=observed_at))
        await db.commit()
    deleted = []
    for _ in range(3):
        async with sessions() as db:
            deleted.append(await AlertRepository(db).purge_observations(retention_days=30, batch_size=2))
    assert deleted == [2, 1, 0]  # bounded batches until a short one
    removed = {"resolved-old", "window-before", "idle-old"}
    assert {row.event_id for row in await rows(sessions, AlertObservation)} == {
        event_id for name, (_, _, event_id) in observations.items() if name not in removed}
