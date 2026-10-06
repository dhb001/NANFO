"""Runtime adapter contract, demo/synthetic adapters and the adapter factory.

Only ``EmulationTelemetryAdapter`` (emulation mode) and the measured SNMP adapter
(``snmp.py``, composed separately) produce measurements. Every other adapter here
is either an empty production stub or a *demo* adapter that fabricates labelled
synthetic samples (``tags.synthetic=true``, ``tags.execution_mode=demo``) and is
refused outside ``EXECUTION_MODE=demo``. The demo adapters that mimic SNMP/gRPC
shapes are named ``Demo*`` so no protocol collector is implied by a class name.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RuntimeTelemetryAdapter(ABC):
    """Runtime adapter interface for production telemetry poll actions."""

    @abstractmethod
    async def poll(self) -> list[dict[str, Any]]:
        """Collect a batch of raw telemetry samples from the runtime adapter."""

    async def acknowledge_batch(self, samples: list[dict[str, Any]]) -> None:
        """Optional adapter checkpoint after every sample has been published."""


def _require_demo_mode() -> None:
    if get_settings().EXECUTION_MODE != "demo":
        raise ValueError("Synthetic runtime telemetry is only available in demo mode")


def _build_deterministic_runtime_sample(
    *,
    sample_key: str,
    metric: str,
    value: float,
    unit: str,
    source: str,
    adapter_mode: str,
    extra_tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    _require_demo_mode()
    tags = {
        "adapter_mode": adapter_mode,
        "sample_key": sample_key,
        "synthetic": True,
        "execution_mode": "demo",
    }
    if extra_tags:
        tags.update(extra_tags)

    return {
        "device_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{sample_key}:device")),
        "network_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{sample_key}:network")),
        "workspace_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{sample_key}:workspace")),
        "metric": metric,
        "value": value,
        "unit": unit,
        "source": source,
        "observed_at": datetime.now(UTC).isoformat(),
        "tags": tags,
    }


def _coerce_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class ProductionTelemetryAdapterStub(RuntimeTelemetryAdapter):
    """Empty production adapter: wiring is production-shaped but never fabricates data."""

    async def poll(self) -> list[dict[str, Any]]:
        return []


class SeededRuntimeTelemetryAdapter(RuntimeTelemetryAdapter):
    """Demo-only adapter emitting one deterministic synthetic sample per poll."""

    def __init__(self, *, sample_key: str, metric: str, value: float, unit: str, source: str):
        self._sample_key = str(sample_key).strip() or "default"
        self._metric = str(metric).strip() or "runtime_adapter_heartbeat"
        self._value = _coerce_value(value)
        self._unit = str(unit).strip()
        self._source = str(source).strip() or "runtime_seeded"

    async def poll(self) -> list[dict[str, Any]]:
        return [_build_deterministic_runtime_sample(
            sample_key=self._sample_key, metric=self._metric, value=self._value,
            unit=self._unit, source=self._source, adapter_mode="seeded",
        )]


class DemoSNMPTelemetryAdapter(RuntimeTelemetryAdapter):
    """Demo-only synthetic samples shaped like an SNMP poll; performs no SNMP I/O."""

    def __init__(self, *, target: str, oid: str, sample_key: str, metric: str, value: float,
                 unit: str, source: str):
        self._target = str(target).strip() or "127.0.0.1"
        self._oid = str(oid).strip() or "1.3.6.1.2.1.1.3.0"
        self._sample_key = str(sample_key).strip() or "nanfo-snmp-runtime"
        self._metric = str(metric).strip() or "runtime_adapter_snmp_poll_latency_ms"
        self._value = _coerce_value(value)
        self._unit = str(unit).strip() or "ms"
        self._source = str(source).strip() or "runtime_snmp"

    async def poll(self) -> list[dict[str, Any]]:
        return [_build_deterministic_runtime_sample(
            sample_key=self._sample_key, metric=self._metric, value=self._value,
            unit=self._unit, source=self._source, adapter_mode="snmp",
            extra_tags={"target": self._target, "oid": self._oid},
        )]


class DemoGRPCTelemetryAdapter(RuntimeTelemetryAdapter):
    """Demo-only synthetic samples shaped like a gRPC poll; performs no gRPC I/O."""

    def __init__(self, *, endpoint: str, method: str, sample_key: str, metric: str, value: float,
                 unit: str, source: str):
        self._endpoint = str(endpoint).strip() or "localhost:50051"
        self._method = str(method).strip() or "TelemetryService/Poll"
        self._sample_key = str(sample_key).strip() or "nanfo-grpc-runtime"
        self._metric = str(metric).strip() or "runtime_adapter_grpc_poll_latency_ms"
        self._value = _coerce_value(value)
        self._unit = str(unit).strip() or "ms"
        self._source = str(source).strip() or "runtime_grpc"

    async def poll(self) -> list[dict[str, Any]]:
        return [_build_deterministic_runtime_sample(
            sample_key=self._sample_key, metric=self._metric, value=self._value,
            unit=self._unit, source=self._source, adapter_mode="grpc",
            extra_tags={"endpoint": self._endpoint, "method": self._method},
        )]


def build_production_runtime_adapter(
    *,
    mode: str,
    seeded_sample_key: str,
    seeded_metric: str,
    seeded_value: float,
    seeded_unit: str,
    seeded_source: str,
    snmp_target: str = "127.0.0.1",
    snmp_oid: str = "1.3.6.1.2.1.1.3.0",
    snmp_sample_key: str = "nanfo-snmp-runtime",
    snmp_metric: str = "runtime_adapter_snmp_poll_latency_ms",
    snmp_value: float = 1.0,
    snmp_unit: str = "ms",
    snmp_source: str = "runtime_snmp",
    grpc_endpoint: str = "localhost:50051",
    grpc_method: str = "TelemetryService/Poll",
    grpc_sample_key: str = "nanfo-grpc-runtime",
    grpc_metric: str = "runtime_adapter_grpc_poll_latency_ms",
    grpc_value: float = 1.0,
    grpc_unit: str = "ms",
    grpc_source: str = "runtime_grpc",
    emulation_adapter: RuntimeTelemetryAdapter | None = None,
) -> RuntimeTelemetryAdapter:
    """Select the configured adapter; ``snmp``/``grpc`` select *demo* adapters only."""
    normalized_mode = str(mode).strip().lower()
    execution_mode = get_settings().EXECUTION_MODE
    if normalized_mode == "emulation":
        from app.modules.telemetry.emulation import EmulationTelemetryAdapter

        if execution_mode != "emulation" or not isinstance(emulation_adapter, EmulationTelemetryAdapter):
            raise ValueError("Emulation telemetry requires emulation mode and a trusted snapshot adapter")
        return emulation_adapter
    if execution_mode != "demo" and normalized_mode != "stub":
        raise ValueError("No measured runtime telemetry adapter is installed for this execution mode")
    if normalized_mode == "seeded":
        return SeededRuntimeTelemetryAdapter(
            sample_key=seeded_sample_key, metric=seeded_metric, value=seeded_value,
            unit=seeded_unit, source=seeded_source,
        )
    if normalized_mode == "snmp":
        return DemoSNMPTelemetryAdapter(
            target=snmp_target, oid=snmp_oid, sample_key=snmp_sample_key, metric=snmp_metric,
            value=snmp_value, unit=snmp_unit, source=snmp_source,
        )
    if normalized_mode == "grpc":
        return DemoGRPCTelemetryAdapter(
            endpoint=grpc_endpoint, method=grpc_method, sample_key=grpc_sample_key, metric=grpc_metric,
            value=grpc_value, unit=grpc_unit, source=grpc_source,
        )
    if normalized_mode != "stub":
        logger.warning(
            "telemetry_runtime_adapter_mode_invalid",
            runtime_adapter_mode=normalized_mode,
            fallback_mode="stub",
        )
    return ProductionTelemetryAdapterStub()
