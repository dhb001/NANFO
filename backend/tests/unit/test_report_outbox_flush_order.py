"""A new report and its first outbox row flush parent-first (ADR-028 0030 FK).

``fk_report_outbox_report`` makes ``report_outbox.report_id`` reference ``reports``.
The report request path stages both rows in one unit of work, so the ORM must
INSERT the report before the outbox row. Only the statement order is observed:
the first INSERT is captured and aborted, so no database or schema is needed.
The report service module is imported so its telemetry-reference flush guard is
installed exactly as in production (the snapshot carries no telemetry rows).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import MANYTOONE, Session

import app.modules.report.service  # noqa: F401 - installs the production flush guard
from app.modules.report.artifacts import digest
from app.modules.report.models import ReportOutbox, ReportRecord
from app.modules.report.repository import ReportRepository
from tests.report_support import snapshot


class _FirstInsert(Exception):
    pass


def _record() -> ReportRecord:
    value = snapshot()
    value["sections"]["telemetry"].update(rows=[], total=0)
    return ReportRecord(
        report_id=uuid.uuid4(), workspace_id=uuid.uuid4(), requested_by_user_id=str(uuid.uuid4()),
        report_type="executive_summary", output_format="csv", status="requested", artifact_version=1,
        status_version=1, snapshot=value, snapshot_sha256=digest(value), date_range=value["request"]["date_range"],
        scope=value["request"]["scope"], filters=value["request"]["filters"], requested_at=datetime.now(UTC),
        artifact_refs=[], error_context={}, correlation_id=uuid.uuid4(), queue_status="outbox_pending",
    )


def _first_inserted_table(stage) -> str:
    engine = create_engine("sqlite://")
    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT"):
            seen.append(statement.split()[2].strip('"'))
            raise _FirstInsert

    with Session(engine) as session:
        stage(session)
        with pytest.raises(_FirstInsert):
            session.flush()
    engine.dispose()
    return seen[0]


def test_outbox_row_references_report_through_a_many_to_one_ordering_dependency():
    relationship = ReportOutbox.__mapper__.relationships["report"]
    assert relationship.direction is MANYTOONE and not relationship.viewonly
    assert relationship.mapper.class_ is ReportRecord


def test_request_path_inserts_the_report_before_its_first_outbox_row():
    def stage(session):
        record = _record()
        # Exactly the ReportService request path: add the report, stage its event.
        session.add(record)
        ReportRepository(session).enqueue(record)

    assert _first_inserted_table(stage) == "reports"


def test_outbox_row_staged_first_still_flushes_after_its_report():
    def stage(session):
        record = _record()
        session.add(ReportOutbox(event_id=uuid.uuid4(), report_id=record.report_id, status_version=1, envelope={}))
        session.add(record)

    assert _first_inserted_table(stage) == "reports"
