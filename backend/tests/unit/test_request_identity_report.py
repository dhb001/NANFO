"""Opaque correlation acceptance retains provenance and existing report contracts."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from app.modules.report.artifacts import digest, render
from app.modules.report.repository import ReportRepository
from app.modules.report.service import ReportService
from tests.auth_support import create_authorized_workspace
from tests.report_support import request, snapshot


@pytest.fixture
def report_service(mock_db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.modules.report.service.get_settings", lambda: SimpleNamespace(
        REPORTS_STORAGE_PATH=str(tmp_path), REPORTS_MAX_BYTES=100000, REPORTS_MIN_FREE_BYTES=0,
    ))
    svc = ReportService(db=mock_db, redis=None)
    svc.authorize_generation = AsyncMock()
    svc._repo.get_by_idempotency_key = AsyncMock(return_value=None)
    return svc


def arguments(request_id, output_format="csv"):
    req = request(workspace_id=str(uuid.UUID(int=27)), format=output_format)
    data = req.model_dump(mode="json")
    data.pop("format")
    return req, {**data, "workspace_id": req.workspace_id, "output_format": output_format,
                 "fail_generation": False, "idempotency_key": "adr027-report",
                 "correlation_id": request_id, "requested_by_user_id": str(uuid.UUID(int=28))}


@pytest.mark.parametrize("request_id", ["req_report/27", str(uuid.UUID(int=27))])
@pytest.mark.parametrize("output_format", ["csv", "pdf"])
async def test_report_generation_correlation_and_replay(report_service, mock_db, monkeypatch, request_id, output_format):
    req, args = arguments(request_id, output_format)
    original = {**snapshot(req), "metadata": {"source": "preserved"}}
    sources = AsyncMock(return_value=original)
    monkeypatch.setattr("app.modules.report.service.ReportSources.snapshot", sources)
    result = await report_service.generate_report(**args)
    record, event = [call.args[0] for call in mock_db.add.call_args_list]
    expected = (uuid.UUID(request_id) if request_id[0].isdigit() else
                uuid.uuid5(uuid.NAMESPACE_URL, f"nanfo:audit-correlation:{request_id}"))
    assert record.correlation_id == result["correlation_id"] == expected
    assert event.envelope["correlation_id"] == str(expected)
    assert record.snapshot["metadata"]["source"] == "preserved"
    assert "request_id" not in original["metadata"]
    if request_id.startswith("req_"):
        assert record.snapshot["metadata"]["request_id"] == request_id
    else:
        assert record.snapshot == original
    assert record.snapshot_sha256 == digest(record.snapshot)
    artifact = render(record.snapshot, output_format, 100000)
    assert artifact and (artifact.startswith(b"%PDF") if output_format == "pdf" else b"12.5" in artifact)
    assert result["status"] == "requested"
    assert report_service.authorize_generation.await_count == 2
    report_service._repo.get_by_idempotency_key.return_value = record
    replay = await report_service.generate_report(**{**args, "correlation_id": "req_retry/27"})
    assert replay["idempotent_replay"] and replay["correlation_id"] == expected
    sources.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


async def test_invalid_report_id_precedes_authority_sources_and_mutation(report_service, mock_db):
    _, args = arguments("x" * 129)
    with pytest.raises(HTTPException) as error:
        await report_service.generate_report(**args)
    assert error.value.status_code == 400
    report_service.authorize_generation.assert_not_awaited()
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()


async def test_report_http_opaque_header_with_current_authority(
    report_service, mock_db, monkeypatch, tenant_auth,
):
    token, _ = tenant_auth.issue(user_id=str(uuid.UUID(int=27)), email="reports@example.com",
                                roles=["Admin"], permissions=["read:telemetry", "write:config"])
    req = request(workspace_id=str(create_authorized_workspace()))
    monkeypatch.setattr(ReportRepository, "get_by_idempotency_key", AsyncMock(return_value=None))
    monkeypatch.setattr("app.modules.report.service.ReportSources.snapshot", AsyncMock(return_value=snapshot(req)))
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: tenant_auth.redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/reports/generate", json=req.model_dump(mode="json"), headers={
                "X-Request-ID": "req_report_http/27", "Authorization": f"Bearer {token}",
            })
        assert response.status_code == 202
        assert response.json()["meta"]["request_id"] == "req_report_http/27"
        assert response.json()["meta"]["timestamp"]
        row = mock_db.add.call_args_list[0].args[0]
        assert row.snapshot["metadata"]["request_id"] == "req_report_http/27"
        assert response.json()["data"]["correlation_id"] == str(row.correlation_id)
        mock_db.commit.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()
