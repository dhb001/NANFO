"""Integration tests for telemetry read APIs (VS2 Step 7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from app.modules.telemetry.schemas import (
    TelemetryAggregationResponse,
    TelemetryDeviceHistoryResponse,
    TelemetryHealthResponse,
    TelemetryHistoryResponse,
    TelemetryRecordResponse,
)
from tests.auth_support import create_session_access_token as create_access_token


def _make_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="telemetry@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
    )
    return token


def _make_no_read_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="telemetry-no-read@example.com",
        roles=["Admin"],
        permissions=["read:topology"],
    )
    return token


def _make_workspace_scoped_token(*, workspace_id: uuid.UUID) -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="telemetry-scoped@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
        workspace_id=str(workspace_id),
    )
    return token


@pytest.fixture
def client(session_auth, tenant_auth) -> TestClient:
    db = AsyncMock()
    fake_r = session_auth.redis

    async def _db():
        yield db

    async def _redis():
        yield fake_r

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def headers(session_auth) -> dict[str, str]:
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
    scoped_workspace_id = uuid.uuid4()

    async def _resolve_scope(*, claims, db, redis, network_id, workspace_id):
        return network_id, scoped_workspace_id

    with (
        patch("app.api.v1.telemetry._resolve_history_scope", side_effect=_resolve_scope),
        patch(
            "app.modules.telemetry.service.TelemetryQueryService.get_history",
            new=AsyncMock(return_value=payload),
        ),
    ):
        response = client.get("/api/v1/telemetry/history", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "data" in body
    assert "meta" in body
    assert "errors" in body
    assert body["data"]["total"] == 1


@pytest.mark.parametrize("params", [
    {"cursor": "untrusted"}, {"pagination": "cursor", "page": 2},
    {"pagination": "cursor", "aggregation": "avg"},
    {"pagination": "cursor", "bucket_seconds": 10},
])
def test_cursor_invalid_combinations_use_canonical_errors(client, headers, params):
    response = client.get("/api/v1/telemetry/history", headers=headers, params=params)
    assert response.status_code == 422
    assert response.json()["errors"]["code"] == "VALIDATION_ERROR"


def test_cursor_scope_rechecked_and_tamper_rejected_before_query(client, headers):
    workspace = uuid.uuid4()
    with (
        patch("app.api.v1.telemetry._resolve_history_scope", new=AsyncMock(return_value=(None, workspace))) as scope,
        patch("app.modules.telemetry.repository.TelemetryRecordRepository.list_history_keyset", new_callable=AsyncMock) as query,
    ):
        response = client.get("/api/v1/telemetry/history", headers=headers, params={"pagination": "cursor", "cursor": "tampered"})
    assert response.status_code == 400 and response.json()["success"] is False
    scope.assert_awaited_once()
    query.assert_not_awaited()


def test_cursor_response_has_no_page_totals_and_preserves_envelope(client, headers):
    row = _record()
    with (
        patch("app.api.v1.telemetry._resolve_history_scope", new=AsyncMock(return_value=(row.network_id, row.workspace_id))),
        patch("app.modules.telemetry.repository.TelemetryRecordRepository.list_history_keyset", new=AsyncMock(return_value=[row])),
    ):
        response = client.get("/api/v1/telemetry/history", headers=headers, params={"pagination": "cursor"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {"items", "page_size", "next_cursor", "upper_record_id", "upper_observed_at"}
    assert data["upper_record_id"] == str(row.record_id) and data["next_cursor"] is None


def test_cursor_current_membership_denial_precedes_cursor_read(client, headers):
    with (
        patch("app.api.v1.telemetry._resolve_history_scope", new=AsyncMock(side_effect=HTTPException(403, "Insufficient permissions."))),
        patch("app.modules.telemetry.cursor.TelemetryCursorService.get_history", new_callable=AsyncMock) as query,
    ):
        response = client.get("/api/v1/telemetry/history", headers=headers, params={"pagination": "cursor", "cursor": "token"})
    assert response.status_code == 403 and response.json()["success"] is False
    query.assert_not_awaited()


@pytest.mark.parametrize("params", [
    {"start_time": "2026-09-08T00:00:00"},
    {"end_time": "invalid"},
    {"start_time": "2026-09-08T00:00:00Z", "end_time": "2026-09-08T00:00:00Z"},
    {"aggregation": "avg"}, {"aggregation": "median"}, {"bucket_seconds": 60},
    {"metric": "cpu", "aggregation": "avg", "bucket_seconds": 0},
    {"metric": "cpu", "aggregation": "avg", "bucket_seconds": 86401},
    {"metric": "cpu", "aggregation": "avg", "bucket_seconds": 60,
     "start_time": "2026-09-01T00:00:00Z", "end_time": "2026-09-08T00:00:01Z"},
])
def test_invalid_history_bounds_return_canonical_errors(client, headers, params):
    with patch("app.modules.telemetry.service.TelemetryQueryService.get_history", new_callable=AsyncMock) as query:
        response = client.get("/api/v1/telemetry/history", headers=headers, params=params)
    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["errors"]["code"] == "VALIDATION_ERROR"
    query.assert_not_awaited()


def test_aggregation_response_and_scoped_forwarding(client, headers):
    workspace_id, network_id, device_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    payload = TelemetryAggregationResponse(items=[{
        "device_id": device_id, "metric": "queue_backlog_bytes", "unit": "bytes",
        "source": "emulation", "port_no": "2", "peer_host": None, "run_id": None, "bucket_start": "2026-09-08T00:00:00Z",
        "value": 40, "sample_count": 3,
    }], total=8, page=2, page_size=1)
    with (
        patch("app.api.v1.telemetry._resolve_history_scope", new=AsyncMock(return_value=(network_id, workspace_id))),
        patch("app.modules.telemetry.service.TelemetryQueryService.get_history", new=AsyncMock(return_value=payload)) as query,
    ):
        response = client.get("/api/v1/telemetry/history", headers=headers, params={
            "metric": "queue_backlog_bytes", "aggregation": "avg", "bucket_seconds": 60,
            "start_time": "2026-09-08T03:00:00+03:00", "end_time": "2026-09-08T01:00:00Z", "page": 2, "page_size": 1,
        })
    assert response.status_code == 200
    assert response.json()["data"] == payload.model_dump(mode="json")
    query.assert_awaited_once_with(
        network_id=network_id, workspace_id=workspace_id, metric="queue_backlog_bytes",
        aggregation="avg", bucket_seconds=60, start_time=datetime(2026, 9, 8, tzinfo=UTC),
        end_time=datetime(2026, 9, 8, 1, tzinfo=UTC), page=2, page_size=1, count_cap=10_000,
    )


@pytest.mark.parametrize("path", ["/api/v1/telemetry/history", f"/api/v1/telemetry/device/{uuid.uuid4()}"])
@pytest.mark.parametrize("page", ["0", "10001", "9223372036854775808"])
def test_page_numbers_are_bounded_before_any_query(client, headers, path, page):
    """ADR-028: unbounded pages overflowed OFFSET (HTTP 500) or forced deep scans."""
    with (
        patch("app.modules.telemetry.service.TelemetryQueryService.get_history", new_callable=AsyncMock) as history,
        patch("app.modules.telemetry.service.TelemetryQueryService.get_device_history", new_callable=AsyncMock) as device,
    ):
        response = client.get(path, headers=headers, params={"page": page})
    assert response.status_code == 422
    assert response.json()["errors"]["code"] == "VALIDATION_ERROR"
    history.assert_not_awaited()
    device.assert_not_awaited()


def test_capped_history_total_is_reported(client, headers):
    workspace_id = uuid.uuid4()
    with (
        patch("app.api.v1.telemetry._resolve_history_scope", new=AsyncMock(return_value=(None, workspace_id))),
        patch("app.modules.telemetry.repository.TelemetryRecordRepository.list_history",
              new=AsyncMock(return_value=([], 10_001))) as query,
    ):
        response = client.get("/api/v1/telemetry/history", headers=headers, params={"page": 10_000})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 10_000 and data["total_capped"] is True and data["page"] == 10_000
    assert query.await_args.kwargs["count_cap"] == 10_000


def test_device_bounds_validation_and_forwarding(client, headers):
    device_id, network_id, workspace_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with (
        patch("app.api.v1.telemetry._resolve_device_scope", new=AsyncMock(return_value=(network_id, workspace_id))),
        patch("app.modules.telemetry.service.TelemetryQueryService.get_device_history", new=AsyncMock(return_value=TelemetryDeviceHistoryResponse(device_id=device_id, items=[], total=0, page=1, page_size=50))) as query,
    ):
        invalid = client.get(f"/api/v1/telemetry/device/{device_id}", headers=headers, params={"start_time": "2026-09-08"})
        assert invalid.status_code == 422
        query.assert_not_awaited()
        response = client.get(f"/api/v1/telemetry/device/{device_id}", headers=headers, params={"end_time": "2026-09-08T00:00:00Z"})
    assert response.status_code == 200
    assert query.call_args.kwargs["end_time"] == datetime(2026, 9, 8, tzinfo=UTC)
    assert query.call_args.kwargs["workspace_id"] == workspace_id


def test_aggregation_does_not_bypass_tenant_scope(client, headers):
    with patch("app.modules.telemetry.service.TelemetryQueryService.get_history", new_callable=AsyncMock) as query:
        response = client.get("/api/v1/telemetry/history", headers=headers, params={
            "metric": "cpu", "aggregation": "avg", "bucket_seconds": 60,
            "start_time": "2026-09-08T00:00:00Z", "end_time": "2026-09-08T01:00:00Z",
        })
    assert response.status_code == 403
    query.assert_not_awaited()


def test_flow_aggregation_rejected_before_query(client, headers):
    with patch("app.modules.telemetry.service.TelemetryQueryService.get_history", new_callable=AsyncMock) as query:
        response = client.get("/api/v1/telemetry/history", headers=headers, params={
            "metric": "flow_byte_count", "aggregation": "sum", "bucket_seconds": 60,
            "start_time": "2026-09-08T00:00:00Z", "end_time": "2026-09-08T01:00:00Z",
        })
    assert response.status_code == 422
    assert "no durable flow match identity" in response.json()["errors"]["message"]
    assert "raw history" in response.json()["errors"]["message"]
    query.assert_not_awaited()


def test_get_telemetry_device_returns_envelope_and_payload(client, headers):
    request_device_id = uuid.uuid4()
    scoped_network_id = uuid.uuid4()
    scoped_workspace_id = uuid.uuid4()
    payload = TelemetryDeviceHistoryResponse(
        device_id=request_device_id,
        items=[_record(metric="latency_ms")],
        total=1,
        page=1,
        page_size=20,
    )

    async def _resolve_scope(*, claims, db, redis, device_id):
        assert device_id == request_device_id
        return scoped_network_id, scoped_workspace_id

    with (
        patch("app.api.v1.telemetry._resolve_device_scope", side_effect=_resolve_scope),
        patch(
            "app.modules.telemetry.service.TelemetryQueryService.get_device_history",
            new=AsyncMock(return_value=payload),
        ),
    ):
        response = client.get(f"/api/v1/telemetry/device/{request_device_id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["device_id"] == str(request_device_id)
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
            "app.modules.telemetry.repository.TelemetryRecordRepository.estimate_total_records",
            new=AsyncMock(return_value=(0, False)),
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


def test_get_telemetry_health_is_read_only_without_event_redis(client, headers):
    """ADR-028 C12: the health read path never receives a publisher."""
    with patch("app.api.v1.telemetry.TelemetryQueryService") as mock_query_service_cls:
        mock_svc = AsyncMock()
        mock_svc.get_health = AsyncMock(
            return_value=TelemetryHealthResponse(
                status="ok",
                ingest_lag_ms=0,
                dropped_events=0,
                latest_observed_at=None,
                total_records=0,
            )
        )
        mock_query_service_cls.return_value = mock_svc

        response = client.get("/api/v1/telemetry/health", headers=headers)

    assert response.status_code == 200
    call_kwargs = mock_query_service_cls.call_args.kwargs
    assert "event_redis" not in call_kwargs
    assert call_kwargs["counter_service"] is not None


def test_get_telemetry_health_reports_additive_slo_object(client, headers, session_auth):
    with (
        patch("app.modules.telemetry.repository.TelemetryRecordRepository.get_latest_observed_at",
              new=AsyncMock(return_value=datetime.now(UTC))),
        patch("app.modules.telemetry.repository.TelemetryRecordRepository.estimate_total_records",
              new=AsyncMock(return_value=(7, False))),
        patch("app.events.publisher.publish_event", new_callable=AsyncMock) as publish,
    ):
        response = client.get("/api/v1/telemetry/health", headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_records"] == 7 and data["total_records_estimated"] is False
    assert data["slo"]["status"] in {"unavailable", "ok", "degraded", "critical"}
    assert {"alert_active", "evaluated_at", "stale", "thresholds"} <= set(data["slo"])
    publish.assert_not_awaited()


def test_get_telemetry_health_validates_workspace_claim_scope(client):
    token_workspace_id = uuid.uuid4()
    token_org_id = uuid.uuid4()
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="telemetry-health-scoped@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
        workspace_id=str(token_workspace_id),
        org_id=str(token_org_id),
    )
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch("app.api.v1.telemetry.WorkspaceService") as mock_workspace_service_cls,
        patch(
            "app.modules.telemetry.service.TelemetryQueryService.get_health",
            new=AsyncMock(
                return_value=TelemetryHealthResponse(
                    status="ok",
                    ingest_lag_ms=0,
                    dropped_events=0,
                    latest_observed_at=None,
                    total_records=0,
                )
            ),
        ),
    ):
        workspace_service = AsyncMock()
        workspace_service.get_active_workspace = AsyncMock()
        mock_workspace_service_cls.return_value = workspace_service

        response = client.get("/api/v1/telemetry/health", headers=headers)

    assert response.status_code == 200
    workspace_service.get_active_workspace.assert_awaited_once_with(
        token_workspace_id,
        user_id=ANY,
        claim_org_id=token_org_id,
    )


def test_get_telemetry_health_workspace_scope_mismatch_returns_403(client):
    token_workspace_id = uuid.uuid4()
    token_org_id = uuid.uuid4()
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="telemetry-health-scope-deny@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
        workspace_id=str(token_workspace_id),
        org_id=str(token_org_id),
    )
    headers = {"Authorization": f"Bearer {token}"}

    with patch("app.api.v1.telemetry.WorkspaceService") as mock_workspace_service_cls:
        workspace_service = AsyncMock()
        workspace_service.get_active_workspace = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Insufficient permissions.")
        )
        mock_workspace_service_cls.return_value = workspace_service

        response = client.get("/api/v1/telemetry/health", headers=headers)

    assert response.status_code == 403


def test_get_telemetry_health_validates_org_claim_scope_without_workspace_claim(client):
    token_org_id = uuid.uuid4()
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="telemetry-health-org-scoped@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
        org_id=str(token_org_id),
    )
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch("app.api.v1.telemetry.WorkspaceService") as mock_workspace_service_cls,
        patch(
            "app.modules.telemetry.service.TelemetryQueryService.get_health",
            new=AsyncMock(
                return_value=TelemetryHealthResponse(
                    status="ok",
                    ingest_lag_ms=0,
                    dropped_events=0,
                    latest_observed_at=None,
                    total_records=0,
                )
            ),
        ),
    ):
        workspace_service = AsyncMock()
        workspace_service.list_workspaces = AsyncMock(return_value=AsyncMock())
        mock_workspace_service_cls.return_value = workspace_service

        response = client.get("/api/v1/telemetry/health", headers=headers)

    assert response.status_code == 200
    workspace_service.get_active_workspace.assert_not_awaited()
    workspace_service.list_workspaces.assert_awaited_once_with(
        org_id=token_org_id,
        user_id=ANY,
        page=1,
        page_size=1,
    )


def test_get_telemetry_health_invalid_org_claim_returns_401(client):
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="telemetry-health-invalid-org@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
        org_id="not-a-uuid",
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/v1/telemetry/health", headers=headers)
    assert response.status_code == 401


def test_telemetry_endpoints_require_auth(client):
    r1 = client.get("/api/v1/telemetry/history")
    r2 = client.get(f"/api/v1/telemetry/device/{uuid.uuid4()}")
    r3 = client.get("/api/v1/telemetry/health")

    assert r1.status_code in (401, 403)
    assert r2.status_code in (401, 403)
    assert r3.status_code in (401, 403)


def test_telemetry_endpoints_require_read_telemetry_permission(client):
    headers = {"Authorization": f"Bearer {_make_no_read_token()}"}
    r1 = client.get("/api/v1/telemetry/history", headers=headers)
    r2 = client.get(f"/api/v1/telemetry/device/{uuid.uuid4()}", headers=headers)
    r3 = client.get("/api/v1/telemetry/health", headers=headers)

    assert r1.status_code == 403
    assert r2.status_code == 403
    assert r3.status_code == 403


def test_telemetry_history_workspace_scope_mismatch_returns_403(client):
    token_workspace_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {_make_workspace_scoped_token(workspace_id=token_workspace_id)}"}
    response = client.get(
        "/api/v1/telemetry/history",
        params={"workspace_id": str(uuid.uuid4())},
        headers=headers,
    )

    assert response.status_code == 403


def test_telemetry_history_requires_workspace_scope_when_network_not_provided(client, headers):
    with (
        patch(
            "app.api.v1.telemetry._resolve_history_scope",
            side_effect=HTTPException(status_code=403, detail="Insufficient permissions."),
        ),
        patch(
            "app.modules.telemetry.service.TelemetryQueryService.get_history",
            new=AsyncMock(),
        ) as mock_get_history,
    ):
        response = client.get("/api/v1/telemetry/history", headers=headers)

    assert response.status_code == 403
    mock_get_history.assert_not_awaited()


def test_telemetry_history_scope_resolution_includes_claim_workspace_and_org(client):
    token_workspace_id = uuid.uuid4()
    token_org_id = uuid.uuid4()
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="telemetry-scoped-org@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
        workspace_id=str(token_workspace_id),
        org_id=str(token_org_id),
    )
    headers = {"Authorization": f"Bearer {token}"}

    request_network_id = uuid.uuid4()
    payload = TelemetryHistoryResponse(items=[], total=0, page=1, page_size=50)

    async def _resolve_scope(*, claims, db, redis, network_id, workspace_id):
        assert network_id == request_network_id
        assert workspace_id is None
        assert claims.workspace_id == str(token_workspace_id)
        assert claims.org_id == str(token_org_id)
        return network_id, token_workspace_id

    with (
        patch("app.api.v1.telemetry._resolve_history_scope", side_effect=_resolve_scope),
        patch(
            "app.modules.telemetry.service.TelemetryQueryService.get_history",
            new=AsyncMock(return_value=payload),
        ) as mock_get_history,
    ):
        response = client.get(
            "/api/v1/telemetry/history",
            params={"network_id": str(request_network_id)},
            headers=headers,
        )

    assert response.status_code == 200
    call_kwargs = mock_get_history.await_args.kwargs
    assert call_kwargs["network_id"] == request_network_id
    assert call_kwargs["workspace_id"] == token_workspace_id


def test_telemetry_device_scope_resolution_includes_claim_workspace_and_org(client):
    token_workspace_id = uuid.uuid4()
    token_org_id = uuid.uuid4()
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="telemetry-device-scoped@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
        workspace_id=str(token_workspace_id),
        org_id=str(token_org_id),
    )
    headers = {"Authorization": f"Bearer {token}"}

    request_device_id = uuid.uuid4()
    scoped_network_id = uuid.uuid4()
    payload = TelemetryDeviceHistoryResponse(
        device_id=request_device_id,
        items=[],
        total=0,
        page=1,
        page_size=50,
    )

    async def _resolve_scope(*, claims, db, redis, device_id):
        assert device_id == request_device_id
        assert claims.workspace_id == str(token_workspace_id)
        assert claims.org_id == str(token_org_id)
        return scoped_network_id, token_workspace_id

    with (
        patch("app.api.v1.telemetry._resolve_device_scope", side_effect=_resolve_scope),
        patch(
            "app.modules.telemetry.service.TelemetryQueryService.get_device_history",
            new=AsyncMock(return_value=payload),
        ) as mock_get_device_history,
    ):
        response = client.get(f"/api/v1/telemetry/device/{request_device_id}", headers=headers)

    assert response.status_code == 200
    call_kwargs = mock_get_device_history.await_args.kwargs
    assert call_kwargs["device_id"] == request_device_id
    assert call_kwargs["network_id"] == scoped_network_id
    assert call_kwargs["workspace_id"] == token_workspace_id


def test_telemetry_device_denied_on_unresolved_scope_returns_403(client, headers):
    with (
        patch(
            "app.api.v1.telemetry._resolve_device_scope",
            side_effect=HTTPException(status_code=403, detail="Insufficient permissions."),
        ),
        patch(
            "app.modules.telemetry.service.TelemetryQueryService.get_device_history",
            new=AsyncMock(),
        ) as mock_get_device_history,
    ):
        response = client.get(f"/api/v1/telemetry/device/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 403
    mock_get_device_history.assert_not_awaited()
