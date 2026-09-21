"""Opt-in disposable PostgreSQL/Redis worker persistence with real confined inference.

Private timestamped historical fixtures exercise glue, NOT qualified live operation.
No shared containers, migrations, network devices, training or HTTP auth changes.
"""

import asyncio
import json
import os
import secrets
import subprocess
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.autonomy.model_provider import _QUALIFICATION_TASKS
from app.modules.autonomy.models import AutonomyControl, AutonomyDecision, ConfigurationRevision, TimedOverride
from app.modules.autonomy.providers import installed_providers
from app.modules.autonomy.schemas import ProviderStatus, Verification
from app.modules.autonomy.worker import AutonomyWorker
from tests.autonomy_support import certified_assessment, control_record
from tests.live_provider_support import provision

pytestmark = pytest.mark.skipif(os.environ.get("NANFO_LIVE_PROVIDER_POSTGRES") != "1",
                                reason="explicit disposable Docker provider lane required")


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
async def infrastructure():
    prefix = "nanfo-live-provider-" + uuid.uuid4().hex
    password = secrets.token_hex(24)
    names = []
    engine = redis = None
    try:
        pg = prefix + "-pg"
        docker("run", "--detach", "--rm", "--pull=never", "--name", pg,
               "--tmpfs", "/var/lib/postgresql/data", "-p", "127.0.0.1::5432",
               "-e", "POSTGRES_PASSWORD=" + password, "postgres:16-alpine")
        names.append(pg)
        rd = prefix + "-redis"
        docker("run", "--detach", "--rm", "--pull=never", "--name", rd,
               "-p", "127.0.0.1::6379", "redis:7-alpine", "redis-server",
               "--save", "", "--appendonly", "no", "--requirepass", password)
        names.append(rd)
        port = docker("port", pg, "5432/tcp").rsplit(":", 1)[1]
        redis_port = int(docker("port", rd, "6379/tcp").rsplit(":", 1)[1])
        engine = create_async_engine(f"postgresql+asyncpg://postgres:{password}@127.0.0.1:{port}/postgres")
        redis = Redis(host="127.0.0.1", port=redis_port, password=password)
        for attempt in range(100):
            try:
                async with engine.begin() as connection:
                    for model in (AutonomyControl, AutonomyDecision, ConfigurationRevision, TimedOverride):
                        await connection.run_sync(model.__table__.create, checkfirst=True)
                await redis.ping()
                break
            except (OSError, ConnectionError):
                if attempt == 99:
                    raise
                await asyncio.sleep(.2)
        yield async_sessionmaker(engine, expire_on_commit=False), redis
    finally:
        if redis:
            await redis.aclose()
        if engine:
            await engine.dispose()
        for name in reversed(names):
            docker("rm", "--force", name)


async def test_installed_worker_monitor_recommend_and_durable_acceptance(infrastructure, tmp_path, monkeypatch):
    sessions, redis = infrastructure
    registry, network, workspace, document = provision(tmp_path, snapshot=True)
    for key, value in registry.settings.environment().items():
        monkeypatch.setenv(key, value)
    providers = installed_providers(sessions, redis)
    checkpoint = document["checkpoint"]["sha256"]
    pending = await providers.model.qualify(checkpoint)
    assert pending.reasons == ["live_qualification_pending"]
    await asyncio.gather(*list(_QUALIFICATION_TASKS))
    assert (await providers.model.qualify(checkpoint)).qualified
    control = control_record(network_id=network, workspace_id=workspace, mode="monitor",
                             checkpoint_sha256=checkpoint, claim_token=None, lease_expires_at=None)
    async with sessions() as db:
        db.add(control)
        await db.commit()
    # Identity is a provider-boundary test dependency, not a disabled HTTP/auth layer.
    monkeypatch.setattr("app.modules.autonomy.worker.authorize", AsyncMock(return_value=(control, [])))
    path = Path(registry.settings.observation_root) / "snapshot.json"
    async def refresh(mode):
        body = json.loads(path.read_bytes())
        now = datetime.now(UTC)
        body.update(snapshot_id=str(uuid.uuid4()), observed_at=(now - timedelta(seconds=1)).isoformat(),
                    published_at=now.isoformat(), window_started_at=(now - timedelta(seconds=4)).isoformat())
        path.write_text(json.dumps(body))
        async with sessions() as db:
            current = await db.get(AutonomyControl, network)
            current.mode = mode
            current.next_cycle_at = now - timedelta(seconds=1)
            await db.commit()

    for mode, expected in (("monitor", "observed"), ("recommend", "recommended")):
        await refresh(mode)
        # Independent new worker/provider instance uses backend-owned Redis receipt.
        worker = AutonomyWorker(sessions=sessions, redis=redis)
        assert await worker.run_one()
        async with sessions() as db:
            row = await db.scalar(select(AutonomyDecision).order_by(AutonomyDecision.created_at.desc()).limit(1))
            assert row.status == expected, row.reasons
            assert row.execution_id is None and row.authorization is None
            assert row.observation["compatible"]
            if mode == "recommend":
                assert row.proposal["action_id"] == "route0" and row.safety is None
                assert "not_authorized_for_actuation" in row.reasons

    # Autonomous acceptance tests composition with private calibrated/executor doubles.
    # Only live observer/model are installed concrete providers in this scenario.
    async def assess(observation, proposal):
        from app.modules.autonomy.safety import SafetyShield
        from app.modules.autonomy.schemas import SafetyAssessment, contract_digest
        fixture = certified_assessment(observation, proposal)
        binding = fixture.binding
        binding.policy = binding.policy.model_copy(update={"max_dt_seconds": 20.,
            "max_observation_age_seconds": 30., "max_delay_seconds": 20.})
        action = fixture.selected_action.model_copy(update={"bounds": fixture.selected_action.bounds.model_copy(
            update={"dt_seconds": 20., "valid_until_unix_seconds": observation.observed_at.timestamp() + 25})})
        binding.selected_action_sha256 = contract_digest(action)
        result = SafetyShield(binding.policy, binding.calibration).evaluate(binding.observation, action,
            state=binding.state, now=binding.evaluated_at_unix_seconds)
        assert result["decision"] == "accept", result
        return SafetyAssessment(admissible=True, action_id=action.action_id, model_version="bounded-fluid-v1",
            evidence=["private-unit-fixture:20-second-horizon"], selected_action=result["selected_action"],
            certificate=result["certificate"], binding=binding)
    accepted = []
    async def accept(db, authorization):
        accepted.append(authorization)
        # Enlist in the actual transaction; no commit or physical action.
        assert db.in_transaction()
    async def verify(reference):
        async with sessions() as db:
            row = await db.get(AutonomyDecision, reference.decision_id)
            assert row.status == "accepted" and row.authorization is not None
            assert row.execution_id == reference.execution_id
            assert row.proposal["action_id"] == "route0"
        return Verification(execution_id=reference.execution_id, status="pending", reasons=["private-fixture-not-dispatched"])
    ready = ProviderStatus(provider_id="private-unit-fixture", status="ready")
    composite = replace(installed_providers(sessions, redis),
        safety=SimpleNamespace(status=ready, assess=assess),
        executor=SimpleNamespace(status=ready, accept=accept, verify=verify))
    await refresh("autonomous")
    assert await AutonomyWorker(sessions=sessions, redis=redis, providers=composite).run_one()
    async with sessions() as db:
        last = await db.scalar(select(AutonomyDecision).order_by(AutonomyDecision.created_at.desc()).limit(1))
        assert len(accepted) == 1, last.reasons
        current = await db.get(AutonomyControl, network)
        assert current.active_execution_id == accepted[0].execution_id
        rows = list((await db.scalars(select(AutonomyDecision))).all())
        assert [row.status for row in sorted(rows, key=lambda row: row.created_at)] == ["observed", "recommended", "uncertain"]
