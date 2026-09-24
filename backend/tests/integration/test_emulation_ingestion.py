"""Snapshot -> runtime runner -> existing stream -> idempotent persistence contract."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.telemetry.emulation import (
    EmulationSnapshot,
    EmulationTelemetryAdapter,
    SnapshotReader,
)
from app.modules.telemetry.service import (
    TelemetryCollectorRunner,
    TelemetryIngestionService,
    TelemetryPersistenceService,
    build_runtime_poll_action,
)


async def test_snapshot_retry_publishes_stable_ids_and_persists_once(integration_fake_redis):
    redis = integration_fake_redis
    await redis.delete("stream:telemetry")
    now = datetime.now(UTC).isoformat()
    dpid = "0000000000000001"
    snapshot = EmulationSnapshot.model_validate_json(json.dumps({
        "version": 1, "topology_id": "campus-small-v1", "run_id": str(uuid.uuid4()),
        "sequence": 0, "observed_at": now, "switches": [], "links": [], "hosts": [],
        "queues": [{"dpid": dpid, "port_no": 1, "observed_at": now,
                    "backlog_bytes": 123, "backlog_packets": 2}], "probes": [],
    }))
    binding = {"network_id": str(uuid.uuid4()), "workspace_id": str(uuid.uuid4()),
               "switches": {dpid: str(uuid.uuid4())}, "hosts": {}, "port_capacities_mbps": {}}
    reader = SnapshotReader(Path("unused"))
    reader.read = AsyncMock(return_value=snapshot)
    adapter = EmulationTelemetryAdapter(reader=reader, prepare_snapshot=AsyncMock(return_value=binding))
    runner = TelemetryCollectorRunner(TelemetryIngestionService(redis))
    poll = build_runtime_poll_action(collector_runner=runner, adapter=adapter)
    await poll()
    await poll()
    entries = await redis.xrange("stream:telemetry")
    assert len(entries) == 2
    rows = {}

    async def create(**kwargs):
        rows[kwargs["event_id"]] = kwargs

    repository = AsyncMock()
    repository.get_by_event_id.side_effect = lambda event_id: rows.get(event_id)
    repository.create.side_effect = create
    with patch("app.modules.telemetry.persistence.TelemetryRecordRepository", return_value=repository):
        persistence = TelemetryPersistenceService(AsyncMock())
        persistence._dedup = AsyncMock()
        persistence._dedup.archived.return_value = False
        results = []
        for _, fields in entries:
            results.append(await persistence.persist_event({**fields, "payload": json.loads(fields["payload"])}))
    assert results == [True, True]
    assert len(rows) == 2
    assert {row["value"] for row in rows.values()} == {123, 2}
    assert all(row["tags"]["synthetic"] is False for row in rows.values())

    # A publish failure partway through a batch replays the original IDs, including
    # the already-published prefix, so the existing persistence guard can dedupe it.
    await redis.delete("stream:telemetry")
    adapter = EmulationTelemetryAdapter(reader=reader, prepare_snapshot=AsyncMock(return_value=binding))
    poll = build_runtime_poll_action(collector_runner=runner, adapter=adapter)
    from app.modules.telemetry.service import publish_event

    calls = 0

    async def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("stream unavailable")
        return await publish_event(**kwargs)

    with (
        patch("app.modules.telemetry.ingestion.publish_event", side_effect=fail_second),
        pytest.raises(RuntimeError),
    ):
        await poll()
    original_ids = {sample["event_id"] for sample in adapter._samples}
    newer = snapshot.model_copy(deep=True)
    newer.sequence = 1
    newer.observed_at += timedelta(seconds=1)
    newer.queues[0].observed_at += timedelta(seconds=1)
    reader.read.return_value = newer
    reads = reader.read.await_count
    await poll()
    assert reader.read.await_count == reads
    retried = await redis.xrange("stream:telemetry")
    assert len(retried) == 3
    assert retried[0][1]["event_id"] == retried[1][1]["event_id"]
    assert {fields["event_id"] for _, fields in retried} == {str(key) for key in rows}
    assert {fields["event_id"] for _, fields in retried} == original_ids
    rows.clear()
    with patch("app.modules.telemetry.persistence.TelemetryRecordRepository", return_value=repository):
        persistence = TelemetryPersistenceService(AsyncMock())
        persistence._dedup = AsyncMock()
        persistence._dedup.archived.return_value = False
        results = []
        for _, fields in retried:
            results.append(await persistence.persist_event({**fields, "payload": json.loads(fields["payload"])}))
        assert results == [True, False, True]
        assert {str(key) for key in rows} == original_ids
    await poll()
    assert reader.read.await_count == reads + 1
    assert len(await redis.xrange("stream:telemetry")) == 5
