"""Opt-in PostgreSQL execution test using only a transaction-local temporary table.

Set TELEMETRY_TEST_DSN to an asyncpg SQLAlchemy DSN to execute this gate.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.telemetry.models import TelemetryRecord
from app.modules.telemetry.repository import TelemetryRecordRepository


@pytest.mark.skipif(not os.environ.get("TELEMETRY_TEST_DSN"), reason="TELEMETRY_TEST_DSN not configured")
async def test_postgres_aggregation_boundaries_dimensions_and_pagination():
    engine = create_async_engine(os.environ["TELEMETRY_TEST_DSN"])
    try:
        async with engine.connect() as connection, connection.begin():
            await connection.execute(text("""
                CREATE TEMP TABLE telemetry_records (
                    record_id uuid PRIMARY KEY, event_id uuid, correlation_id uuid,
                    device_id uuid, network_id uuid, workspace_id uuid, metric text,
                    value double precision, unit text, observed_at timestamptz,
                    source text, tags jsonb, created_at timestamptz DEFAULT now()
                ) ON COMMIT DROP
            """))
            async with AsyncSession(bind=connection) as db:
                start = datetime(2026, 9, 8, tzinfo=UTC)
                workspace, network, device = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

                def row(value, seconds=0, **overrides):
                    values = {
                        "record_id": uuid.uuid4(), "event_id": uuid.uuid4(), "correlation_id": uuid.uuid4(),
                        "device_id": device, "network_id": network, "workspace_id": workspace,
                        "metric": "queue_backlog_bytes", "value": value, "unit": "bytes", "source": "emulation",
                        "tags": {"port_no": 1}, "observed_at": start + timedelta(seconds=seconds),
                    }
                    values.update(overrides)
                    return TelemetryRecord(**values)

                db.add_all([
                    row(10), row(30, 59), row(50, 60), row(999, -1), row(999, 120),
                    row(20, tags={"port_no": 2}), row(7, tags={}),
                    row(8, source="other"), row(9, unit="packets"), row(11, unit=None),
                    row(12, device_id=uuid.uuid4()), row(999, metric="other"),
                    row(999, workspace_id=uuid.uuid4()), row(999, network_id=uuid.uuid4()),
                ])
                await db.flush()
                repo = TelemetryRecordRepository(db)
                params = {
                    "network_id": network, "workspace_id": workspace, "metric": "queue_backlog_bytes",
                    "start_time": start, "end_time": start + timedelta(seconds=120), "bucket_seconds": 60,
                }
                for aggregation, expected in [("avg", 20), ("min", 10), ("max", 30), ("sum", 40)]:
                    items, total = await repo.list_history(**params, aggregation=aggregation)
                    assert total == len(items) == 8
                    primary = [item for item in items if item.device_id == device and item.unit == "bytes" and item.source == "emulation" and item.port_no == "1" and item.bucket_start == start]
                    assert len(primary) == 1 and primary[0].value == expected and primary[0].sample_count == 2
                    paged = []
                    for page in range(1, 5):
                        page_items, page_total = await repo.list_history(**params, aggregation=aggregation, page=page, page_size=2)
                        assert page_total == total
                        paged.extend(page_items)
                    assert paged == items
                    assert await repo.list_history(**params, aggregation=aggregation, page=5, page_size=2) == ([], total)
                raw_params = {key: value for key, value in params.items() if key != "bucket_seconds"}
                raw, total = await repo.list_history(**raw_params)
                assert total == 9
                assert all(start <= item.observed_at < start + timedelta(seconds=120) for item in raw)
                device_rows, total = await repo.list_for_device(**raw_params, device_id=device)
                assert total == 8 and all(item.device_id == device for item in device_rows)

                run_a, run_b = str(uuid.uuid4()), str(uuid.uuid4())
                db.add_all([
                    row(value, metric="latency_ms", unit="ms", tags=tags)
                    for value, tags in [
                        (10, {"peer_host": "h2", "run_id": run_a}),
                        (30, {"peer_host": "h2", "run_id": run_a}),
                        (50, {"peer_host": "h3", "run_id": run_a}),
                        (70, {"peer_host": "h2", "run_id": run_b}),
                        (90, {"peer_host": "h3", "run_id": run_b}),
                        (100, {"peer_host": "h2"}),
                        (110, {"run_id": run_a}),
                        (120, {}),
                    ]
                ])
                db.add(row(42, metric="flow_byte_count", tags={"flow_index": 0}))
                db.add(row(84, metric="flow_byte_count", tags={"flow_index": 1}))
                await db.flush()
                probe_params = {**params, "metric": "latency_ms"}
                for aggregation, expected in [("avg", 20), ("min", 10), ("max", 30), ("sum", 40)]:
                    items, total = await repo.list_history(**probe_params, aggregation=aggregation)
                    assert total == len(items) == 7
                    by_series = {(item.peer_host, item.run_id): item for item in items}
                    assert len(by_series) == 7
                    assert by_series[("h2", run_a)].value == expected
                    assert by_series[("h2", run_a)].sample_count == 2
                    for key, value in [(('h3', run_a), 50), (('h2', run_b), 70), (('h3', run_b), 90), (('h2', None), 100), ((None, run_a), 110), ((None, None), 120)]:
                        assert by_series[key].value == value
                        assert by_series[key].port_no is None
                    paged = []
                    for page in range(1, 5):
                        page_items, page_total = await repo.list_history(**probe_params, aggregation=aggregation, page=page, page_size=2)
                        assert page_total == 7
                        paged.extend(page_items)
                    assert paged == items
                    assert await repo.list_history(**probe_params, aggregation=aggregation, page=5, page_size=2) == ([], 7)
                with pytest.raises(ValidationError, match="no durable flow match identity"):
                    await repo.list_history(**{**params, "metric": "flow_byte_count"}, aggregation="sum")
                flows, total = await repo.list_history(**{**raw_params, "metric": "flow_byte_count"})
                assert total == 2 and {item.value for item in flows} == {42, 84}
    finally:
        await engine.dispose()
