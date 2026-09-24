"""Telemetry service facade (stable public import path).

The implementation is split by responsibility (ADR-028):

- ``runtime/adapters.py``  adapter contract, empty stub, labelled demo adapters, factory
- ``runtime/poll.py``      generic poll action (validation + guarded ingestion)
- ``runtime/runner.py``    collector lifecycle, retry/backoff, runtime loop (+ SLO hook)
- ``ingestion.py``         normalization and event publication
- ``validation.py``        canonical field parsers (aware, bounded timestamps)
- ``persistence.py``       idempotent persistence into ``telemetry_records``
- ``queries.py``           history/device read models
- ``health.py``            read-only health (never evaluates or publishes)
- ``slo/``                 periodic SLO evaluator with persisted windows

Other modules and tests keep importing from ``app.modules.telemetry.service``.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.events.publisher import publish_event
from app.modules.telemetry.ingestion import TelemetryIngestionService
from app.modules.telemetry.persistence import TelemetryPersistenceService
from app.modules.telemetry.queries import TelemetryQueryService
from app.modules.telemetry.repository import TelemetryRecordRepository
from app.modules.telemetry.runtime.adapters import (
    DemoGRPCTelemetryAdapter,
    DemoSNMPTelemetryAdapter,
    ProductionTelemetryAdapterStub,
    RuntimeTelemetryAdapter,
    SeededRuntimeTelemetryAdapter,
    build_production_runtime_adapter,
)
from app.modules.telemetry.runtime.poll import build_runtime_poll_action
from app.modules.telemetry.runtime.runner import (
    TelemetryCollector,
    TelemetryCollectorRunner,
    compute_bounded_backoff_seconds,
)
from app.modules.telemetry.slo.evaluator import TelemetrySLOEvaluator

__all__ = [
    "DemoGRPCTelemetryAdapter",
    "DemoSNMPTelemetryAdapter",
    "ProductionTelemetryAdapterStub",
    "RuntimeTelemetryAdapter",
    "SeededRuntimeTelemetryAdapter",
    "TelemetryCollector",
    "TelemetryCollectorRunner",
    "TelemetryIngestionService",
    "TelemetryPersistenceService",
    "TelemetryQueryService",
    "TelemetryRecordRepository",
    "TelemetrySLOEvaluator",
    "build_production_runtime_adapter",
    "build_runtime_poll_action",
    "compute_bounded_backoff_seconds",
    "get_settings",
    "publish_event",
]
