import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_default_singleton_and_independent_fleet_guard():
    settings = Settings(_env_file=None)
    assert not settings.API_REALTIME_DISTRIBUTED and not settings.TELEMETRY_FLEET_ENABLED
    for distributed in (True, False):
        settings = Settings(_env_file=None, API_REALTIME_DISTRIBUTED=distributed, TELEMETRY_FLEET_ENABLED=True)
        assert settings.TELEMETRY_FLEET_ENABLED
        assert settings.realtime_fanout_settings().lease_ttl_seconds == settings.API_REALTIME_LEASE_TTL_SECONDS


@pytest.mark.parametrize("values", [
    {"API_REALTIME_FANOUT_MAX_ENTRIES": 0},
    {"API_REALTIME_FANOUT_MAX_PAYLOAD_BYTES": 1048577},
    {"API_REALTIME_FANOUT_BATCH_SIZE": True},
    {"API_REALTIME_FANOUT_DEDUP_ENTRIES": -1},
    {"API_REALTIME_FANOUT_HEARTBEAT_SECONDS": float("nan")},
    {"API_REALTIME_FANOUT_IO_TIMEOUT_SECONDS": float("inf")},
    {"API_REALTIME_FANOUT_RETRY_SECONDS": False},
    {"API_REALTIME_FANOUT_SHUTDOWN_SECONDS": 0},
    {"API_REALTIME_FANOUT_STALE_SECONDS": 3},
    {"API_REALTIME_FANOUT_IO_TIMEOUT_SECONDS": 0.5},
    {"API_REALTIME_COLLECTOR_WATCHDOG_SECONDS": 5},
    {"TELEMETRY_FLEET_ENABLED": True, "TELEMETRY_RUNTIME_ADAPTER_MODE": "seeded"},
    {"TELEMETRY_FLEET_ENABLED": True, "TELEMETRY_RUNTIME_ADAPTER_MODE": "emulation"},
])
def test_invalid_configuration_is_rejected_even_before_runtime(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
