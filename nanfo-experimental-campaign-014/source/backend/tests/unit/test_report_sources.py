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
