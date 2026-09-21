"""API collector composition; parent main selects this instead of the demo factory."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.telemetry.service import TelemetryIngestionService
from app.modules.telemetry.snmp import MeasuredSNMPAdapter
from app.modules.telemetry.snmp_config import SNMPBinding, SNMPCredentials, SNMPError, load_protected_json
from app.modules.telemetry.snmp_ownership import SNMPOwnerBoundary
from app.modules.telemetry.snmp_transport import NetSNMPTransport


async def build_measured_snmp_poll_action(
    *,
    settings: Settings,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    redis: Redis,
    ingestion_service: TelemetryIngestionService,
) -> Callable[[], Awaitable[None]]:
    """Preflight protected config and current write authority, without device I/O.

    Returns one stateful, serialized, guarded action for start_runtime_loop.
    Caller owns sessions/Redis/ingestion lifetimes and loop interval/retry policy.
    Both build authorization and each complete poll have the configured deadline.
    Per-request timeout stays authoritative in the pinned binding (default 2s).
    """
    if settings.TELEMETRY_RUNTIME_ADAPTER_MODE.strip().lower() != "measured_snmp":
        raise SNMPError("measured_snmp_selector_required")
    binding_path = settings.TELEMETRY_MEASURED_SNMP_BINDING_PATH
    credentials_path = settings.TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH
    if binding_path is None or credentials_path is None:
        raise SNMPError("measured_snmp_paths_required")
    timeout = settings.TELEMETRY_MEASURED_SNMP_POLL_TIMEOUT_SECONDS
    try:
        binding = load_protected_json(binding_path, SNMPBinding)
        load_protected_json(credentials_path, SNMPCredentials)
        if settings.EXECUTION_MODE != binding.execution_mode:
            raise SNMPError("execution_mode_mismatch")
        # Admit enough time for a complete successful serial collection; leave
        # strictly positive room for authorization and publication. Owner-service
        # latency can still consume that room and is bounded by the outer deadline.
        request_budget = len(binding.interfaces) * (binding.timeout_seconds + 1)
        if request_budget >= timeout:
            raise SNMPError("poll_timeout_below_transport_budget")
        if request_budget >= binding.max_pending_seconds:
            raise SNMPError("pending_ttl_below_transport_budget")
        if settings.TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS + request_budget >= binding.max_interval_seconds:
            raise SNMPError("poll_interval_exceeds_binding_rate_window")
        transport = NetSNMPTransport(credentials_path=credentials_path)
        transport.check_available()
        boundary = SNMPOwnerBoundary(binding_path=binding_path, session_factory=session_factory, redis=redis)
        async with asyncio.timeout(timeout):
            await boundary.authorize(binding, True)
        adapter = MeasuredSNMPAdapter(binding=binding, transport=transport, authorize=boundary.authorize)
    except SNMPError:
        raise
    except TimeoutError:
        raise SNMPError("measured_snmp_preflight_timeout") from None
    except Exception:
        raise SNMPError("measured_snmp_preflight_failed") from None

    async def poll_action() -> None:
        try:
            async with asyncio.timeout(timeout):
                await adapter.collect_and_publish(ingestion_service)
        except SNMPError:
            raise
        except TimeoutError:
            raise SNMPError("measured_snmp_poll_timeout") from None
        except Exception:
            # The runner logs str(exc); database/Redis exceptions can include
            # credentials. Retain pending samples and expose only a fixed code.
            raise SNMPError("measured_snmp_poll_failed") from None

    return poll_action
