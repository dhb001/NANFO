"""Deterministic report requests and real frozen render inputs."""

import uuid

from app.modules.report.schemas import GenerateReportRequest


def request(**overrides):
    return GenerateReportRequest.model_validate(
        {
            "workspace_id": str(uuid.uuid4()),
            "report_type": "executive_summary",
            "format": "csv",
            "date_range": {
                "start": "2026-08-01T00:00:00Z",
                "end": "2026-08-02T00:00:00Z",
            },
            **overrides,
        }
    )


def snapshot(req=None):
    return {
        "version": 1,
        "request": (req or request()).model_dump(mode="json"),
        "sections": {
            "telemetry": {
                "rows": [{"metric": "rtt_ms", "value": 12.5, "unit": "ms"}],
                "total": 1,
                "truncated": False,
                "omissions": [],
            }
        },
    }


REPORT_ORG = uuid.UUID(int=0xC26)


def authorized_workspace(org_id=REPORT_ORG):
    """What ``ReportService.authorize_generation`` returns: the workspace and its organisation."""
    from types import SimpleNamespace

    return SimpleNamespace(org_id=org_id)


def stub_org_admission(service, *, workspaces=(), used=0):
    """Mock-DB stand-ins for the C26 organisation storage admission (owner reads + usage)."""
    from unittest.mock import AsyncMock

    service._workspace_svc.list_accessible_workspace_ids = AsyncMock(return_value=list(workspaces))
    service._repo.lock_org_storage = AsyncMock()
    service._repo.storage_usage = AsyncMock(return_value=used)
    return service
