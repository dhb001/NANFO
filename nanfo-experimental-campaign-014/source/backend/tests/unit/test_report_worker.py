import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.modules.report.artifacts import digest
from app.modules.report.worker import ReportWorker
from tests.report_support import snapshot


async def test_worker_revoked_actor_fails_without_rendering(mock_db, tmp_path):
    value = snapshot()
    row = SimpleNamespace(
        snapshot=value,
        snapshot_sha256=digest(value),
        workspace_id=uuid.uuid4(),
        network_id=None,
        requested_by_user_id=str(uuid.uuid4()),
    )

    def sessions():
        return mock_db

    mock_db.__aenter__.return_value = mock_db
    settings = SimpleNamespace(
        REPORTS_LEASE_SECONDS=30,
        REPORTS_MAX_BYTES=100000,
        REPORTS_STORAGE_PATH=str(tmp_path),
    )
    with (
        patch(
            "app.modules.report.worker.ReportRepository.claim",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.modules.report.worker.ReportRepository.finish", AsyncMock()
        ) as finish,
        patch(
            "app.modules.report.worker.ReportService.authorize_generation",
            AsyncMock(side_effect=HTTPException(403)),
        ),
        patch("app.modules.report.worker.render") as renderer,
    ):
        assert await ReportWorker(
            sessions=sessions, redis=None, settings=settings
        ).run_one()
    renderer.assert_not_called()
    assert finish.await_args.kwargs["error"]["code"] == "REPORT_AUTHORITY_REVOKED"


async def test_worker_no_job_is_idle(mock_db):
    mock_db.__aenter__.return_value = mock_db
    with patch(
        "app.modules.report.worker.ReportRepository.claim", AsyncMock(return_value=None)
    ):
        assert not await ReportWorker(sessions=lambda: mock_db, redis=None).run_one()
