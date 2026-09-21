"""Unit tests for simulation lifecycle event consumer wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.events.consumers.simulation_consumer import (
    SIMULATION_HANDLERS,
    handle_simulation_started_event,
)


def _session_context_manager(db: AsyncMock) -> AsyncMock:
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None
    return session_cm


@pytest.mark.asyncio
async def test_simulation_consumer_routes_started_event_to_terminal_service():
    event = {
        "event_type": "simulation.started",
        "correlation_id": "00000000-0000-0000-0000-000000000001",
        "payload": {"simulation_id": "00000000-0000-0000-0000-000000000010"},
    }
    db = AsyncMock()

    with (
        patch(
            "app.events.consumers.simulation_consumer.AsyncSessionLocal",
            return_value=_session_context_manager(db),
        ),
        patch("app.events.consumers.simulation_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.simulation_consumer.SimulationTerminalEventService") as mock_service,
    ):
        fake_redis = AsyncMock()
        mock_get_redis.return_value = fake_redis
        service_instance = AsyncMock()
        service_instance.process_started_event = AsyncMock()
        mock_service.return_value = service_instance

        await handle_simulation_started_event(event)

    mock_service.assert_called_once_with(db=db, redis=fake_redis)
    service_instance.process_started_event.assert_awaited_once_with(event=event)


def test_simulation_handlers_include_started_event():
    assert "simulation.started" in SIMULATION_HANDLERS
    assert SIMULATION_HANDLERS["simulation.started"] is handle_simulation_started_event
