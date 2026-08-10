"""Integration tests for telemetry read APIs (VS2 Step 7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.core.security import create_access_token
from app.main import app
from app.modules.telemetry.schemas import (
    TelemetryDeviceHistoryResponse,
    TelemetryHealthResponse,
    TelemetryHistoryResponse,
    TelemetryRecordResponse,
)


def _make_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="telemetry@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
    )
    return token


@pytest.fixture
def client() -> TestClient:
    import fakeredis

    db = AsyncMock()
    fake_r = fakeredis.FakeAsyncRedis(decode_responses=True)

    async def _db():
        yield db

    async def _redis():
        yield fake_r

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token()}"}


def _record(metric: str = "cpu_usage") -> TelemetryRecordResponse:
    now = datetime.now(UTC)
    return TelemetryRecordResponse(
        record_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        metric=metric,
        value=42.0,
        unit="percent",
        observed_at=now,
        source="collector",
        tags={"vendor": "test"},
        created_at=now,
    )


def test_get_telemetry_history_returns_envelope_and_payload(client, headers):
    payload = TelemetryHistoryResponse(items=[_record()], total=1, page=1, page_size=50)
    with patch(
        "app.modules.telemetry.service.TelemetryQueryService.get_history",
        new=AsyncMock(return_value=payload),
    ):
        response = client.get("/api/v1/telemetry/history", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "meta" in body
    assert "errors" in body
    assert body["data"]["total"] == 1


def test_get_telemetry_device_returns_envelope_and_payload(client, headers):
    device_id = uuid.uuid4()
    payload = TelemetryDeviceHistoryResponse(
        device_id=device_id,
        items=[_record(metric="latency_ms")],
        total=1,
        page=1,
        page_size=20,
    )
    with patch(
        "app.modules.telemetry.service.TelemetryQueryService.get_device_history",
        new=AsyncMock(return_value=payload),
    ):
        response = client.get(f"/api/v1/telemetry/device/{device_id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["device_id"] == str(device_id)
    assert body["data"]["items"][0]["metric"] == "latency_ms"


def test_get_telemetry_health_returns_envelope_and_payload(client, headers):
    payload = TelemetryHealthResponse(
        status="ok",
        ingest_lag_ms=150,
        dropped_events=2,
        latest_observed_at=datetime.now(UTC),
        total_records=12,
    )
    with patch(
        "app.modules.telemetry.service.TelemetryQueryService.get_health",
        new=AsyncMock(return_value=payload),
    ):
        response = client.get("/api/v1/telemetry/health", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["ingest_lag_ms"] == 150
    assert body["data"]["dropped_events"] == 2


def test_get_telemetry_health_reads_dropped_counter_snapshot(client, headers):
    with (
        patch(
            "app.modules.telemetry.repository.TelemetryRecordRepository.get_latest_observed_at",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.modules.telemetry.repository.TelemetryRecordRepository.count_all",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.telemetry.counters.TelemetryHealthCounterService.get_snapshot",
            new=AsyncMock(
                return_value={
                    "ingested_events": 6,
                    "persisted_events": 5,
                    "fanout_events": 5,
                    "dropped_events": 3,
                    "runtime_exhausted_cycles": 7,
                    "runtime_exhausted_streak": 3,
                    "runtime_sustained_failure_windows": 2,
                    "runtime_sustained_failure_active": 1,
                }
            ),
        ),
    ):
        response = client.get("/api/v1/telemetry/health", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "degraded"
    assert body["data"]["dropped_events"] == 3


def test_telemetry_endpoints_require_auth(client):
    r1 = client.get("/api/v1/telemetry/history")
    r2 = client.get(f"/api/v1/telemetry/device/{uuid.uuid4()}")
    r3 = client.get("/api/v1/telemetry/health")

    assert r1.status_code in (401, 403)
    assert r2.status_code in (401, 403)
    assert r3.status_code in (401, 403)
