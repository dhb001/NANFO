"""Unit tests for report service lifecycle and queue-to-artifact behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.report.service import ReportService


def _make_report_row(
    *,
    report_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    network_id: uuid.UUID | None = None,
    report_type: str = "executive_summary",
    output_format: str = "pdf",
    status: str = "requested",
    idempotency_key: str | None = None,
):
    now = datetime.now(UTC)
    return SimpleNamespace(
        report_id=report_id or uuid.uuid4(),
        workspace_id=workspace_id or uuid.uuid4(),
        network_id=network_id,
        report_type=report_type,
        output_format=output_format,
        status=status,
        date_range={
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-08-14T00:00:00+00:00",
        },
        scope={"workspace": "all"},
        filters={"kpi": "latency"},
        artifact_refs=[],
        error_context={},
        queue_status="queued",
        stream_entry_id="900-0",
        warning=None,
        idempotency_key=idempotency_key,
        correlation_id=uuid.uuid4(),
        requested_by_user_id=str(uuid.uuid4()),
        requested_at=now,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


def _valid_date_range() -> dict[str, str]:
    return {
        "start": "2026-08-01T00:00:00+00:00",
        "end": "2026-08-14T00:00:00+00:00",
    }


async def _update_lifecycle_side_effect(report, **kwargs):
    for field, value in kwargs.items():
        setattr(report, field, value)
    return report


@pytest.mark.asyncio
async def test_generate_report_creates_record_and_publishes_requested(mock_db, fake_redis):
    service = ReportService(db=mock_db, redis=fake_redis)
    row = _make_report_row(status="requested", output_format="pdf")
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._network_repo.get_by_id = AsyncMock(return_value=None)
    service._repo.get_by_idempotency_key = AsyncMock(return_value=None)
    service._repo.create = AsyncMock(return_value=row)
    service._repo.update_lifecycle = AsyncMock(side_effect=_update_lifecycle_side_effect)

    with patch("app.modules.report.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "910-0"
        result = await service.generate_report(
            workspace_id=row.workspace_id,
            network_id=None,
            report_type="executive_summary",
            output_format="pdf",
            date_range=_valid_date_range(),
            scope={"workspace": "all"},
            filters={"kpi": "latency"},
            fail_generation=False,
            idempotency_key="rep-1",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["status"] == "requested"
    assert result["queue_status"] == "queued"
    assert result["stream_entry_id"] == "910-0"
    assert result["idempotent_replay"] is False
    assert mock_publish.await_args.kwargs["event_type"] == "report.requested"
    assert mock_db.commit.await_count == 2


@pytest.mark.asyncio
async def test_generate_report_replays_when_same_idempotency_request(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    existing = _make_report_row(
        workspace_id=workspace_id,
        report_type="executive_summary",
        output_format="pdf",
        status="generated",
        idempotency_key="rep-1",
    )
    existing.date_range = _valid_date_range()
    existing.scope = {"workspace": "all"}
    existing.filters = {"kpi": "latency"}

    service = ReportService(db=mock_db, redis=fake_redis)
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._network_repo.get_by_id = AsyncMock(return_value=None)
    service._repo.get_by_idempotency_key = AsyncMock(return_value=existing)

    result = await service.generate_report(
        workspace_id=workspace_id,
        network_id=None,
        report_type="executive_summary",
        output_format="pdf",
        date_range=_valid_date_range(),
        scope={"workspace": "all"},
        filters={"kpi": "latency"},
        fail_generation=False,
        idempotency_key="rep-1",
        correlation_id=str(uuid.uuid4()),
        requested_by_user_id=str(uuid.uuid4()),
    )

    assert result["idempotent_replay"] is True
    assert result["report_id"] == str(existing.report_id)
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_generate_report_conflict_on_idempotency_payload_drift(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    existing = _make_report_row(
        workspace_id=workspace_id,
        report_type="executive_summary",
        output_format="pdf",
        idempotency_key="rep-1",
    )
    existing.filters = {"kpi": "latency"}

    service = ReportService(db=mock_db, redis=fake_redis)
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._network_repo.get_by_id = AsyncMock(return_value=None)
    service._repo.get_by_idempotency_key = AsyncMock(return_value=existing)

    with pytest.raises(HTTPException) as exc_info:
        await service.generate_report(
            workspace_id=workspace_id,
            network_id=None,
            report_type="executive_summary",
            output_format="pdf",
            date_range=_valid_date_range(),
            scope={"workspace": "all"},
            filters={"kpi": "loss"},
            fail_generation=False,
            idempotency_key="rep-1",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "REPORT_IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_generate_report_rejects_invalid_date_range(mock_db, fake_redis):
    service = ReportService(db=mock_db, redis=fake_redis)
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._network_repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.generate_report(
            workspace_id=uuid.uuid4(),
            network_id=None,
            report_type="executive_summary",
            output_format="pdf",
            date_range={"start": "2026-08-15T00:00:00+00:00", "end": "2026-08-01T00:00:00+00:00"},
            scope={},
            filters={},
            fail_generation=False,
            idempotency_key=None,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "REPORT_DATE_RANGE_INVALID"


@pytest.mark.asyncio
async def test_generate_report_rejects_unsupported_format(mock_db, fake_redis):
    service = ReportService(db=mock_db, redis=fake_redis)
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._network_repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.generate_report(
            workspace_id=uuid.uuid4(),
            network_id=None,
            report_type="executive_summary",
            output_format="xlsx",
            date_range=_valid_date_range(),
            scope={},
            filters={},
            fail_generation=False,
            idempotency_key=None,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "REPORT_FORMAT_UNSUPPORTED"


@pytest.mark.asyncio
async def test_generate_report_rejects_missing_network(mock_db, fake_redis):
    service = ReportService(db=mock_db, redis=fake_redis)
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._network_repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.generate_report(
            workspace_id=uuid.uuid4(),
            network_id=uuid.uuid4(),
            report_type="executive_summary",
            output_format="pdf",
            date_range=_valid_date_range(),
            scope={},
            filters={},
            fail_generation=False,
            idempotency_key=None,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "REPORT_NETWORK_NOT_FOUND"


@pytest.mark.asyncio
async def test_generate_report_rejects_cross_workspace_network(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    network = SimpleNamespace(workspace_id=uuid.uuid4())

    service = ReportService(db=mock_db, redis=fake_redis)
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._network_repo.get_by_id = AsyncMock(return_value=network)

    with pytest.raises(HTTPException) as exc_info:
        await service.generate_report(
            workspace_id=workspace_id,
            network_id=uuid.uuid4(),
            report_type="executive_summary",
            output_format="pdf",
            date_range=_valid_date_range(),
            scope={},
            filters={},
            fail_generation=False,
            idempotency_key=None,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "REPORT_NETWORK_WORKSPACE_MISMATCH"


@pytest.mark.asyncio
async def test_get_report_returns_404_when_not_found(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    service = ReportService(db=mock_db, redis=fake_redis)
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_report(report_id=uuid.uuid4(), workspace_id=workspace_id, user_id=str(uuid.uuid4()))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "REPORT_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_report_returns_record_when_workspace_matches(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    record = _make_report_row(workspace_id=workspace_id, status="generated")
    record.artifact_refs = [
        {
            "artifact_id": "artifact-1",
            "uri": "s3://nanfo-reports/ws/report.pdf",
            "media_type": "application/pdf",
            "checksum_sha256": "abc",
            "size_bytes": 100,
            "generated_at": datetime.now(UTC).isoformat(),
        }
    ]

    service = ReportService(db=mock_db, redis=fake_redis)
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._repo.get_by_id = AsyncMock(return_value=record)

    result = await service.get_report(report_id=record.report_id, workspace_id=workspace_id, user_id=str(uuid.uuid4()))
    assert result["report_id"] == str(record.report_id)
    assert result["status"] == "failed"
    assert result["artifacts"] == []
    assert result["error"]["code"] == "REPORT_RENDERER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_process_requested_event_fails_without_renderer(mock_db, fake_redis):
    record = _make_report_row(status="requested", output_format="pdf")
    service = ReportService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=record)
    service._repo.update_lifecycle = AsyncMock(return_value=record)

    with patch("app.modules.report.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "950-0"
        await service.process_requested_event(
            {
                "event_type": "report.requested",
                "correlation_id": str(uuid.uuid4()),
                "payload": {
                    "report_id": str(record.report_id),
                    "fail_generation": False,
                },
            }
        )

    assert service._repo.update_lifecycle.await_count == 1
    update_kwargs = service._repo.update_lifecycle.await_args.kwargs
    assert update_kwargs["status"] == "failed"
    assert update_kwargs["queue_status"] == "queued"
    assert update_kwargs["artifact_refs"] == []
    assert mock_publish.await_args.kwargs["event_type"] == "report.failed"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_requested_event_marks_failed_with_error_context(mock_db, fake_redis):
    record = _make_report_row(status="requested", output_format="csv")
    service = ReportService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=record)
    service._repo.update_lifecycle = AsyncMock(return_value=record)

    with patch("app.modules.report.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "951-0"
        await service.process_requested_event(
            {
                "event_type": "report.requested",
                "correlation_id": str(uuid.uuid4()),
                "payload": {
                    "report_id": str(record.report_id),
                    "fail_generation": True,
                },
            }
        )

    update_kwargs = service._repo.update_lifecycle.await_args.kwargs
    assert update_kwargs["status"] == "failed"
    assert update_kwargs["artifact_refs"] == []
    assert update_kwargs["error_context"]["code"] == "REPORT_RENDERER_UNAVAILABLE"
    assert mock_publish.await_args.kwargs["event_type"] == "report.failed"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_requested_event_skips_when_already_terminal(mock_db, fake_redis):
    record = _make_report_row(status="generated")
    service = ReportService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=record)
    service._repo.update_lifecycle = AsyncMock()

    with patch("app.modules.report.service.publish_event", new_callable=AsyncMock) as mock_publish:
        await service.process_requested_event(
            {
                "event_type": "report.requested",
                "correlation_id": str(uuid.uuid4()),
                "payload": {"report_id": str(record.report_id)},
            }
        )

    service._repo.update_lifecycle.assert_not_awaited()
    mock_publish.assert_not_awaited()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_requested_event_ignores_missing_report_record(mock_db, fake_redis):
    service = ReportService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=None)

    await service.process_requested_event(
        {
            "event_type": "report.requested",
            "correlation_id": str(uuid.uuid4()),
            "payload": {"report_id": str(uuid.uuid4())},
        }
    )

    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_report_publish_failure_is_fail_open(mock_db, fake_redis):
    row = _make_report_row(status="requested")
    service = ReportService(db=mock_db, redis=fake_redis)
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._network_repo.get_by_id = AsyncMock(return_value=None)
    service._repo.get_by_idempotency_key = AsyncMock(return_value=None)
    service._repo.create = AsyncMock(return_value=row)
    service._repo.update_lifecycle = AsyncMock(side_effect=_update_lifecycle_side_effect)

    with patch("app.modules.report.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.side_effect = RuntimeError("stream unavailable")
        result = await service.generate_report(
            workspace_id=row.workspace_id,
            network_id=None,
            report_type="executive_summary",
            output_format="pdf",
            date_range=_valid_date_range(),
            scope={"workspace": "all"},
            filters={"kpi": "latency"},
            fail_generation=False,
            idempotency_key="rep-1",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["queue_status"] == "deferred"
    assert result["warning"] == "event_queue_unavailable"
