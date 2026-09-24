"""Integration tests for reports REST endpoint contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from tests.auth_support import create_authorized_workspace
from tests.auth_support import create_session_access_token as create_access_token


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
def client(session_auth, tenant_auth) -> TestClient:
    fake_r = session_auth.redis
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
        "workspace_id": create_authorized_workspace(),
        "network_id": uuid.uuid4(),
        "report_type": "executive_summary",
        "format": "pdf",
        "status": status,
        "date_range": {
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-08-14T00:00:00+00:00",
        },
        "scope": {"workspace": "all"},
        "filters": {"metric": "latency"},
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
                "filters": {"metric": "latency"},
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
                "filters": {"metric": "latency"},
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
                "workspace_id": str(create_authorized_workspace()),
                "network_id": str(uuid.uuid4()),
                "report_type": "executive_summary",
                "format": "pdf",
                "date_range": {
                    "start": "2026-08-01T00:00:00Z",
                    "end": "2026-08-14T00:00:00Z",
                },
                "scope": {"workspace": "all"},
                "filters": {"metric": "loss"},
            },
            headers=headers,
        )

    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert body["errors"]["code"] == "REPORT_IDEMPOTENCY_CONFLICT"


def test_generate_report_invalid_date_range_rejected_by_schema(client):
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
                "workspace_id": str(create_authorized_workspace()),
                "network_id": str(uuid.uuid4()),
                "report_type": "executive_summary",
                "format": "pdf",
                "date_range": {
                    "start": "2026-08-14T00:00:00Z",
                    "end": "2026-08-01T00:00:00Z",
                },
                "scope": {"workspace": "all"},
                "filters": {"metric": "latency"},
            },
            headers=headers,
        )

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["errors"]


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
            params={"workspace_id": str(create_authorized_workspace())},
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
            "filters": {"metric": "latency"},
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
            "filters": {"metric": "latency"},
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
            "filters": {"metric": "latency"},
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


def test_report_history_contract_and_bounded_page(client):
    payload = _report_response_payload(status="requested", queue_status="outbox_pending", idempotent_replay=False)
    headers = {"Authorization": f"Bearer {_make_token()}"}
    with patch("app.modules.report.service.ReportService.history", AsyncMock(return_value={
        "items": [payload], "total": 7, "page": 2, "page_size": 1,
    })) as history:
        response = client.get("/api/v1/reports", params={"workspace_id": str(payload["workspace_id"]), "page": 2, "page_size": 1}, headers=headers)
    assert response.status_code == 200 and response.json()["data"]["total"] == 7
    assert history.await_args.kwargs["page"] == 2
    response = client.get("/api/v1/reports", params={"workspace_id": str(payload["workspace_id"]), "page_size": 101}, headers=headers)
    assert response.status_code == 422 and not response.json()["success"]
    # ADR-028: every page parameter uses the shared PageNumber bound (1..10000).
    response = client.get("/api/v1/reports", params={"workspace_id": str(payload["workspace_id"]), "page": 10001}, headers=headers)
    assert response.status_code == 422 and not response.json()["success"]


class _Artifact:
    def __init__(self, body):
        self.body, self.size, self.closed = body, len(body), 0

    def chunks(self):
        yield self.body[:2]
        yield self.body[2:]

    def close(self):
        self.closed += 1


def test_report_download_binary_and_json_error_contract(client):
    payload = _report_response_payload(status="requested", queue_status="outbox_pending", idempotent_replay=False)
    headers = {"Authorization": f"Bearer {_make_token()}"}
    path = f"/api/v1/reports/{payload['report_id']}/download"
    receipt = {"media_type": "text/csv", "filename": "safe.csv", "checksum_sha256": "a" * 64}
    artifact = _Artifact(b"a,b\r\n")
    with patch("app.modules.report.service.ReportService.download_receipt", AsyncMock(return_value=("csv", receipt))), \
            patch("app.modules.report.service.ReportService.open_artifact", AsyncMock(return_value=artifact)) as opened:
        response = client.get(path, params={"workspace_id": str(payload["workspace_id"])}, headers=headers)
    assert response.status_code == 200 and response.content == b"a,b\r\n"
    assert response.headers["content-length"] == "5" and response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    # C5: strong digest ETag, "sha256:<hex>" (was the bare hex).
    assert response.headers["etag"] == f'"sha256:{"a" * 64}"'
    assert opened.await_args.kwargs["output_format"] == "csv" and artifact.closed >= 1
    with patch("app.modules.report.service.ReportService.download_receipt", AsyncMock(side_effect=HTTPException(409, detail={
        "code": "REPORT_ARTIFACT_INVALID", "message": "Invalid artifact",
    }))):
        response = client.get(path, params={"workspace_id": str(payload["workspace_id"])}, headers=headers)
    assert response.status_code == 409 and response.json()["errors"]["code"] == "REPORT_ARTIFACT_INVALID"


@pytest.mark.parametrize("if_none_match", [
    f'"sha256:{"b" * 64}"', f'W/"sha256:{"b" * 64}"', f'"other", "sha256:{"b" * 64}"', "*",
])
def test_report_download_if_none_match_returns_304_without_reading_bytes(client, if_none_match):
    payload = _report_response_payload(status="requested", queue_status="outbox_pending", idempotent_replay=False)
    receipt = {"media_type": "application/pdf", "filename": "r.pdf", "checksum_sha256": "b" * 64}
    headers = {"Authorization": f"Bearer {_make_token()}", "If-None-Match": if_none_match}
    with patch("app.modules.report.service.ReportService.download_receipt", AsyncMock(return_value=("pdf", receipt))), \
            patch("app.modules.report.service.ReportService.open_artifact", AsyncMock()) as opened:
        response = client.get(f"/api/v1/reports/{payload['report_id']}/download",
                              params={"workspace_id": str(payload["workspace_id"])}, headers=headers)
    assert response.status_code == 304 and response.content == b""
    assert response.headers["etag"] == f'"sha256:{"b" * 64}"'
    opened.assert_not_awaited()


def test_report_download_stale_validator_streams_the_body(client):
    payload = _report_response_payload(status="requested", queue_status="outbox_pending", idempotent_replay=False)
    receipt = {"media_type": "text/csv", "filename": "r.csv", "checksum_sha256": "c" * 64}
    headers = {"Authorization": f"Bearer {_make_token()}", "If-None-Match": f'"{"c" * 64}"'}  # legacy bare hex
    with patch("app.modules.report.service.ReportService.download_receipt", AsyncMock(return_value=("csv", receipt))), \
            patch("app.modules.report.service.ReportService.open_artifact", AsyncMock(return_value=_Artifact(b"x,y"))):
        response = client.get(f"/api/v1/reports/{payload['report_id']}/download",
                              params={"workspace_id": str(payload["workspace_id"])}, headers=headers)
    assert response.status_code == 200 and response.content == b"x,y"


def test_generate_report_org_quota_exceeded_returns_507_envelope(client):
    """ADR-028 C26: distinct per-organisation quota code, 507 like other storage quotas."""
    headers = {"Authorization": f"Bearer {_make_token()}"}
    with patch(
        "app.modules.report.service.ReportService.generate_report",
        new=AsyncMock(side_effect=HTTPException(status_code=507, detail={
            "code": "REPORT_ORG_QUOTA_EXCEEDED",
            "message": "Organisation report storage quota is exhausted; no new report was accepted.",
        })),
    ):
        response = client.post("/api/v1/reports/generate", headers=headers, json={
            "workspace_id": str(create_authorized_workspace()), "report_type": "executive_summary", "format": "csv",
            "date_range": {"start": "2026-08-01T00:00:00Z", "end": "2026-08-02T00:00:00Z"},
        })
    assert response.status_code == 507
    body = response.json()
    assert body["success"] is False and body["errors"]["code"] == "REPORT_ORG_QUOTA_EXCEEDED"
    assert "Traceback" not in response.text
