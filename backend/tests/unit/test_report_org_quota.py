"""ADR-028 C26: per-organisation report storage admission (no database)."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.modules.report.artifacts import ArtifactStore, ReportCapacityError
from app.modules.report.repository import ReportRepository
from app.modules.report.service import DEFAULT_MAX_BYTES_PER_ORG, ReportService, org_storage_quota
from tests.report_support import REPORT_ORG, authorized_workspace, request, snapshot, stub_org_admission
from tests.unit.test_report_service import kwargs

MAX_BYTES, QUOTA = 100_000, 1_000_000
ORG_WORKSPACES = [uuid.UUID(int=0xC261), uuid.UUID(int=0xC262)]


@pytest.fixture
def settings(monkeypatch, tmp_path):
    value = SimpleNamespace(REPORTS_STORAGE_PATH=str(tmp_path), REPORTS_MAX_BYTES=MAX_BYTES,
                            REPORTS_MIN_FREE_BYTES=0, REPORTS_MAX_BYTES_PER_ORG=QUOTA)
    monkeypatch.setattr("app.modules.report.service.get_settings", lambda: value)
    monkeypatch.setattr(ArtifactStore, "require_capacity", lambda self, min_free: None)
    return value


def service(mock_db, *, used):
    svc = ReportService(db=mock_db, redis=None)
    svc.authorize_generation = AsyncMock(return_value=authorized_workspace())
    svc._repo.get_by_idempotency_key = AsyncMock(return_value=None)
    stub_org_admission(svc, workspaces=ORG_WORKSPACES, used=used)
    if isinstance(used, list):
        svc._repo.storage_usage = AsyncMock(side_effect=used)
    return svc


async def test_org_quota_refuses_before_source_reads_or_any_write(mock_db, settings):
    svc = service(mock_db, used=QUOTA - MAX_BYTES + 1)
    args = kwargs(request())
    with patch("app.modules.report.service.ReportSources.snapshot", new_callable=AsyncMock) as sources:
        with pytest.raises(HTTPException) as refused:
            await svc.generate_report(**args)
    assert refused.value.status_code == 507
    assert refused.value.detail["code"] == "REPORT_ORG_QUOTA_EXCEEDED"
    sources.assert_not_awaited()
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()
    # Usage spans every workspace of the organisation, reserving a full artifact per in-flight job.
    svc._workspace_svc.list_accessible_workspace_ids.assert_awaited_once_with(
        user_id=args["requested_by_user_id"], claim_org_id=REPORT_ORG)
    svc._repo.storage_usage.assert_awaited_once_with(ORG_WORKSPACES, in_flight_reserve_bytes=MAX_BYTES)
    svc._repo.lock_org_storage.assert_not_awaited()  # the pre-check never holds the org lock


async def test_org_quota_admits_exactly_up_to_one_more_full_artifact(mock_db, settings):
    svc = service(mock_db, used=QUOTA - MAX_BYTES)
    req = request()
    with patch("app.modules.report.service.ReportSources.snapshot", AsyncMock(return_value=snapshot(req))):
        result = await svc.generate_report(**kwargs(req))
    assert result["status"] == "requested"
    mock_db.commit.assert_awaited_once()
    svc._repo.lock_org_storage.assert_awaited_once_with(REPORT_ORG)
    assert svc._repo.storage_usage.await_count == 2


async def test_org_quota_is_rechecked_under_the_org_lock_after_source_reads(mock_db, settings):
    # A concurrent acceptance in the same organisation committed while sources were read.
    svc = service(mock_db, used=[0, QUOTA])
    req = request()
    order = []
    svc._repo.lock_org_storage.side_effect = lambda org: order.append("lock")
    snapshot_reads = AsyncMock(side_effect=lambda *args: order.append("sources") or snapshot(req))
    with patch("app.modules.report.service.ReportSources.snapshot", snapshot_reads):
        with pytest.raises(HTTPException) as refused:
            await svc.generate_report(**kwargs(req))
    assert refused.value.status_code == 507 and order == ["sources", "lock"]
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()


async def test_idempotent_replay_is_never_refused_by_the_org_quota(mock_db, settings):
    req = request()
    args = kwargs(req)
    svc = service(mock_db, used=QUOTA * 10)
    existing = SimpleNamespace(
        requested_by_user_id=args["requested_by_user_id"], network_id=None, report_type=req.report_type,
        output_format=req.format, date_range=req.model_dump(mode="json")["date_range"],
        scope=req.model_dump(mode="json")["scope"], filters=req.model_dump(mode="json")["filters"],
        status="requested", error_context={}, receipt=None, artifact_version=1, status_version=1,
        report_id=uuid.uuid4(), workspace_id=req.workspace_id, snapshot=snapshot(req), snapshot_sha256="0" * 64)
    svc._repo.get_by_idempotency_key = AsyncMock(return_value=existing)
    replay = await svc.generate_report(**args)
    assert replay["idempotent_replay"] is True
    svc._repo.storage_usage.assert_not_awaited()


async def test_global_reserve_is_still_checked_first(mock_db, settings, monkeypatch):
    monkeypatch.setattr(ArtifactStore, "require_capacity", lambda self, min_free: (_ for _ in ()).throw(
        ReportCapacityError("reserve exhausted")))
    svc = service(mock_db, used=0)
    with pytest.raises(HTTPException) as refused:
        await svc.generate_report(**kwargs(request()))
    assert refused.value.status_code == 503 and refused.value.detail["code"] == "REPORT_STORAGE_UNAVAILABLE"
    svc._repo.storage_usage.assert_not_awaited()


async def test_authority_without_an_organisation_fails_closed(mock_db, settings):
    svc = service(mock_db, used=0)
    svc.authorize_generation = AsyncMock(return_value=SimpleNamespace(org_id=None))
    with pytest.raises(HTTPException) as refused:
        await svc.generate_report(**kwargs(request()))
    assert refused.value.status_code == 503
    svc._repo.storage_usage.assert_not_awaited()
    mock_db.commit.assert_not_awaited()


@pytest.mark.parametrize("configured,expected", [
    (None, DEFAULT_MAX_BYTES_PER_ORG), (2_000_000, 2_000_000), (10, MAX_BYTES), ("big", DEFAULT_MAX_BYTES_PER_ORG),
    (True, DEFAULT_MAX_BYTES_PER_ORG),
])
def test_org_quota_setting_is_read_with_getattr_and_admits_at_least_one_artifact(configured, expected):
    settings = SimpleNamespace(REPORTS_MAX_BYTES=MAX_BYTES)
    if configured is not None:
        settings.REPORTS_MAX_BYTES_PER_ORG = configured
    assert org_storage_quota(settings) == expected
    assert DEFAULT_MAX_BYTES_PER_ORG == 512 * 1024 * 1024


class ScalarSession:
    def __init__(self, value):
        self.value, self.statements = value, []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.value

    async def execute(self, statement, params=None):
        self.statements.append((statement, params))


async def test_storage_usage_counts_recorded_sizes_and_reserves_in_flight_jobs():
    db = ScalarSession(1234)
    assert await ReportRepository(db).storage_usage(ORG_WORKSPACES, in_flight_reserve_bytes=MAX_BYTES) == 1234
    compiled = db.statements[0].compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).split())
    assert "coalesce(sum(CASE WHEN (reports.status = %(status_1)s) THEN CASE WHEN (jsonb_typeof(reports.receipt" in sql
    assert "CAST(reports.receipt ->> %(receipt_2)s AS NUMERIC)" in sql  # only numeric JSON sizes are cast
    assert "reports.status IN (__[POSTCOMPILE_status_2])" in sql
    assert "reports.workspace_id = ANY (%(workspace_ids_1)s::UUID[])" in sql
    assert compiled.params["jsonb_typeof_1"] == "number" and compiled.params["receipt_2"] == "size_bytes"
    assert compiled.params["status_1"] == "generated" and list(compiled.params["status_2"]) == ["requested", "running"]
    assert compiled.params["workspace_ids_1"] == sorted(ORG_WORKSPACES) and MAX_BYTES in compiled.params.values()
    single = ScalarSession(None)
    assert await ReportRepository(single).storage_usage([ORG_WORKSPACES[0]], in_flight_reserve_bytes=1) == 0
    assert "reports.workspace_id = %(workspace_id_1)s" in str(single.statements[0].compile(dialect=postgresql.dialect()))
    empty = ScalarSession(99)
    assert await ReportRepository(empty).storage_usage([], in_flight_reserve_bytes=1) == 0
    assert empty.statements == []


async def test_org_lock_is_a_transaction_scoped_advisory_lock_per_organisation():
    db = ScalarSession(None)
    await ReportRepository(db).lock_org_storage(REPORT_ORG)
    ((statement, params),) = db.statements
    assert "pg_advisory_xact_lock(hashtextextended(:key, 0))" in str(statement)
    assert params == {"key": f"report:org-storage:{REPORT_ORG}"}
