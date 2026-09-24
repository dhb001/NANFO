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
from tests.report_support import authorized_workspace, request, snapshot, stub_org_admission


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


async def test_acceptance_commits_snapshot_and_requested_outbox_together(
    mock_db, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "app.modules.report.service.get_settings",
        lambda: SimpleNamespace(
            REPORTS_STORAGE_PATH=str(tmp_path),
            REPORTS_MAX_BYTES=100000,
            REPORTS_MIN_FREE_BYTES=67108864,
        ),
    )
    req = request()
    svc = ReportService(db=mock_db, redis=None)
    svc.authorize_generation = AsyncMock(return_value=authorized_workspace())
    svc._repo.get_by_idempotency_key = AsyncMock(return_value=None)
    stub_org_admission(svc, workspaces=[req.workspace_id])
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
    # C26: pre-check before the source reads, then the locked authoritative check.
    assert svc._repo.storage_usage.await_count == 2
    svc._repo.lock_org_storage.assert_awaited_once()


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


# ---------------------------------------------------------------- ADR-028 ---


class CapturingSession:
    def __init__(self, rows):
        self.rows, self.statements = rows, []

    async def execute(self, statement):
        self.statements.append(statement)
        from unittest.mock import MagicMock

        result = MagicMock()
        result.all.return_value = self.rows
        return result


async def test_history_projects_summary_columns_and_never_loads_snapshots():
    # Regression: history loaded full (up to 1 MiB) snapshots for every row.
    from sqlalchemy.dialects import postgresql

    from app.modules.report.repository import ReportRepository

    empty = SimpleNamespace(total=7, report_id=None)
    db = CapturingSession([empty])
    rows, total = await ReportRepository(db).history(uuid.uuid4(), "user", 3, 5)
    assert rows == [] and total == 7  # exact total even for an empty page
    text = str(db.statements[0].compile(dialect=postgresql.dialect()))
    select_list = text.split("FROM", 1)[0]
    assert "snapshot_summary" in select_list and "page_rows.snapshot," not in select_list
    assert "jsonb_each" in text and "jsonb_array_length" in text
    assert "reports.snapshot," not in text  # only the summary expression reads it
    assert "LIMIT %(param_1)s OFFSET %(param_2)s" in text
    assert text.rstrip().endswith("ORDER BY page_rows.requested_at DESC, page_rows.report_id DESC")


async def test_history_serializes_summary_rows_without_hashing_snapshots(mock_db):
    from app.modules.report import artifacts

    workspace, user, report_id, artifact_id = uuid.uuid4(), str(uuid.uuid4()), uuid.uuid4(), uuid.uuid4()
    receipt = {"artifact_id": str(artifact_id), "checksum_sha256": "a" * 64, "size_bytes": 5,
               "filename": f"{report_id}-{artifact_id}.csv", "media_type": "text/csv",
               "generated_at": "2026-09-01T00:00:00+00:00", "snapshot_sha256": "b" * 64, "status_version": 3}
    receipt["receipt_sha256"] = artifacts.digest(receipt)
    now = "2026-09-01T00:00:00+00:00"
    # A summary row has no ``snapshot`` attribute at all: touching it would raise.
    row = SimpleNamespace(report_id=report_id, workspace_id=workspace, network_id=None, report_type="alerts",
        output_format="csv", status="generated", date_range={}, scope={}, filters={}, artifact_refs=[],
        error_context={}, queue_status="queued", stream_entry_id=None, warning=None, idempotency_key=None,
        correlation_id=uuid.uuid4(), requested_by_user_id=user, requested_at=now, completed_at=now,
        created_at=now, updated_at=now, artifact_version=1, status_version=3, snapshot_sha256="b" * 64,
        receipt=receipt, snapshot_summary={"alerts": {"row_count": 4, "total": 9, "truncated": True}})
    svc = ReportService(db=mock_db, redis=None)
    svc._workspace_svc.get_active_workspace = AsyncMock()
    svc._repo.history = AsyncMock(return_value=([row], 1))
    result = await svc.history(workspace_id=workspace, user_id=user, page=1, page_size=20)
    item = result["items"][0]
    assert item["status"] == "generated" and item["artifacts"][0]["filename"] == receipt["filename"]
    assert item["snapshot_summary"] == {"alerts": {"row_count": 4, "total": 9, "truncated": True}}
    assert result["total"] == 1


async def test_detail_still_verifies_the_frozen_snapshot_hash(mock_db):
    from app.modules.report.artifacts import digest

    value = snapshot()
    report_id, artifact_id, workspace, user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), str(uuid.uuid4())
    receipt = {"artifact_id": str(artifact_id), "checksum_sha256": "a" * 64, "size_bytes": 5,
               "filename": f"{report_id}-{artifact_id}.csv", "media_type": "text/csv",
               "generated_at": "2026-09-01T00:00:00+00:00", "snapshot_sha256": "c" * 64, "status_version": 3}
    receipt["receipt_sha256"] = digest(receipt)
    row = ReportRecord(report_id=report_id, workspace_id=workspace, requested_by_user_id=user, status="generated",
                       artifact_version=1, status_version=3, output_format="csv", snapshot=value,
                       snapshot_sha256="c" * 64, receipt=receipt)
    svc = ReportService(db=mock_db, redis=None)
    svc._workspace_svc.get_active_workspace = AsyncMock()
    svc._repo.get_by_id = AsyncMock(return_value=row)
    detail = await svc.get_report(report_id=report_id, workspace_id=workspace, user_id=user)
    # The recorded hash does not match the snapshot: detail refuses the artifact.
    assert detail["status"] == "failed" and detail["error"]["code"] == "REPORT_ARTIFACT_UNVERIFIED"
    with pytest.raises(HTTPException) as error:
        await svc.download_receipt(report_id=report_id, workspace_id=workspace, user_id=user)
    assert error.value.status_code == 409


def test_requested_event_carries_request_metadata_without_overriding_lifecycle_fields():
    import json
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    from app.modules.report.repository import ReportRepository

    db = SimpleNamespace(add=MagicMock())
    record = SimpleNamespace(report_id=uuid.uuid4(), workspace_id=uuid.uuid4(), network_id=None,
        report_type="alerts", output_format="csv", status="requested", status_version=1,
        snapshot_sha256="d" * 64, requested_by_user_id="user", requested_at=datetime(2026, 9, 1, tzinfo=UTC),
        artifact_refs=[], error_context={}, completed_at=None, correlation_id=uuid.uuid4())
    ReportRepository(db).enqueue(record, metadata={"request_id": "req/1", "status": "generated"})
    payload = json.loads(db.add.call_args.args[0].envelope["payload"])
    assert payload["request_id"] == "req/1" and payload["status"] == "requested"
