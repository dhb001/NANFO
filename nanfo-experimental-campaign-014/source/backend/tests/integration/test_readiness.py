"""ADR020 public readiness with controlled transport mocks, not auth bypasses."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from app.api import readiness
from app.core.config import get_settings
from app.events.bus import STREAM_GROUPS


@pytest.fixture
async def ready_app(monkeypatch):
    app = FastAPI()
    app.include_router(readiness.router)
    settings = get_settings().model_copy(
        update={"EXECUTION_MODE": "demo", "TELEMETRY_RUNTIME_ADAPTER_MODE": "stub"}
    )
    monkeypatch.setattr(readiness, "get_settings", lambda: settings)
    checks = AsyncMock(
        return_value={"postgres": "ok", "schema": "ok", "redis": "ok", "neo4j": "ok"}
    )
    monkeypatch.setattr(readiness, "dependency_checks", checks)
    monkeypatch.setattr(
        readiness.ArtifactStore,
        "capacity",
        lambda *args: {
            "ready": True,
            "available_bytes": 100000000,
            "min_free_bytes": 67108864,
            "required_bytes": 75497472,
        },
    )
    app.state.realtime_lease = SimpleNamespace(verify=AsyncMock(return_value=True))
    tasks = [asyncio.create_task(asyncio.Event().wait()) for _ in STREAM_GROUPS]
    app.state.consumer_tasks = tasks
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, app, settings, checks
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_ready_canonical_with_explicit_unavailable_optional_capabilities(
    ready_app,
):
    client, _, _, _ = ready_app
    response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"success", "data", "meta", "errors"}
    assert body["success"] and body["data"]["ready"]
    assert body["data"]["capabilities"]["telemetry"] == "unavailable"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("dependency", ["postgres", "schema", "redis", "neo4j"])
async def test_down_dependency_returns_named_canonical_503(ready_app, dependency):
    client, _, _, checks = ready_app
    checks.return_value[dependency] = "unavailable"
    response = await client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert not body["success"] and not body["data"]["ready"]
    assert body["data"]["checks"][dependency] == "unavailable"
    assert body["errors"]["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.parametrize(
    "failure", ["lease", "lease_error", "consumers", "missing_consumers"]
)
async def test_api_runtime_loss_fails_closed_without_internals(ready_app, failure):
    client, app, _, _ = ready_app
    if failure == "lease":
        app.state.realtime_lease.verify.return_value = False
    elif failure == "lease_error":
        app.state.realtime_lease.verify.side_effect = RuntimeError(
            "credential-sentinel"
        )
    elif failure == "consumers":
        app.state.consumer_tasks[0].cancel()
        await asyncio.gather(app.state.consumer_tasks[0], return_exceptions=True)
    else:
        app.state.consumer_tasks = []
    response = await client.get("/ready")
    assert response.status_code == 503
    assert "credential-sentinel" not in response.text


@pytest.mark.parametrize(
    "mode,adapter,collector,code",
    [
        ("emulation", "stub", None, 503),
        ("demo", "emulation", None, 503),
        ("emulation", "emulation", SimpleNamespace(runtime_healthy=False), 503),
        ("emulation", "emulation", SimpleNamespace(runtime_healthy=True), 200),
    ],
)
async def test_configured_telemetry_failure_and_unconfigured_emulation_degrade(
    ready_app, mode, adapter, collector, code
):
    client, app, settings, _ = ready_app
    settings.EXECUTION_MODE, settings.TELEMETRY_RUNTIME_ADAPTER_MODE = mode, adapter
    app.state.telemetry_collector = collector
    assert (await client.get("/ready")).status_code == code


async def test_health_remains_liveness_and_ready_is_mounted():
    from app.main import app

    assert any(route.path == "/ready" for route in app.routes)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_report_capacity_exhaustion_degrades_readiness(ready_app, monkeypatch):
    client, _, _, _ = ready_app
    monkeypatch.setattr(
        readiness.ArtifactStore,
        "capacity",
        lambda *args: {
            "ready": False,
            "available_bytes": 1,
            "min_free_bytes": 67108864,
            "required_bytes": 75497472,
        },
    )
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["data"]["checks"]["report_storage"] == "unavailable"
    assert response.json()["data"]["storage"]["reports"]["available_bytes"] == 1


def test_telemetry_collector_health_tracks_runtime_failure():
    from app.modules.telemetry.service import TelemetryCollectorRunner

    runner = TelemetryCollectorRunner(MagicMock())
    assert not runner.runtime_healthy
    runner._running = True
    runner._runtime_loop_task = MagicMock(done=lambda: False)
    assert runner.runtime_healthy
    runner._runtime_exhausted_streak = 1
    assert not runner.runtime_healthy
    runner._runtime_exhausted_streak = 0
    runner._runtime_loop_task = MagicMock(done=lambda: True)
    assert not runner.runtime_healthy


async def test_distributed_follower_serves_without_fake_local_collector(ready_app):
    client, app, settings, _ = ready_app
    settings.API_REALTIME_DISTRIBUTED = True
    settings.TELEMETRY_RUNTIME_ADAPTER_MODE = "emulation"
    settings.EXECUTION_MODE = "emulation"
    app.state.distributed_realtime = SimpleNamespace(lease=None)
    app.state.consumer_tasks = []
    app.state.telemetry_collector = None
    response = await client.get("/ready")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["checks"]["api_consumers"] == "delegated"
    assert data["capabilities"]["telemetry"] == "delegated"
    assert data["realtime"]["local_collector"] is False
    app.state.realtime_lease.verify.return_value = False
    assert (await client.get("/ready")).status_code == 503


async def test_follower_with_leaked_local_work_is_not_ready(ready_app):
    client, app, settings, _ = ready_app
    settings.API_REALTIME_DISTRIBUTED = True
    app.state.distributed_realtime = SimpleNamespace(lease=None)
    assert (await client.get("/ready")).status_code == 503


async def test_distributed_missing_runtime_and_dead_leader_watchdog_fail(ready_app):
    client, app, settings, _ = ready_app
    settings.API_REALTIME_DISTRIBUTED = True
    assert (await client.get("/ready")).status_code == 503
    app.state.distributed_realtime = SimpleNamespace(lease=object())
    assert (await client.get("/ready")).status_code == 503
    app.state.collector_watchdog = SimpleNamespace(done=lambda: False)
    assert (await client.get("/ready")).status_code == 200


async def test_fleet_diagnostics_do_not_claim_collector_health(ready_app):
    client, app, settings, _ = ready_app
    settings.TELEMETRY_FLEET_ENABLED = True
    settings.EXECUTION_MODE = "production"
    app.state.telemetry_collector = None
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["data"]["capabilities"]["telemetry"] == "external_unverified"
    assert response.json()["data"]["realtime"]["collection_owner"] == "fleet"
