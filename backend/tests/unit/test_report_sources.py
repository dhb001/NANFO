"""Owner service adapter filters, omissions and credential exclusion."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.report.sources import ReportSources
from app.modules.telemetry.schemas import TelemetryRecordResponse
from tests.report_support import request


async def test_telemetry_passes_exact_time_scope_filter_and_cap(mock_db):
    req = request(report_type="telemetry", filters={"metric": "rtt", "max_rows": 1})
    row = TelemetryRecordResponse(
        record_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        network_id=uuid.uuid4(),
        workspace_id=req.workspace_id,
        metric="rtt",
        value=10,
        unit="ms",
        observed_at=datetime(2026, 8, 1, tzinfo=UTC),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        source="fixture",
        tags={"password": "not_exportable", "run_id": "fixture"},
    )
    with patch(
        "app.modules.report.sources.TelemetryQueryService.get_history",
        AsyncMock(return_value=SimpleNamespace(items=[row], total=2)),
    ) as history:
        result = await ReportSources(mock_db, None).snapshot(req, str(uuid.uuid4()))
    section = result["sections"]["telemetry"]
    assert section["truncated"] and section["total"] == 2
    assert "not_exportable" not in str(result)
    assert section["rows"][0]["provenance"] == {"run_id": "fixture"}
    assert history.await_args.kwargs == {
        "workspace_id": req.workspace_id,
        "network_id": None,
        "metric": "rtt",
        "page": 1,
        "page_size": 1,
        "start_time": req.date_range.start,
        "end_time": req.date_range.end,
    }


@pytest.mark.parametrize("section", ["intent", "simulation"])
async def test_explicit_id_network_and_date_scope(mock_db, section):
    identity = uuid.uuid4()
    req = request(
        report_type=section,
        network_id=str(uuid.uuid4()),
        scope={f"{section}_ids": [str(identity)]},
    )
    row = {
        f"{section}_id": str(identity),
        "network_id": str(uuid.uuid4()),
        "requested_at": "2026-08-01T01:00:00+00:00",
    }
    target = (
        "IntentExecutionService.get_intent_detail"
        if section == "intent"
        else "SimulationStartService.get_simulation_detail"
    )
    with patch("app.modules.report.sources." + target, AsyncMock(return_value=row)):
        with pytest.raises(HTTPException) as error:
            await ReportSources(mock_db, None).snapshot(req, str(uuid.uuid4()))
        assert error.value.status_code == 404
        row["network_id"] = str(req.network_id)
        row["requested_at"] = "2026-08-03T01:00:00+00:00"
        result = await ReportSources(mock_db, None).snapshot(req, str(uuid.uuid4()))
    assert result["sections"][section]["rows"] == []
    assert result["sections"][section]["omissions"] == [
        f"{identity}:outside_date_range"
    ]


async def test_empty_id_section_is_explicit(mock_db):
    result = await ReportSources(mock_db, None).snapshot(
        request(report_type="intent"), str(uuid.uuid4())
    )
    assert result["sections"]["intent"]["omissions"] == [
        "explicit_ids_required_no_discovery"
    ]


async def test_alert_section_filters_in_alert_sql_and_reports_exact_total(mock_db):
    # Regression: 500 newest alerts were fetched and date/network-filtered in Python,
    # so older in-range alerts vanished and the total was unknown.
    from app.modules.alert.schemas import AlertListResponse, AlertRecordResponse

    network = uuid.uuid4()
    req = request(report_type="alerts", network_id=str(network), filters={"alert_status": "active", "max_rows": 2})
    created = datetime(2026, 8, 1, 6, tzinfo=UTC)
    item = AlertRecordResponse(alert_id=uuid.uuid4(), alert_key="secret-key", source="telemetry", status="active",
        severity="warning", correlation_id=uuid.uuid4(), payload={"value": 91.5, "unit": "%", "password": "x"},
        acknowledged_by_user_id=None, resolved_by_user_id=None, acknowledged_at=None, resolved_at=None,
        created_at=created, updated_at=created)
    listing = AsyncMock(return_value=AlertListResponse(items=[item, item], total=37, status_counts={"active": 37}))
    with patch("app.modules.report.sources.AlertService.list_alerts", listing):
        result = await ReportSources(mock_db, None).snapshot(req, "user-1")
    kwargs = listing.await_args.kwargs
    assert kwargs["limit"] == 2 and kwargs["network_id_filter"] == network
    assert kwargs["created_from"] == req.date_range.start and kwargs["created_before"] == req.date_range.end
    assert kwargs["status_filter"] == "active" and kwargs["requested_workspace_id"] == req.workspace_id
    section = result["sections"]["alerts"]
    assert section["total"] == 37 and section["truncated"] is True and len(section["rows"]) == 2
    assert section["rows"][0]["measurement"] == {"value": 91.5, "unit": "%"}
    assert "secret-key" not in str(section) and "password" not in str(section)
    assert section["omissions"] == ["arbitrary_payload"]
