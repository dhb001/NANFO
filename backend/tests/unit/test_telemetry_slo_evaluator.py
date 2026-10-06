"""Periodic runtime-adapter SLO evaluator (ADR-028 C12) against fakeredis."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.ingestion import TelemetryIngestionService
from app.modules.telemetry.runtime.runner import TelemetryCollectorRunner
from app.modules.telemetry.slo import rules
from app.modules.telemetry.slo.evaluator import TelemetrySLOEvaluator, advance_state
from app.modules.telemetry.slo.store import LOCK_KEY, STATE_KEY, SLOStateStore, TelemetrySLOSettings

START = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now

    def advance(self, seconds=30):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def counters(fake_redis):
    return TelemetryHealthCounterService(fake_redis)


def evaluator(fake_redis, counters, clock, **settings):
    return TelemetrySLOEvaluator(redis=fake_redis, counter_service=counters, clock=clock,
                                 settings=TelemetrySLOSettings(**{"interval_seconds": 30, **settings}))


async def alert_events(fake_redis):
    entries = await fake_redis.xrange("stream:alert")
    return [{**fields, "payload": json.loads(fields["payload"])} for _, fields in entries]


async def fail_ingest(counters, times=1):
    for _ in range(times):
        await counters.increment_runtime_adapter_ingest_attempt()
        await counters.increment_runtime_adapter_ingest_failure()
        await counters.increment_runtime_adapter_dropped_sample()


async def test_first_window_is_baseline_even_with_historical_failures(fake_redis, counters, clock):
    await fail_ingest(counters, times=50)  # totals accumulated before the evaluator ran
    state = await evaluator(fake_redis, counters, clock).maybe_evaluate()
    assert state.severity == "ok" and state.window.ingest_failures == 0
    assert state.baseline["ingest_failures"] == 50
    assert await alert_events(fake_redis) == []


async def test_alert_resolves_when_monotonic_counters_stop_increasing(fake_redis, counters, clock):
    """Regression: with monotonic totals the alert stayed active forever."""
    slo = evaluator(fake_redis, counters, clock)
    await slo.maybe_evaluate()
    clock.advance()
    await fail_ingest(counters)
    active = await slo.maybe_evaluate()
    assert active.severity == "degraded" and active.alert_active
    assert active.anomaly_reason_flags == ["ingest_failures_detected", "dropped_samples_detected"]
    clock.advance()
    recovered = await slo.maybe_evaluate()  # totals unchanged -> zero deltas
    assert recovered.severity == "ok" and not recovered.alert_active
    events = await alert_events(fake_redis)
    assert [event["event_type"] for event in events] == ["alert.generated", "alert.resolved"]
    generated, resolved = (event["payload"] for event in events)
    assert generated["runtime_adapter_slo_snapshot"]["ingest_failures"] == 1
    assert resolved["runtime_adapter_slo_snapshot"]["ingest_failures"] == 0
    assert resolved["runbook_playbook"] == rules.PLAYBOOK_RECOVERY
    # One episode shares its correlation; ids are deterministic per episode.
    assert events[0]["correlation_id"] == events[1]["correlation_id"]
    assert events[0]["event_id"] != events[1]["event_id"]


async def test_slo_alerts_are_platform_scoped_never_tenant_attributed(fake_redis, counters, clock):
    slo = evaluator(fake_redis, counters, clock)
    await slo.maybe_evaluate()
    clock.advance()
    await fail_ingest(counters)
    await slo.maybe_evaluate()
    (event,) = await alert_events(fake_redis)
    payload = event["payload"]
    assert payload["alert_scope"] == "platform"
    assert "workspace_id" not in payload and "network_id" not in payload and "scope" not in payload
    assert payload["alert_key"] == "telemetry_runtime_adapter_slo_threshold_breach"
    assert payload["evaluation_window"]["seconds"] == 30


async def test_window_state_persists_across_instances_and_is_gated(fake_redis, counters, clock):
    """The old deque/cooldown state lived on a per-request object and never took effect."""
    first = evaluator(fake_redis, counters, clock)
    await first.maybe_evaluate()
    assert await evaluator(fake_redis, counters, clock).maybe_evaluate() is None  # not due yet
    clock.advance(29)
    assert await first.maybe_evaluate() is None
    clock.advance(1)
    for _ in range(3):
        await fail_ingest(counters)
        second = await evaluator(fake_redis, counters, clock).maybe_evaluate()
        clock.advance()
    assert second.anomaly_streak == 3 and second.severity == "critical"
    assert second.severity_reason == "anomaly_streak_threshold_exceeded"
    assert second.sequence == 4 and len(second.trend) == 4
    assert (await counters.get_snapshot())["runtime_adapter_anomaly_streak"] == 3


async def test_concurrent_evaluators_close_a_window_once(fake_redis, counters, clock):
    evaluators = [evaluator(fake_redis, counters, clock) for _ in range(5)]
    results = await asyncio.gather(*(item.maybe_evaluate() for item in evaluators))
    assert sum(result is not None for result in results) == 1
    await fake_redis.set(LOCK_KEY, "someone-else", px=10_000)
    clock.advance()
    assert await evaluators[0].maybe_evaluate() is None  # lock held elsewhere
    assert (await SLOStateStore(fake_redis).load()).sequence == 1


async def test_sustained_failure_level_is_critical_immediately(fake_redis, counters, clock):
    await counters.set_runtime_sustained_failure_active(True)
    state = await evaluator(fake_redis, counters, clock).maybe_evaluate()
    assert (state.severity, state.severity_reason) == ("critical", "runtime_sustained_failure_active")
    (event,) = await alert_events(fake_redis)
    assert event["payload"]["runbook_playbook"] == rules.PLAYBOOK_TRANSITION


async def test_counter_reset_is_detected_and_not_negative(fake_redis, counters, clock):
    slo = evaluator(fake_redis, counters, clock)
    await fail_ingest(counters, times=5)
    await slo.maybe_evaluate()
    await fake_redis.flushall()  # Redis restart without the SLO state keys
    await SLOStateStore(fake_redis).save(advance_state(None, {"runtime_adapter_ingest_failures": 5,
                                                              "runtime_adapter_ingest_attempts": 5}, now=clock.now))
    await counters.increment_runtime_adapter_ingest_attempt()
    clock.advance()
    state = await slo.maybe_evaluate()
    assert state.window.counter_reset is True
    assert state.window.ingest_attempts == 1 and state.window.ingest_failures == 0


async def test_invalid_ratio_uses_window_deltas(fake_redis, counters, clock):
    slo = evaluator(fake_redis, counters, clock)
    for _ in range(100):
        await counters.increment_runtime_adapter_ingest_attempt()
    await slo.maybe_evaluate()
    clock.advance()
    await counters.increment_runtime_adapter_invalid_sample()
    await counters.increment_runtime_adapter_ingest_attempt()
    state = await slo.maybe_evaluate()
    # 1 invalid vs 1 attempt in this window = 0.5 > 0.25, despite 100 historic attempts.
    assert state.window.invalid_sample_ratio == 0.5
    assert state.anomaly_reason_flags == ["invalid_sample_ratio_exceeded"]


async def test_publish_failure_keeps_idempotent_pending_event(fake_redis, counters, clock):
    slo = evaluator(fake_redis, counters, clock)
    await slo.maybe_evaluate()
    clock.advance()
    await fail_ingest(counters)
    with patch("app.events.publisher.publish_event", AsyncMock(side_effect=ConnectionError("down"))):
        state = await slo.maybe_evaluate()
    assert state.alert_active and len(state.pending_events) == 1
    pending = state.pending_events[0]
    assert await alert_events(fake_redis) == []
    # Not due yet, but the outbox is flushed by the next periodic call.
    assert await slo.maybe_evaluate() is None
    (event,) = await alert_events(fake_redis)
    assert event["event_id"] == str(pending.event_id) and event["payload"] == pending.payload
    assert (await SLOStateStore(fake_redis).load()).pending_events == []


async def test_disabled_evaluator_is_inert(fake_redis, counters, clock):
    assert await evaluator(fake_redis, counters, clock, enabled=False).maybe_evaluate() is None
    assert await fake_redis.get(STATE_KEY) is None


async def test_corrupt_state_restarts_under_new_epoch(fake_redis, counters, clock):
    await fake_redis.set(STATE_KEY, "{not json")
    state = await evaluator(fake_redis, counters, clock).maybe_evaluate()
    assert state.sequence == 1


def test_trend_window_is_bounded_and_counts_transitions():
    state = None
    now = START
    for index in range(15):
        snapshot = {"runtime_adapter_ingest_failures": index * (index % 2)}
        state = advance_state(state, snapshot, now=now)
        now += timedelta(seconds=30)
    assert len(state.trend) == rules.TREND_WINDOW_MAX_SIZE
    summary = rules.trend_summary(state.trend)
    assert summary["window_size"] == 10 and summary["max_window_size"] == 10
    assert sum(summary["severity_transition_counts"].values()) == 9


def test_threshold_cooldown_phases():
    crossed = {"ingest_failures_detected": 3}
    state, phase = rules.threshold_step(None, crossed=crossed)
    assert phase == rules.PHASE_ENTER
    phases = []
    for _ in range(3):
        state, phase = rules.threshold_step(state, crossed=crossed)
        phases.append(phase)
    assert phases == [rules.PHASE_SUPPRESSED, rules.PHASE_SUPPRESSED, rules.PHASE_EXPIRED_REEMIT]
    state, phase = rules.threshold_step(state, crossed={})
    assert phase == rules.PHASE_CLEARED_RECOVERY and not state["threshold_crossed"]
    assert rules.threshold_step(state, crossed={})[1] == ""


@pytest.mark.parametrize("flags,reason,expected", [
    (["ingest_failures_detected"], "anomaly_streak_threshold_exceeded", rules.PLAYBOOK_COMBINED),
    ([], "runtime_sustained_failure_active", rules.PLAYBOOK_TRANSITION),
    (["dropped_samples_detected"], "runtime_adapter_anomaly_detected", rules.PLAYBOOK_REASON),
])
def test_playbook_selection(flags, reason, expected):
    assert rules.select_playbook(event_type=rules.ALERT_GENERATED, flags=flags, severity_reason=reason) == expected


async def test_collector_runtime_loop_hosts_the_evaluator(fake_redis):
    slo = AsyncMock()
    runner = TelemetryCollectorRunner(TelemetryIngestionService(fake_redis), slo_evaluator=slo)
    cycles = 0

    async def sleep(_):
        nonlocal cycles
        cycles += 1
        if cycles == 3:
            runner._runtime_stop_event.set()

    slo.maybe_evaluate.side_effect = [RuntimeError("redis down"), None, None]
    await runner.start_runtime_loop(poll_action=AsyncMock(), interval_seconds=0, poll_max_attempts=1,
                                    poll_base_backoff_seconds=0, poll_max_backoff_seconds=0, sleep=sleep)
    await runner._runtime_loop_task
    # An evaluator failure never stops collection; one evaluation hook per cycle.
    assert slo.maybe_evaluate.await_count == 3


def test_runner_builds_a_default_evaluator_on_its_event_redis(fake_redis):
    runner = TelemetryCollectorRunner(TelemetryIngestionService(fake_redis))
    assert isinstance(runner.slo_evaluator, TelemetrySLOEvaluator)
    assert TelemetryCollectorRunner(TelemetryIngestionService(fake_redis), slo_evaluator=None).slo_evaluator is None


def test_event_ids_are_unique_per_epoch():
    first = advance_state(None, {"runtime_sustained_failure_active": 1}, now=START)
    second = advance_state(None, {"runtime_sustained_failure_active": 1}, now=START)
    assert first.pending_events[0].event_id != second.pending_events[0].event_id
    assert uuid.UUID(str(first.pending_events[0].correlation_id))


def test_invalid_slo_environment_disables_evaluation_without_blocking_collection(fake_redis, monkeypatch):
    monkeypatch.setenv("NANFO_TELEMETRY_SLO_INTERVAL_SECONDS", "1")  # below the 5 s floor
    runner = TelemetryCollectorRunner(TelemetryIngestionService(fake_redis))
    assert runner.slo_evaluator is None
    monkeypatch.setenv("NANFO_TELEMETRY_SLO_INTERVAL_SECONDS", "60")
    assert TelemetryCollectorRunner(TelemetryIngestionService(fake_redis)).slo_evaluator.settings.interval_seconds == 60
