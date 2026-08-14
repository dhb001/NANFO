"""Integration tests for alerts REST endpoint contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.core.security import create_access_token
from app.main import app


def _make_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="alerts-api@example.com",
        roles=["Admin"],
        permissions=["read:telemetry", "write:config"],
    )
    return token


@pytest.fixture
def client() -> TestClient:
    fake_r = fakeredis.FakeAsyncRedis(decode_responses=True)
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    async def _redis():
        yield fake_r

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_list_alerts_returns_envelope_with_status_counts(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    alert_id = uuid.uuid4()
    now = datetime.now(UTC)
    list_payload = {
        "items": [
            {
                "alert_id": alert_id,
                "alert_key": "telemetry_runtime_adapter_slo_threshold_breach",
                "source": "telemetry",
                "status": "active",
                "severity": "critical",
                "correlation_id": uuid.uuid4(),
                "payload": {
                    "alert_id": str(alert_id),
                    "alert_key": "telemetry_runtime_adapter_slo_threshold_breach",
                    "status": "active",
                    "severity": "critical",
                },
                "acknowledged_by_user_id": None,
                "resolved_by_user_id": None,
                "acknowledged_at": None,
                "resolved_at": None,
                "created_at": now,
                "updated_at": now,
            }
        ],
        "total": 1,
        "status_counts": {
            "active": 1,
            "acknowledged": 0,
            "resolved": 0,
        },
    }

    with patch(
        "app.modules.alert.service.AlertService.list_alerts",
        new=AsyncMock(return_value=list_payload),
    ) as mock_list:
        response = client.get(
            "/api/v1/alerts",
            params={
                "status": "active",
                "severity": "critical",
                "source": "telemetry",
                "search": "threshold",
                "limit": 50,
            },
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["total"] == 1
    assert body["data"]["status_counts"]["active"] == 1
    call_kwargs = mock_list.await_args.kwargs
    assert call_kwargs["status_filter"] == "active"
    assert call_kwargs["severity_filter"] == "critical"
    assert call_kwargs["source_filter"] == "telemetry"
    assert call_kwargs["search_filter"] == "threshold"
    assert call_kwargs["limit"] == 50


def test_list_alerts_invalid_status_returns_400_with_error_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.alert.service.AlertService.list_alerts",
        new=AsyncMock(
            side_effect=HTTPException(
                status_code=400,
                detail={
                    "code": "ALERT_STATUS_INVALID",
                    "message": "status must be one of: active, acknowledged, resolved.",
                },
            )
        ),
    ):
        response = client.get("/api/v1/alerts", params={"status": "queued"}, headers=headers)

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["errors"]["code"] == "ALERT_STATUS_INVALID"


def test_acknowledge_alert_returns_envelope_with_queue_metadata(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    alert_id = uuid.uuid4()
    now = datetime.now(UTC)
    response_payload = {
        "alert_id": alert_id,
        "alert_key": "telemetry_runtime_adapter_slo_threshold_breach",
        "source": "telemetry",
        "status": "acknowledged",
        "severity": "critical",
        "correlation_id": uuid.uuid4(),
        "payload": {
            "alert_id": str(alert_id),
            "alert_key": "telemetry_runtime_adapter_slo_threshold_breach",
            "status": "acknowledged",
            "severity": "critical",
        },
        "acknowledged_by_user_id": str(uuid.uuid4()),
        "resolved_by_user_id": None,
        "acknowledged_at": now,
        "resolved_at": None,
        "created_at": now,
        "updated_at": now,
        "queue_status": "queued",
        "stream_entry_id": "910-0",
        "warning": None,
        "idempotent_replay": False,
    }

    with patch(
        "app.modules.alert.service.AlertService.acknowledge_alert",
        new=AsyncMock(return_value=response_payload),
    ) as mock_ack:
        response = client.post(f"/api/v1/alerts/{alert_id}/ack", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["alert_id"] == str(alert_id)
    assert body["data"]["status"] == "acknowledged"
    assert body["data"]["queue_status"] == "queued"
    assert body["data"]["idempotent_replay"] is False
    assert mock_ack.await_args.kwargs["alert_id"] == alert_id


def test_acknowledge_alert_not_found_returns_404_error_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.alert.service.AlertService.acknowledge_alert",
        new=AsyncMock(
            side_effect=HTTPException(
                status_code=404,
                detail={"code": "ALERT_NOT_FOUND", "message": "Alert not found."},
            )
        ),
    ):
        response = client.post(f"/api/v1/alerts/{uuid.uuid4()}/ack", headers=headers)

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["errors"]["code"] == "ALERT_NOT_FOUND"


def test_acknowledge_alert_resolved_conflict_returns_409_error_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.alert.service.AlertService.acknowledge_alert",
        new=AsyncMock(
            side_effect=HTTPException(
                status_code=409,
                detail={
                    "code": "ALERT_ALREADY_RESOLVED",
                    "message": "Resolved alerts cannot be acknowledged.",
                },
            )
        ),
    ):
        response = client.post(f"/api/v1/alerts/{uuid.uuid4()}/ack", headers=headers)

    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert body["errors"]["code"] == "ALERT_ALREADY_RESOLVED"


def test_resolve_alert_returns_envelope_with_replay_metadata(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    alert_id = uuid.uuid4()
    now = datetime.now(UTC)
    response_payload = {
        "alert_id": alert_id,
        "alert_key": "telemetry_runtime_adapter_slo_threshold_breach",
        "source": "telemetry",
        "status": "resolved",
        "severity": "critical",
        "correlation_id": uuid.uuid4(),
        "payload": {
            "alert_id": str(alert_id),
            "alert_key": "telemetry_runtime_adapter_slo_threshold_breach",
            "status": "resolved",
            "severity": "critical",
        },
        "acknowledged_by_user_id": str(uuid.uuid4()),
        "resolved_by_user_id": str(uuid.uuid4()),
        "acknowledged_at": now,
        "resolved_at": now,
        "created_at": now,
        "updated_at": now,
        "queue_status": "replayed",
        "stream_entry_id": None,
        "warning": None,
        "idempotent_replay": True,
    }

    with patch(
        "app.modules.alert.service.AlertService.resolve_alert",
        new=AsyncMock(return_value=response_payload),
    ) as mock_resolve:
        response = client.post(f"/api/v1/alerts/{alert_id}/resolve", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["status"] == "resolved"
    assert body["data"]["queue_status"] == "replayed"
    assert body["data"]["idempotent_replay"] is True
    assert mock_resolve.await_args.kwargs["alert_id"] == alert_id


def test_alert_routes_require_auth(client):
    list_response = client.get("/api/v1/alerts")
    ack_response = client.post(f"/api/v1/alerts/{uuid.uuid4()}/ack")
    resolve_response = client.post(f"/api/v1/alerts/{uuid.uuid4()}/resolve")

    assert list_response.status_code in (401, 403)
    assert ack_response.status_code in (401, 403)
    assert resolve_response.status_code in (401, 403)
