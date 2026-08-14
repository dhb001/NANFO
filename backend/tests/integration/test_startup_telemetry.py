"""Integration tests for telemetry startup/lifecycle wiring (VS2 Step 5)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


def test_startup_starts_and_stops_telemetry_collector():
    collector = AsyncMock()
    collector.start = AsyncMock()
    collector.start_with_retry = AsyncMock(return_value=True)
    collector.start_runtime_loop = AsyncMock()
    collector.stop = AsyncMock()

    with (
        patch("app.main.TelemetryCollectorRunner", return_value=collector),
        patch("app.main.TelemetryIngestionService") as _svc,
        patch("app.main.build_production_runtime_adapter") as mock_build_adapter,
        patch("app.main.build_runtime_poll_action", return_value=AsyncMock()) as mock_build_poll,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/health")

    assert response.status_code == 200
    collector.start_with_retry.assert_awaited_once()
    collector.start.assert_not_awaited()
    collector.start_runtime_loop.assert_awaited_once()
    collector.stop.assert_awaited_once()

    runtime_loop_kwargs = collector.start_runtime_loop.await_args.kwargs
    assert runtime_loop_kwargs["poll_action"] is mock_build_poll.return_value
    mock_build_adapter.assert_called_once()
    mock_build_poll.assert_called_once_with(
        collector_runner=collector,
        adapter=mock_build_adapter.return_value,
    )
    assert runtime_loop_kwargs["interval_seconds"] == main_module._TELEMETRY_COLLECTOR_RUNTIME_INTERVAL_SECONDS
    assert (
        runtime_loop_kwargs["poll_max_attempts"]
        == main_module._TELEMETRY_COLLECTOR_RUNTIME_POLL_MAX_ATTEMPTS
    )
    assert (
        runtime_loop_kwargs["poll_base_backoff_seconds"]
        == main_module._TELEMETRY_COLLECTOR_RUNTIME_POLL_BACKOFF_BASE_SECONDS
    )
    assert (
        runtime_loop_kwargs["poll_max_backoff_seconds"]
        == main_module._TELEMETRY_COLLECTOR_RUNTIME_POLL_BACKOFF_MAX_SECONDS
    )
    assert (
        runtime_loop_kwargs["runtime_sustained_failure_threshold"]
        == main_module._TELEMETRY_COLLECTOR_RUNTIME_SUSTAINED_FAILURE_THRESHOLD
    )


def test_startup_continues_if_telemetry_collector_start_fails():
    collector = AsyncMock()
    collector.start = AsyncMock()
    collector.start_with_retry = AsyncMock(return_value=False)
    collector.start_runtime_loop = AsyncMock()
    collector.stop = AsyncMock()

    with (
        patch("app.main.TelemetryCollectorRunner", return_value=collector),
        patch("app.main.TelemetryIngestionService") as _svc,
        patch("app.main.build_production_runtime_adapter") as mock_build_adapter,
        patch("app.main.build_runtime_poll_action") as mock_build_poll,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/health")

    assert response.status_code == 200
    collector.start_with_retry.assert_awaited_once()
    collector.start.assert_not_awaited()
    collector.start_runtime_loop.assert_not_awaited()
    collector.stop.assert_not_awaited()
    mock_build_adapter.assert_not_called()
    mock_build_poll.assert_not_called()


def test_startup_continues_if_runtime_loop_start_fails_and_stops_collector():
    collector = AsyncMock()
    collector.start = AsyncMock()
    collector.start_with_retry = AsyncMock(return_value=True)
    collector.start_runtime_loop = AsyncMock(side_effect=RuntimeError("runtime loop startup failed"))
    collector.stop = AsyncMock()

    with (
        patch("app.main.TelemetryCollectorRunner", return_value=collector),
        patch("app.main.TelemetryIngestionService") as _svc,
        patch("app.main.build_production_runtime_adapter") as mock_build_adapter,
        patch("app.main.build_runtime_poll_action", return_value=AsyncMock()) as mock_build_poll,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/health")

    assert response.status_code == 200
    collector.start_with_retry.assert_awaited_once()
    collector.start.assert_not_awaited()
    collector.start_runtime_loop.assert_awaited_once()
    collector.stop.assert_awaited_once()
    mock_build_adapter.assert_called_once()
    mock_build_poll.assert_called_once_with(
        collector_runner=collector,
        adapter=mock_build_adapter.return_value,
    )


def test_startup_shutdown_repeats_without_runtime_loop_lifecycle_regression():
    collector = AsyncMock()
    collector.start = AsyncMock()
    collector.start_with_retry = AsyncMock(return_value=True)
    collector.start_runtime_loop = AsyncMock()
    collector.stop = AsyncMock()

    with (
        patch("app.main.TelemetryCollectorRunner", return_value=collector),
        patch("app.main.TelemetryIngestionService") as _svc,
        patch("app.main.build_production_runtime_adapter") as mock_build_adapter,
        patch("app.main.build_runtime_poll_action", return_value=AsyncMock()) as mock_build_poll,
    ):
        for _ in range(3):
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")
            assert response.status_code == 200

    assert collector.start_with_retry.await_count == 3
    assert collector.start_runtime_loop.await_count == 3
    assert collector.stop.await_count == 3
    assert mock_build_adapter.call_count == 3
    assert mock_build_poll.call_count == 3


def test_startup_simulation_stream_is_provisioned_for_consumer_groups():
    collector = AsyncMock()
    collector.start = AsyncMock()
    collector.start_with_retry = AsyncMock(return_value=False)
    collector.start_runtime_loop = AsyncMock()
    collector.stop = AsyncMock()

    with (
        patch("app.main.TelemetryCollectorRunner", return_value=collector),
        patch("app.main.TelemetryIngestionService") as _svc,
        patch("app.main.ensure_consumer_groups", new=AsyncMock()) as mock_ensure_consumer_groups,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/health")

    assert response.status_code == 200
    mock_ensure_consumer_groups.assert_awaited_once()

    from app.events.bus import STREAM_GROUPS

    assert "stream:simulation" in STREAM_GROUPS
    assert "stream:plugin" in STREAM_GROUPS
