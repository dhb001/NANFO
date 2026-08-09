"""Integration tests for telemetry startup/lifecycle wiring (VS2 Step 5)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_startup_starts_and_stops_telemetry_collector():
    collector = AsyncMock()
    collector.start = AsyncMock()
    collector.stop = AsyncMock()

    with (
        patch("app.main.TelemetryCollectorRunner", return_value=collector),
        patch("app.main.TelemetryIngestionService") as _svc,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/health")

    assert response.status_code == 200
    collector.start.assert_awaited_once()
    collector.stop.assert_awaited_once()


def test_startup_continues_if_telemetry_collector_start_fails():
    collector = AsyncMock()
    collector.start = AsyncMock(side_effect=RuntimeError("telemetry init failed"))
    collector.stop = AsyncMock()

    with (
        patch("app.main.TelemetryCollectorRunner", return_value=collector),
        patch("app.main.TelemetryIngestionService") as _svc,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/health")

    assert response.status_code == 200
    collector.start.assert_awaited_once()
    collector.stop.assert_not_awaited()
