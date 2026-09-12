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
