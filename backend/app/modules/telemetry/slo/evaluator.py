"""Periodic runtime-adapter SLO evaluator with persisted windows (ADR-028 C12).

Runs inside collector workers (``TelemetryCollectorRunner`` runtime loop and
``FleetWorker.run``), never on the health read path. Each evaluation:

1. flushes any pending alert events left by a crashed predecessor;
2. under a short Redis lock, closes one window when ``interval_seconds`` elapsed:
   counter DELTAS since the persisted baseline -> anomaly flags -> streak ->
   rollup severity -> bounded trend window -> per-dimension threshold cooldown;
3. on an alert-activity transition, records a platform-scoped
   ``alert.generated``/``alert.resolved`` with a deterministic event id in the
   state outbox, persists, then publishes (at-least-once, idempotent ids).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.events import publisher as event_publisher
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.slo import rules
from app.modules.telemetry.slo.store import (
    PendingEvent,
    SLOState,
    SLOStateStore,
    SLOWindow,
    TelemetrySLOSettings,
    is_due,
)

logger = get_logger(__name__)

_THRESHOLD_LOG_EVENTS = {
    rules.PHASE_ENTER: ("warning", "telemetry_slo_threshold_crossed"),
    rules.PHASE_EXPIRED_REEMIT: ("warning", "telemetry_slo_threshold_crossed_reemitted"),
    rules.PHASE_SUPPRESSED: ("info", "telemetry_slo_threshold_crossed_suppressed"),
    rules.PHASE_CLEARED_RECOVERY: ("info", "telemetry_slo_threshold_recovered"),
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def advance_state(state: SLOState | None, snapshot: dict[str, Any], *, now: datetime) -> SLOState:
    """Pure transition: close one evaluation window on ``state`` at ``now``."""
    previous = state or SLOState()
    current = rules.current_counters(snapshot)
    deltas, reset = rules.window_deltas(current, previous.baseline)
    window = SLOWindow(
        start=previous.evaluated_at, end=now,
        seconds=(now - previous.evaluated_at).total_seconds() if previous.evaluated_at else 0.0,
        last_batch_size=rules.non_negative_int(snapshot.get("runtime_adapter_last_batch_size", 0)),
        invalid_sample_ratio=rules.invalid_sample_ratio(
            invalid_samples=deltas["invalid_samples"], ingest_attempts=deltas["ingest_attempts"]),
        counter_reset=reset, **deltas,
    )
    flags = rules.anomaly_reason_flags(deltas)
    streak = rules.next_anomaly_streak(previous.anomaly_streak, flags)
    sustained = rules.non_negative_int(snapshot.get("runtime_sustained_failure_active", 0)) > 0
    severity, reason = rules.rollup_severity(anomaly_streak=streak, sustained_failure_active=sustained, flags=flags)
    trend = [*previous.trend, {"severity": severity, "flags": flags}][-rules.TREND_WINDOW_MAX_SIZE:]
    summary = rules.trend_summary(trend)
    cooldown, phases = {}, {}
    for dimension in rules.THRESHOLD_DIMENSIONS:
        cooldown[dimension], phases[dimension] = rules.threshold_step(
            previous.cooldown.get(dimension), crossed=rules.crossed_values(summary, dimension))

    alert_active = severity != "ok"
    episode = previous.alert_episode + (1 if alert_active and not previous.alert_active else 0)
    pending = list(previous.pending_events)
    if alert_active != previous.alert_active:
        event_type = rules.ALERT_GENERATED if alert_active else rules.ALERT_RESOLVED
        pending.append(PendingEvent(
            event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"nanfo:telemetry-slo:{previous.epoch}:{episode}:{event_type}"),
            event_type=event_type,
            # Generated and resolved events of one episode share a correlation.
            correlation_id=uuid.uuid5(uuid.NAMESPACE_URL, f"nanfo:telemetry-slo:{previous.epoch}:{episode}"),
            payload=rules.alert_payload(
                event_type=event_type, previous_active=previous.alert_active, current_active=alert_active,
                severity=severity, severity_reason=reason, flags=flags, window=window.as_payload()),
        ))
    return previous.model_copy(update={
        "sequence": previous.sequence + 1, "evaluated_at": now, "baseline": current, "window": window,
        "severity": severity, "severity_reason": reason, "anomaly_reason_flags": flags,
        "anomaly_streak": streak, "sustained_failure_active": sustained, "alert_active": alert_active,
        "alert_episode": episode, "trend": trend, "cooldown": cooldown, "threshold_phase": phases,
        "pending_events": pending,
    })


class TelemetrySLOEvaluator:
    def __init__(
        self,
        *,
        redis: aioredis.Redis,
        counter_service: TelemetryHealthCounterService | None = None,
        settings: TelemetrySLOSettings | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self._redis = redis
        self._counters = counter_service or TelemetryHealthCounterService(redis)
        self._settings = settings or TelemetrySLOSettings()
        self._clock = clock
        self._store = SLOStateStore(redis)

    @property
    def settings(self) -> TelemetrySLOSettings:
        return self._settings

    async def maybe_evaluate(self) -> SLOState | None:
        """Cheap periodic hook: evaluate only when the persisted window elapsed."""
        if not self._settings.enabled:
            return None
        state = await self._store.load()
        if state is not None and state.pending_events:
            await self._flush(state)
        if not is_due(state, now=self._clock(), interval_seconds=self._settings.interval_seconds):
            return None
        return await self.evaluate()

    async def evaluate(self, *, force: bool = False) -> SLOState | None:
        """Close one window under the evaluation lock; ``None`` if another holds it."""
        token = uuid.uuid4().hex
        if not await self._store.acquire(token, ttl_seconds=self._settings.lock_seconds):
            return None
        try:
            state = await self._store.load()
            now = self._clock()
            if not force and not is_due(state, now=now, interval_seconds=self._settings.interval_seconds):
                return None
            snapshot = await self._counters.get_snapshot()
            new_state = advance_state(state, snapshot, now=now)
            await self._store.save(new_state)
            new_state = await self._flush(new_state)
            await self._mirror_counters(new_state)
            self._log(new_state)
            return new_state
        finally:
            try:
                await self._store.release(token)
            except Exception as exc:  # noqa: BLE001 - the lock expires on its own
                logger.warning("telemetry_slo_lock_release_failed", error_code="slo_lock_release_failed",
                               error_type=type(exc).__name__)

    async def _flush(self, state: SLOState) -> SLOState:
        remaining = list(state.pending_events)
        while remaining:
            event = remaining[0]
            try:
                stream_entry_id = await event_publisher.publish_event(
                    redis=self._redis, event_type=event.event_type, source="telemetry",
                    payload=event.payload, correlation_id=str(event.correlation_id),
                    event_id=str(event.event_id),
                )
            except Exception as exc:  # noqa: BLE001 - retried by the next evaluation
                logger.warning("telemetry_slo_alert_publish_failed", error_code="slo_alert_publish_failed",
                               error_type=type(exc).__name__, event_type=event.event_type,
                               event_id=str(event.event_id))
                break
            remaining.pop(0)
            logger.info("telemetry_slo_alert_published", event_type=event.event_type, event_id=str(event.event_id),
                        correlation_id=str(event.correlation_id), stream_entry_id=stream_entry_id,
                        runbook_playbook=event.payload.get("runbook_playbook"))
        if len(remaining) != len(state.pending_events):
            state = state.model_copy(update={"pending_events": remaining})
            await self._store.save(state)
        return state

    async def _mirror_counters(self, state: SLOState) -> None:
        # Legacy counter keys stay readable for existing dashboards/snapshots.
        for update in (
            lambda: self._counters.set_runtime_adapter_anomaly_streak(state.anomaly_streak),
            lambda: self._counters.set_runtime_adapter_slo_alert_active(state.alert_active),
        ):
            try:
                await update()
            except Exception as exc:  # noqa: BLE001
                logger.warning("telemetry_slo_counter_mirror_failed", error_code="slo_counter_mirror_failed",
                               error_type=type(exc).__name__)

    @staticmethod
    def _log(state: SLOState) -> None:
        window = state.window
        log = logger.info if state.severity == "ok" else logger.warning if state.severity == "degraded" else logger.error
        log("telemetry_slo_evaluated", sequence=state.sequence, severity=state.severity,
            severity_reason=state.severity_reason, anomaly_reason_flags=state.anomaly_reason_flags,
            anomaly_streak=state.anomaly_streak, alert_active=state.alert_active,
            window_seconds=window.seconds if window else 0.0,
            ingest_attempts=window.ingest_attempts if window else 0,
            ingest_failures=window.ingest_failures if window else 0,
            invalid_samples=window.invalid_samples if window else 0,
            dropped_samples=window.dropped_samples if window else 0,
            counter_reset=window.counter_reset if window else False,
            trend=rules.trend_summary(state.trend))
        for dimension, phase in state.threshold_phase.items():
            if phase in _THRESHOLD_LOG_EVENTS:
                level, name = _THRESHOLD_LOG_EVENTS[phase]
                (logger.warning if level == "warning" else logger.info)(
                    name, threshold_dimension=dimension, cooldown_phase=phase,
                    threshold_value=rules.THRESHOLD_DIMENSIONS[dimension],
                    cooldown_evaluations=rules.THRESHOLD_CROSS_COOLDOWN_EVALUATIONS,
                    crossed_values=rules.crossed_values(rules.trend_summary(state.trend), dimension))
