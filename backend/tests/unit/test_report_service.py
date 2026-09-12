"""Report acceptance, owner authorization, strict schemas and truthful receipts."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.report.models import ReportRecord
from app.modules.report.schemas import GenerateReportRequest
from app.modules.report.service import ReportService
from tests.report_support import request, snapshot


def kwargs(req, user=None):
    data = req.model_dump(mode="json")
    output_format = data.pop("format")
    return {
        **data,
        "workspace_id": req.workspace_id,
        "network_id": req.network_id,
        "output_format": output_format,
        "fail_generation": False,
        "idempotency_key": "report-unit",
        "correlation_id": str(uuid.uuid4()),
        "requested_by_user_id": user or str(uuid.uuid4()),
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"report_type": "arbitrary"},
        {"format": "xlsx"},
        {"scope": {"path": "/tmp/a"}},
        {"filters": {"kpi": "latency"}},
        {"filters": {"max_rows": 501}},
        {"filters": {"max_rows": True}},
        {"scope": {"intent_ids": [str(uuid.uuid4())] * 21}},
        {"date_range": {"start": "2026-08-01", "end": "2026-08-02"}},
        {
            "date_range": {
                "start": "2026-08-01T00:00:00Z",
                "end": "2026-09-02T00:00:00Z",
            }
        },
        {
            "date_range": {
                "start": "2026-08-01T00:00:00Z",
                "end": "2026-08-01T00:00:00Z",
            }
        },
        {"report_type": "alerts", "filters": {"metric": "rtt"}},
        {"report_type": "telemetry", "filters": {"alert_status": "active"}},
        {"report_type": "telemetry", "scope": {"intent_ids": [str(uuid.uuid4())]}},
    ],
)
def test_strict_supported_request(overrides):
    with pytest.raises(ValidationError):
        request(**overrides)


async def test_acceptance_commits_snapshot_and_requested_outbox_together(mock_db):
    req = request()
    svc = ReportService(db=mock_db, redis=None)
    svc.authorize_generation = AsyncMock()
    svc._repo.get_by_idempotency_key = AsyncMock(return_value=None)
    args = kwargs(req)
    args.pop("format", None)
    with patch(
        "app.modules.report.service.ReportSources.snapshot",
        AsyncMock(return_value=snapshot(req)),
    ):
        result = await svc.generate_report(**args)
    assert result["status"] == "requested"
    assert result["queue_status"] == "outbox_pending"
    assert result["snapshot_summary"]["telemetry"]["row_count"] == 1
    assert mock_db.commit.await_count == 1
    assert mock_db.add.call_count == 2
    record, event = [call.args[0] for call in mock_db.add.call_args_list]
    assert record.snapshot_sha256 == result["snapshot_sha256"]
    assert event.envelope["event_type"] == "report.requested"
    assert svc.authorize_generation.await_count == 2


async def test_replay_same_owner_and_filters_without_source_reads(mock_db):
    req = request()
    args = kwargs(req)
    args.pop("format", None)
    row = ReportRecord(
        **{
            key: value
            for key, value in args.items()
            if key not in {"fail_generation", "output_format"}
        },
        output_format=req.format,
        report_id=uuid.uuid4(),
        status="requested",
        artifact_version=1,
        status_version=1,
    )
    svc = ReportService(db=mock_db, redis=None)
    svc.authorize_generation = AsyncMock()
    svc._repo.get_by_idempotency_key = AsyncMock(return_value=row)
    result = await svc.generate_report(**args)
    assert result["idempotent_replay"]
    for change in (
        {"requested_by_user_id": str(uuid.uuid4())},
        {"filters": {"max_rows": 5}},
    ):
        with pytest.raises(HTTPException) as error:
            await svc.generate_report(**{**args, **change})
        assert error.value.status_code == 409


async def test_history_and_detail_require_membership_and_owner(mock_db):
    svc = ReportService(db=mock_db, redis=None)
    svc._workspace_svc.get_active_workspace = AsyncMock()
    row = SimpleNamespace(
        workspace_id=uuid.uuid4(), requested_by_user_id=str(uuid.uuid4())
    )
    svc._repo.get_by_id = AsyncMock(return_value=row)
    with pytest.raises(HTTPException) as error:
        await svc.get_report(
            report_id=uuid.uuid4(),
            workspace_id=row.workspace_id,
            user_id=str(uuid.uuid4()),
        )
    assert error.value.status_code == 404
    svc._workspace_svc.get_active_workspace.side_effect = HTTPException(403)
    with pytest.raises(HTTPException):
        await svc.history(
            workspace_id=row.workspace_id,
            user_id=row.requested_by_user_id,
            page=1,
            page_size=20,
        )


def test_legacy_generated_artifacts_masked():
    row = ReportRecord(
        report_id=uuid.uuid4(),
        status="generated",
        artifact_version=0,
        status_version=0,
        output_format="pdf",
        artifact_refs=[{"uri": "s3://fake/report.pdf"}],
    )
    result = ReportService._serialize_report(row, idempotent_replay=False)
    assert result["status"] == "failed" and result["artifacts"] == []


async def test_consumer_never_advances_or_renders(mock_db):
    svc = ReportService(db=mock_db, redis=None)
    await svc.process_requested_event(
        {"event_type": "report.requested", "payload": {"report_id": str(uuid.uuid4())}}
    )
    mock_db.execute.assert_not_called()
    mock_db.commit.assert_not_called()


def test_utc_normalization():
    req = request(
        date_range={
            "start": "2026-08-01T03:00:00+03:00",
            "end": "2026-08-02T03:00:00+03:00",
        }
    )
    assert req.date_range.start.hour == 0
    assert (
        GenerateReportRequest.model_validate(req.model_dump()).date_range
        == req.date_range
    )
