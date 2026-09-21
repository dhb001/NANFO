"""Real owning replay classification, canonical delivery and transient recovery."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.events.bus import process_entry
from app.events.consumers import telemetry_consumer as consumer
from app.events.fanout import FanoutPublisher, _publisher
from app.events.fanout_contract import FanoutSettings
from app.modules.telemetry.dedup import TelemetryDedupRepository
from app.modules.telemetry.repository import TelemetryRecordRepository
from app.modules.telemetry.service import TelemetryPersistenceService
from tests.unit.test_telemetry_consumer import _telemetry_event


@pytest.fixture
def replay_case(monkeypatch):
    event = _telemetry_event()
    event["timestamp"] = "untrusted-envelope-time"
    values = deepcopy(event["payload"])
    values.update(event_id=event["event_id"], correlation_id=event["correlation_id"])
    for key in ("event_id", "correlation_id", "device_id", "network_id", "workspace_id"):
        values[key] = UUID(values[key])
    from datetime import datetime
    values["observed_at"] = datetime.fromisoformat(values["observed_at"])
    record = SimpleNamespace(**values)
    lock, archived, get_record = AsyncMock(), AsyncMock(return_value=False), AsyncMock(return_value=record)
    monkeypatch.setattr(TelemetryDedupRepository, "lock", lock)
    monkeypatch.setattr(TelemetryDedupRepository, "archived", archived)
    monkeypatch.setattr(TelemetryRecordRepository, "get_by_event_id", get_record)
    db = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__.return_value = db
    monkeypatch.setattr(consumer, "AsyncSessionLocal", lambda: cm)
    monkeypatch.setattr(consumer, "_get_counter_service", lambda: None)
    detector, push = AsyncMock(), AsyncMock()
    monkeypatch.setattr(consumer, "handle_persisted_metric_event", detector)
    monkeypatch.setattr(consumer.telemetry_ws_manager, "push_delta", push)
    return SimpleNamespace(event=event, record=record, db=db, archived=archived,
                           get_record=get_record, detector=detector, push=push, lock=lock)


async def test_committed_exact_replay_recovers_canonical_delta(replay_case):
    case = replay_case
    replay = await TelemetryPersistenceService(case.db).replay_event(case.event)
    assert replay.status == "active_exact"
    assert replay.event["timestamp"] == case.record.observed_at.isoformat()
    assert replay.event["payload"] is not case.event["payload"]
    await consumer.handle_telemetry_event(case.event)
    case.db.commit.assert_not_awaited()
    case.detector.assert_awaited_once_with(replay.event)
    assert case.push.await_args.kwargs["metric"]["value"] == case.record.value
    assert case.push.await_args.kwargs["workspace_id"] == str(case.record.workspace_id)
    assert case.push.await_args.kwargs["timestamp"] != "untrusted-envelope-time"


@pytest.mark.parametrize("field,value", [
    ("value", 999), ("workspace_id", str(uuid4())), ("network_id", str(uuid4())),
    ("device_id", str(uuid4())), ("metric", "other"), ("unit", "foreign"),
    ("source", "forged"), ("tags", {"run_id": "forged"}), ("observed_at", "2000-01-01T00:00:00Z"),
])
async def test_real_conflicts_never_reach_detector_or_socket(replay_case, field, value):
    case = replay_case
    case.event["payload"][field] = value
    assert (await TelemetryPersistenceService(case.db).replay_event(case.event)).status == "active_conflict"
    with pytest.raises(ValueError, match="conflicts"):
        await consumer.handle_telemetry_event(case.event)
    case.detector.assert_not_awaited()
    case.push.assert_not_awaited()


async def test_tombstone_suppresses_even_malformed_replay(replay_case):
    case = replay_case
    case.archived.return_value = True
    case.event["payload"] = {"value": 999, "workspace_id": str(uuid4())}
    await consumer.handle_telemetry_event(case.event)
    case.get_record.assert_not_awaited()
    case.detector.assert_not_awaited()
    case.push.assert_not_awaited()


async def test_recovered_exact_event_transient_append_cannot_ack(replay_case):
    import json
    case = replay_case
    redis = AsyncMock()
    redis.exists.return_value = False
    redis.eval.side_effect = OSError("append outcome unknown")
    context = _publisher.set(FanoutPublisher(redis, token="leader", settings=FanoutSettings()))
    try:
        fields = {**case.event, "payload": json.dumps(case.event["payload"])}
        with pytest.raises(asyncio.CancelledError):
            await process_entry(redis, "stream:telemetry", "group", "1-0", fields,
                                {"telemetry.metric.ingested": consumer.handle_telemetry_event})
    finally:
        _publisher.reset(context)
    case.detector.assert_awaited_once()
    redis.xack.assert_not_awaited()
    redis.set.assert_not_awaited()
    redis.xadd.assert_not_awaited()


async def test_conflict_reaches_durable_dlq_instead_of_delivery(replay_case):
    import json
    case = replay_case
    case.event["correlation_id"] = str(uuid4())
    redis = AsyncMock()
    redis.exists.return_value = False
    await process_entry(redis, "stream:telemetry", "group", "1-0",
                        {**case.event, "payload": json.dumps(case.event["payload"])},
                        {"telemetry.metric.ingested": consumer.handle_telemetry_event}, max_retries=1)
    redis.xadd.assert_awaited_once()
    redis.xack.assert_awaited_once()
    case.push.assert_not_awaited()
    case.detector.assert_not_awaited()


async def test_missing_active_record_is_failure_not_unvalidated_fallback(replay_case):
    case = replay_case
    case.get_record.return_value = None
    with pytest.raises(RuntimeError, match="missing"):
        await TelemetryPersistenceService(case.db).replay_event(case.event)
