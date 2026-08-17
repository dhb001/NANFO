"""Integration tests for reports REST endpoint contracts."""

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
        email="reports-api@example.com",
        roles=["Admin"],
        permissions=["read:telemetry", "write:config"],
    )
    return token


def _make_no_read_telemetry_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="reports-no-read@example.com",
        roles=["Admin"],
        permissions=["write:config"],
    )
    return token


def _make_workspace_scoped_token(*, workspace_id: uuid.UUID) -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="reports-scoped@example.com",
        roles=["Admin"],
        permissions=["read:telemetry", "write:config"],
        workspace_id=str(workspace_id),
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


def _report_response_payload(*, status: str, queue_status: str, idempotent_replay: bool) -> dict:
    now = datetime.now(UTC)
    payload = {
        "report_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "network_id": uuid.uuid4(),
        "report_type": "executive_summary",
        "format": "pdf",
        "status": status,
        "date_range": {
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-08-14T00:00:00+00:00",
        },
        "scope": {"workspace": "all"},
        "filters": {"kpi": "latency"},
        "artifacts": [],
        "error": None,
        "queue_status": queue_status,
        "stream_entry_id": "1000-0",
        "warning": None,
        "idempotency_key": "rep-1",
        "correlation_id": uuid.uuid4(),
        "requested_by_user_id": str(uuid.uuid4()),
        "requested_at": now,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "idempotent_replay": idempotent_replay,
    }
    if status == "generated":
        payload["artifacts"] = [
            {
                "artifact_id": "artifact-1",
                "uri": "s3://nanfo-reports/ws/report.pdf",
                "media_type": "application/pdf",
                "checksum_sha256": "abc123",
                "size_bytes": 16384,
                "generated_at": now,
            }
        ]
        payload["completed_at"] = now
    if status == "failed":
        payload["error"] = {
            "code": "REPORT_GENERATION_FAILED",
            "message": "Report generation failed during queue processing.",
        }
        payload["completed_at"] = now
    return payload


def test_generate_report_returns_202_with_requested_payload(client):
    headers = {
        "Authorization": f"Bearer {_make_token()}",
        "Idempotency-Key": "rep-1",
    }
    response_payload = _report_response_payload(
        status="requested",
        queue_status="queued",
        idempotent_replay=False,
    )

    with patch(
        "app.modules.report.service.ReportService.generate_report",
        new=AsyncMock(return_value=response_payload),
    ) as mock_generate:
        response = client.post(
            "/api/v1/reports/generate",
            json={
                "workspace_id": str(response_payload["workspace_id"]),
                "network_id": str(response_payload["network_id"]),
                "report_type": "executive_summary",
                "format": "pdf",
                "date_range": {
                    "start": "2026-08-01T00:00:00Z",
                    "end": "2026-08-14T00:00:00Z",
                },
                "scope": {"workspace": "all"},
                "filters": {"kpi": "latency"},
            },
            headers=headers,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["status"] == "requested"
    assert body["data"]["queue_status"] == "queued"
    assert body["data"]["idempotent_replay"] is False

    call_kwargs = mock_generate.await_args.kwargs
    assert call_kwargs["idempotency_key"] == "rep-1"


def test_generate_report_returns_generated_replay_payload(client):
    headers = {
        "Authorization": f"Bearer {_make_token()}",
        "Idempotency-Key": "rep-1",
    }
    response_payload = _report_response_payload(
        status="generated",
        queue_status="replayed",
        idempotent_replay=True,
    )

    with patch(
        "app.modules.report.service.ReportService.generate_report",
        new=AsyncMock(return_value=response_payload),
    ):
        response = client.post(
            "/api/v1/reports/generate",
            json={
                "workspace_id": str(response_payload["workspace_id"]),
                "network_id": str(response_payload["network_id"]),
                "report_type": "executive_summary",
                "format": "pdf",
                "date_range": {
                    "start": "2026-08-01T00:00:00Z",
                    "end": "2026-08-14T00:00:00Z",
                },
                "scope": {"workspace": "all"},
                "filters": {"kpi": "latency"},
            },
            headers=headers,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "generated"
    assert body["data"]["idempotent_replay"] is True
    assert len(body["data"]["artifacts"]) == 1


def test_generate_report_idempotency_conflict_returns_409(client):
    headers = {
        "Authorization": f"Bearer {_make_token()}",
        "Idempotency-Key": "rep-1",
    }

    with patch(
        "app.modules.report.service.ReportService.generate_report",
        new=AsyncMock(
            side_effect=HTTPException(
                status_code=409,
                detail={
                    "code": "REPORT_IDEMPOTENCY_CONFLICT",
                    "message": "idempotency_key is already bound to a different report request.",
                },
            )
        ),
    ):
        response = client.post(
            "/api/v1/reports/generate",
            json={
                "workspace_id": str(uuid.uuid4()),
                "network_id": str(uuid.uuid4()),
                "report_type": "executive_summary",
                "format": "pdf",
                "date_range": {
                    "start": "2026-08-01T00:00:00Z",
                    "end": "2026-08-14T00:00:00Z",
                },
                "scope": {"workspace": "all"},
                "filters": {"kpi": "loss"},
            },
            headers=headers,
        )

    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert body["errors"]["code"] == "REPORT_IDEMPOTENCY_CONFLICT"


def test_generate_report_invalid_date_range_returns_400(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.report.service.ReportService.generate_report",
        new=AsyncMock(
            side_effect=HTTPException(
                status_code=400,
                detail={
                    "code": "REPORT_DATE_RANGE_INVALID",
                    "message": "date_range.start and date_range.end must be valid timestamps with start <= end.",
                },
            )
        ),
    ):
        response = client.post(
            "/api/v1/reports/generate",
            json={
                "workspace_id": str(uuid.uuid4()),
                "network_id": str(uuid.uuid4()),
                "report_type": "executive_summary",
                "format": "pdf",
                "date_range": {
                    "start": "2026-08-14T00:00:00Z",
                    "end": "2026-08-01T00:00:00Z",
                },
                "scope": {"workspace": "all"},
                "filters": {"kpi": "latency"},
            },
            headers=headers,
        )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["errors"]["code"] == "REPORT_DATE_RANGE_INVALID"


def test_get_report_returns_generated_payload(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    response_payload = _report_response_payload(
        status="generated",
        queue_status="queued",
        idempotent_replay=False,
    )

    with patch(
        "app.modules.report.service.ReportService.get_report",
        new=AsyncMock(return_value=response_payload),
    ) as mock_get:
        response = client.get(
            f"/api/v1/reports/{response_payload['report_id']}",
            params={"workspace_id": str(response_payload["workspace_id"])},
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "generated"
    assert len(body["data"]["artifacts"]) == 1
    assert mock_get.await_args.kwargs["workspace_id"] == response_payload["workspace_id"]


def test_get_report_returns_failed_payload_with_error_context(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    response_payload = _report_response_payload(
        status="failed",
        queue_status="queued",
        idempotent_replay=False,
    )

    with patch(
        "app.modules.report.service.ReportService.get_report",
        new=AsyncMock(return_value=response_payload),
    ):
        response = client.get(
            f"/api/v1/reports/{response_payload['report_id']}",
            params={"workspace_id": str(response_payload["workspace_id"])},
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "failed"
    assert body["data"]["error"]["code"] == "REPORT_GENERATION_FAILED"


def test_get_report_not_found_returns_404(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.report.service.ReportService.get_report",
        new=AsyncMock(
            side_effect=HTTPException(
                status_code=404,
                detail={"code": "REPORT_NOT_FOUND", "message": "Report not found."},
            )
        ),
    ):
        response = client.get(
            f"/api/v1/reports/{uuid.uuid4()}",
            params={"workspace_id": str(uuid.uuid4())},
            headers=headers,
        )

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["errors"]["code"] == "REPORT_NOT_FOUND"


def test_report_routes_require_auth(client):
    generate_response = client.post(
        "/api/v1/reports/generate",
        json={
            "workspace_id": str(uuid.uuid4()),
            "network_id": str(uuid.uuid4()),
            "report_type": "executive_summary",
            "format": "pdf",
            "date_range": {
                "start": "2026-08-01T00:00:00Z",
                "end": "2026-08-14T00:00:00Z",
            },
            "scope": {"workspace": "all"},
            "filters": {"kpi": "latency"},
        },
    )
    get_response = client.get(
        f"/api/v1/reports/{uuid.uuid4()}",
        params={"workspace_id": str(uuid.uuid4())},
    )

    assert generate_response.status_code in (401, 403)
    assert get_response.status_code in (401, 403)


def test_report_routes_require_read_telemetry_permission(client):
    headers = {"Authorization": f"Bearer {_make_no_read_telemetry_token()}"}
    generate_response = client.post(
        "/api/v1/reports/generate",
        json={
            "workspace_id": str(uuid.uuid4()),
            "network_id": str(uuid.uuid4()),
            "report_type": "executive_summary",
            "format": "pdf",
            "date_range": {
                "start": "2026-08-01T00:00:00Z",
                "end": "2026-08-14T00:00:00Z",
            },
            "scope": {"workspace": "all"},
            "filters": {"kpi": "latency"},
        },
        headers=headers,
    )
    get_response = client.get(
        f"/api/v1/reports/{uuid.uuid4()}",
        params={"workspace_id": str(uuid.uuid4())},
        headers=headers,
    )

    assert generate_response.status_code == 403
    assert get_response.status_code == 403


def test_report_generate_workspace_scope_mismatch_returns_403(client):
    token_workspace_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {_make_workspace_scoped_token(workspace_id=token_workspace_id)}"}
    response = client.post(
        "/api/v1/reports/generate",
        json={
            "workspace_id": str(uuid.uuid4()),
            "network_id": str(uuid.uuid4()),
            "report_type": "executive_summary",
            "format": "pdf",
            "date_range": {
                "start": "2026-08-01T00:00:00Z",
                "end": "2026-08-14T00:00:00Z",
            },
            "scope": {"workspace": "all"},
            "filters": {"kpi": "latency"},
        },
        headers=headers,
    )

    assert response.status_code == 403


def test_report_get_workspace_scope_mismatch_returns_403(client):
    token_workspace_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {_make_workspace_scoped_token(workspace_id=token_workspace_id)}"}
    response = client.get(
        f"/api/v1/reports/{uuid.uuid4()}",
        params={"workspace_id": str(uuid.uuid4())},
        headers=headers,
    )

    assert response.status_code == 403
