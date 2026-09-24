"""Read-only telemetry health (ADR-028 C12): no evaluation, no publication, no full count.

``get_health`` combines ingest lag, pipeline counters, a cached record-count
estimate and the SLO state persisted by the collector-side evaluator. Nothing on
this path writes SLO state or emits events, so concurrent readers, readers in
different tenants and polling frequency cannot influence alerting.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.core.logging import get_logger
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.repository import TelemetryRecordRepository
from app.modules.telemetry.schemas import TelemetryHealthResponse, TelemetrySLOHealth
from app.modules.telemetry.slo import rules
from app.modules.telemetry.slo.store import SLOStateStore, TelemetrySLOSettings
from app.modules.telemetry.validation import MAX_FUTURE_SKEW, utc_now

logger = get_logger(__name__)

TOTAL_RECORDS_CACHE_KEY = "telemetry:health:total_records:v1"
TOTAL_RECORDS_CACHE_SECONDS = 60

_ZERO_COUNTERS = {
    "ingested_events": 0, "persisted_events": 0, "fanout_events": 0, "dropped_events": 0,
    "runtime_exhausted_cycles": 0, "runtime_exhausted_streak": 0,
    "runtime_sustained_failure_windows": 0, "runtime_sustained_failure_active": 0,
    "runtime_adapter_last_batch_size": 0, "runtime_adapter_invalid_samples": 0,
    "runtime_adapter_dropped_samples": 0, "runtime_adapter_ingest_attempts": 0,
    "runtime_adapter_ingest_failures": 0, "runtime_adapter_anomaly_streak": 0,
    "runtime_adapter_slo_alert_active": 0,
}


async def read_slo_health(
    store: SLOStateStore, *, settings: TelemetrySLOSettings, now: datetime,
) -> TelemetrySLOHealth:
    """Project persisted evaluator state; ``unavailable`` if never evaluated."""
    state = await store.load()
    interval = settings.interval_seconds
    if state is None or state.evaluated_at is None:
        return TelemetrySLOHealth(status="unavailable", evaluation_interval_seconds=interval, stale=True,
                                  thresholds=dict(rules.THRESHOLDS))
    age = (now - state.evaluated_at).total_seconds()
    window = state.window
    return TelemetrySLOHealth(
        status=state.severity,
        severity_reason=state.severity_reason,
        alert_active=state.alert_active,
        anomaly_reason_flags=list(state.anomaly_reason_flags),
        anomaly_streak=state.anomaly_streak,
        evaluated_at=state.evaluated_at,
        evaluation_interval_seconds=interval,
        stale=age > interval * settings.stale_after_intervals,
        window=window.model_dump() if window is not None else None,
        trend=rules.trend_summary(state.trend),
        thresholds=dict(rules.THRESHOLDS),
    )


class TelemetryHealthReader:
    def __init__(
        self,
        repo: TelemetryRecordRepository,
        counter_service: TelemetryHealthCounterService | None,
        *,
        slo_settings: TelemetrySLOSettings | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._repo = repo
        self._counters = counter_service
        self._slo_settings = slo_settings
        self._clock = clock

    async def read(self) -> TelemetryHealthResponse:
        now = self._clock()
        latest_observed_at = await self._repo.get_latest_observed_at(not_after=now + MAX_FUTURE_SKEW)
        counters = await self._counter_snapshot()
        dropped_events = counters["dropped_events"]
        sustained_failure = counters.get("runtime_sustained_failure_active", 0) > 0
        slo = await self._slo(now)
        if latest_observed_at is None:
            return TelemetryHealthResponse(
                status="degraded" if sustained_failure else "unavailable",
                ingest_lag_ms=None, dropped_events=dropped_events, latest_observed_at=None,
                total_records=0, slo=slo,
            )
        total_records, estimated = await self._total_records()
        lag_ms = int(max((now - latest_observed_at).total_seconds() * 1000, 0))
        return TelemetryHealthResponse(
            status="degraded" if sustained_failure else "ok",
            ingest_lag_ms=lag_ms, dropped_events=dropped_events, latest_observed_at=latest_observed_at,
            total_records=total_records, total_records_estimated=estimated, slo=slo,
        )

    async def _counter_snapshot(self) -> dict[str, int]:
        if self._counters is None:
            return dict(_ZERO_COUNTERS)
        try:
            return {**_ZERO_COUNTERS, **await self._counters.get_snapshot()}
        except Exception as exc:  # noqa: BLE001 - health degrades to zeros, never 500s
            logger.warning("telemetry_health_counter_snapshot_failed", error_code="health_counters_unavailable",
                           error_type=type(exc).__name__)
            return dict(_ZERO_COUNTERS)

    async def _slo(self, now: datetime) -> TelemetrySLOHealth | None:
        if self._counters is None:
            return None
        try:
            settings = self._slo_settings or TelemetrySLOSettings()
            return await read_slo_health(SLOStateStore(self._counters.redis), settings=settings, now=now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("telemetry_health_slo_state_unavailable", error_code="health_slo_state_unavailable",
                           error_type=type(exc).__name__)
            return None

    async def _total_records(self) -> tuple[int, bool]:
        redis = self._counters.redis if self._counters is not None else None
        cached = await self._cached_total(redis)
        if cached is not None:
            return cached
        total, estimated = await self._repo.estimate_total_records()
        if redis is not None:
            try:
                await redis.set(TOTAL_RECORDS_CACHE_KEY, json.dumps({"total": total, "estimated": estimated}),
                                ex=TOTAL_RECORDS_CACHE_SECONDS)
            except Exception as exc:  # noqa: BLE001
                logger.warning("telemetry_health_total_cache_write_failed", error_code="health_total_cache_unavailable",
                               error_type=type(exc).__name__)
        return total, estimated

    @staticmethod
    async def _cached_total(redis: Any) -> tuple[int, bool] | None:
        if redis is None:
            return None
        try:
            raw = await redis.get(TOTAL_RECORDS_CACHE_KEY)
            if raw is None:
                return None
            data = json.loads(raw)
            return max(int(data["total"]), 0), bool(data["estimated"])
        except Exception as exc:  # noqa: BLE001 - recompute on any cache problem
            logger.warning("telemetry_health_total_cache_read_failed", error_code="health_total_cache_unavailable",
                           error_type=type(exc).__name__)
            return None
