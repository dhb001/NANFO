"""Filesystem pressure refuses new artifacts, never deletes existing evidence."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.report.artifacts import ArtifactStore, ReportCapacityError
from app.modules.report.service import ReportService
from app.modules.report.worker import ReportWorker
from app.modules.report.artifacts import digest
from tests.report_support import request, snapshot
from tests.unit.test_report_service import kwargs


@pytest.mark.parametrize(
    "available,inodes,ready", [(110, 1, True), (109, 1, False), (110, 0, False)]
)
def test_capacity_reserves_full_artifact(
    tmp_path, monkeypatch, available, inodes, ready
):
    monkeypatch.setattr(
        "os.fstatvfs",
        lambda fd: SimpleNamespace(f_bavail=available, f_frsize=1, f_favail=inodes),
    )
    store = ArtifactStore(tmp_path, 10)
    assert store.capacity(100)["ready"] is ready
    if not ready:
        with pytest.raises(ReportCapacityError):
            store.write(uuid.uuid4(), uuid.uuid4(), "csv", b"data", min_free_bytes=100)
        assert list(tmp_path.iterdir()) == []


async def test_admission_refuses_before_snapshot_or_commit(mock_db):
    service = ReportService(db=mock_db, redis=None)
    service.authorize_generation = AsyncMock()
    service._repo.get_by_idempotency_key = AsyncMock(return_value=None)
    with (
        patch.object(
            ArtifactStore, "require_capacity", side_effect=ReportCapacityError
        ),
        patch(
            "app.modules.report.service.ReportSources.snapshot", new_callable=AsyncMock
        ) as source,
    ):
        with pytest.raises(HTTPException) as error:
            await service.generate_report(**kwargs(request()))
    assert error.value.status_code == 503
    source.assert_not_called()
    mock_db.commit.assert_not_called()


async def test_worker_capacity_failure_never_renders(mock_db, tmp_path):
    value = snapshot()
    row = SimpleNamespace(
        snapshot=value,
        snapshot_sha256=digest(value),
        workspace_id=uuid.uuid4(),
        network_id=None,
        requested_by_user_id=str(uuid.uuid4()),
    )
    mock_db.__aenter__.return_value = mock_db
    settings = SimpleNamespace(
        REPORTS_LEASE_SECONDS=30,
        REPORTS_STORAGE_PATH=str(tmp_path),
        REPORTS_MAX_BYTES=10000,
        REPORTS_MIN_FREE_BYTES=67108864,
    )
    with (
        patch(
            "app.modules.report.worker.ReportRepository.claim",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.modules.report.worker.ReportService.authorize_generation", AsyncMock()
        ),
        patch("app.modules.report.worker.ReportSources.revalidate", AsyncMock()),
        patch.object(
            ArtifactStore, "require_capacity", side_effect=ReportCapacityError
        ),
        patch(
            "app.modules.report.worker.ReportRepository.finish", AsyncMock()
        ) as finish,
        patch("app.modules.report.worker.render") as render,
    ):
        assert await ReportWorker(
            sessions=lambda: mock_db, redis=None, settings=settings
        ).run_one()
    render.assert_not_called()
    assert finish.await_args.kwargs["error"]["code"] == "REPORT_STORAGE_UNAVAILABLE"
