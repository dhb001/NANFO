"""Unit tests for telemetry ingestion scaffold (VS2 Step 5)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.telemetry.service import (
    GRPCRuntimeTelemetryAdapter,
    ProductionTelemetryAdapterStub,
    SeededRuntimeTelemetryAdapter,
    SNMPRuntimeTelemetryAdapter,
    TelemetryCollectorRunner,
    TelemetryIngestionService,
    build_production_runtime_adapter,
    build_runtime_poll_action,
    compute_bounded_backoff_seconds,
)

pytestmark = pytest.mark.usefixtures("execution_mode")


@pytest.mark.asyncio
async def test_telemetry_normalize_payload_coerces_types_and_defaults(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    normalized = svc.normalize_payload(
        {
            "device_id": uuid.uuid4(),
            "network_id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "metric": "cpu_usage",
            "value": "42.5",
            "unit": "percent",
            "source": "snmp",
            "tags": {"vendor": "test"},
        }
    )

    assert normalized["metric"] == "cpu_usage"
    assert normalized["value"] == 42.5
    assert normalized["unit"] == "percent"
    assert normalized["source"] == "snmp"
    assert normalized["tags"] == {"vendor": "test"}
    assert normalized["observed_at"]


@pytest.mark.asyncio
async def test_telemetry_ingest_publishes_expected_event(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    with patch("app.modules.telemetry.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "1712425-0"
        entry_id = await svc.ingest(
            raw={
                "device_id": str(uuid.uuid4()),
                "network_id": str(uuid.uuid4()),
                "workspace_id": str(uuid.uuid4()),
                "metric": "latency_ms",
                "value": 12,
            },
            correlation_id=str(uuid.uuid4()),
        )

    assert entry_id == "1712425-0"
    kwargs = mock_publish.call_args.kwargs
    assert kwargs["event_type"] == "telemetry.metric.ingested"
    assert kwargs["source"] == "telemetry"
    assert "metric" in kwargs["payload"]
    assert kwargs["payload"]["metric"] == "latency_ms"
    assert await fake_redis.get("telemetry:health:ingested_events") == "1"


@pytest.mark.asyncio
async def test_telemetry_ingest_ignores_counter_failures(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    with (
        patch("app.modules.telemetry.service.publish_event", new_callable=AsyncMock) as mock_publish,
        patch.object(svc._counter_service, "increment_ingested", new_callable=AsyncMock) as mock_increment,
    ):
        mock_publish.return_value = "1712425-0"
        mock_increment.side_effect = RuntimeError("redis unavailable")
        entry_id = await svc.ingest(
            raw={
                "device_id": str(uuid.uuid4()),
                "network_id": str(uuid.uuid4()),
                "workspace_id": str(uuid.uuid4()),
                "metric": "latency_ms",
                "value": 12,
            },
            correlation_id=str(uuid.uuid4()),
        )

    assert entry_id == "1712425-0"


@pytest.mark.asyncio
async def test_production_adapter_stub_returns_empty_batch(fake_redis):
    _ = TelemetryIngestionService(redis=fake_redis)
    adapter = ProductionTelemetryAdapterStub()

    samples = await adapter.poll()

    assert samples == []


@pytest.mark.asyncio
async def test_seeded_runtime_adapter_returns_deterministic_canonical_sample(fake_redis):
    _ = TelemetryIngestionService(redis=fake_redis)
    adapter = SeededRuntimeTelemetryAdapter(
        sample_key="campus-a",
        metric="cpu_usage",
        value=42.5,
        unit="percent",
        source="runtime_seeded",
    )

    first = await adapter.poll()
    second = await adapter.poll()

    assert len(first) == 1
    assert len(second) == 1
    first_sample = first[0]
    second_sample = second[0]

    assert first_sample["device_id"] == second_sample["device_id"]
    assert first_sample["network_id"] == second_sample["network_id"]
    assert first_sample["workspace_id"] == second_sample["workspace_id"]
    assert first_sample["metric"] == "cpu_usage"
    assert first_sample["value"] == 42.5
    assert first_sample["unit"] == "percent"
    assert first_sample["source"] == "runtime_seeded"
    assert first_sample["tags"] == {
        "adapter_mode": "seeded",
        "sample_key": "campus-a",
        "synthetic": True,
        "execution_mode": "demo",
    }
    assert first_sample["observed_at"]


def test_build_production_runtime_adapter_returns_seeded_mode_adapter():
    adapter = build_production_runtime_adapter(
        mode="seeded",
        seeded_sample_key="site-1",
        seeded_metric="latency_ms",
        seeded_value=12.0,
        seeded_unit="ms",
        seeded_source="runtime_seeded",
    )

    assert isinstance(adapter, SeededRuntimeTelemetryAdapter)


def test_build_production_runtime_adapter_returns_snmp_mode_adapter():
    adapter = build_production_runtime_adapter(
        mode="snmp",
        seeded_sample_key="site-1",
        seeded_metric="latency_ms",
        seeded_value=12.0,
        seeded_unit="ms",
        seeded_source="runtime_seeded",
        snmp_target="10.0.0.11",
        snmp_oid="1.3.6.1.2.1.31.1.1.1.6.1",
        snmp_sample_key="snmp-site-a",
        snmp_metric="if_in_octets_rate",
        snmp_value=22.5,
        snmp_unit="kbps",
        snmp_source="runtime_snmp",
    )

    assert isinstance(adapter, SNMPRuntimeTelemetryAdapter)


def test_build_production_runtime_adapter_returns_grpc_mode_adapter():
    adapter = build_production_runtime_adapter(
        mode="grpc",
        seeded_sample_key="site-1",
        seeded_metric="latency_ms",
        seeded_value=12.0,
        seeded_unit="ms",
        seeded_source="runtime_seeded",
        grpc_endpoint="collector.example:8443",
        grpc_method="Telemetry/Poll",
        grpc_sample_key="grpc-site-a",
        grpc_metric="packet_loss_ratio",
        grpc_value=0.03,
        grpc_unit="ratio",
        grpc_source="runtime_grpc",
    )

    assert isinstance(adapter, GRPCRuntimeTelemetryAdapter)


def test_build_production_runtime_adapter_falls_back_to_stub_for_invalid_mode():
    with patch("app.modules.telemetry.service.logger.warning") as mock_warning:
        adapter = build_production_runtime_adapter(
            mode="unknown",
            seeded_sample_key="site-1",
            seeded_metric="latency_ms",
            seeded_value=12.0,
            seeded_unit="ms",
            seeded_source="runtime_seeded",
        )

    assert isinstance(adapter, ProductionTelemetryAdapterStub)
    invalid_mode_logs = [
        call
        for call in mock_warning.call_args_list
        if call.args and call.args[0] == "telemetry_runtime_adapter_mode_invalid"
    ]
    assert len(invalid_mode_logs) == 1


@pytest.mark.asyncio
async def test_snmp_runtime_adapter_poll_emits_snmp_tags(fake_redis):
    _ = TelemetryIngestionService(redis=fake_redis)
    adapter = SNMPRuntimeTelemetryAdapter(
        target="10.0.0.11",
        oid="1.3.6.1.2.1.31.1.1.1.6.1",
        sample_key="snmp-site-a",
        metric="if_in_octets_rate",
        value=22.5,
        unit="kbps",
        source="runtime_snmp",
    )

    first = await adapter.poll()
    second = await adapter.poll()

    assert len(first) == 1
    assert len(second) == 1
    first_sample = first[0]
    second_sample = second[0]
    assert first_sample["device_id"] == second_sample["device_id"]
    assert first_sample["network_id"] == second_sample["network_id"]
    assert first_sample["workspace_id"] == second_sample["workspace_id"]
    assert first_sample["metric"] == "if_in_octets_rate"
    assert first_sample["value"] == 22.5
    assert first_sample["unit"] == "kbps"
    assert first_sample["source"] == "runtime_snmp"
    assert first_sample["tags"]["adapter_mode"] == "snmp"
    assert first_sample["tags"]["sample_key"] == "snmp-site-a"
    assert first_sample["tags"]["target"] == "10.0.0.11"
    assert first_sample["tags"]["oid"] == "1.3.6.1.2.1.31.1.1.1.6.1"


@pytest.mark.asyncio
async def test_grpc_runtime_adapter_poll_emits_grpc_tags(fake_redis):
    _ = TelemetryIngestionService(redis=fake_redis)
    adapter = GRPCRuntimeTelemetryAdapter(
        endpoint="collector.example:8443",
        method="Telemetry/Poll",
        sample_key="grpc-site-a",
        metric="packet_loss_ratio",
        value=0.03,
        unit="ratio",
        source="runtime_grpc",
    )

    first = await adapter.poll()
    second = await adapter.poll()

    assert len(first) == 1
    assert len(second) == 1
    first_sample = first[0]
    second_sample = second[0]
    assert first_sample["device_id"] == second_sample["device_id"]
    assert first_sample["network_id"] == second_sample["network_id"]
    assert first_sample["workspace_id"] == second_sample["workspace_id"]
    assert first_sample["metric"] == "packet_loss_ratio"
    assert first_sample["value"] == 0.03
    assert first_sample["unit"] == "ratio"
    assert first_sample["source"] == "runtime_grpc"
    assert first_sample["tags"]["adapter_mode"] == "grpc"
    assert first_sample["tags"]["sample_key"] == "grpc-site-a"
    assert first_sample["tags"]["endpoint"] == "collector.example:8443"
    assert first_sample["tags"]["method"] == "Telemetry/Poll"


@pytest.mark.asyncio
async def test_runtime_poll_action_ingests_valid_samples(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    valid_sample = {
        "device_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "metric": "cpu_usage",
        "value": 42.0,
    }

    adapter = AsyncMock()
    adapter.poll = AsyncMock(return_value=[valid_sample])

    with patch.object(runner, "ingest_once", new=AsyncMock(return_value="1-0")) as mock_ingest_once:
        poll_action = build_runtime_poll_action(collector_runner=runner, adapter=adapter)
        await poll_action()

    mock_ingest_once.assert_awaited_once()
    ingest_kwargs = mock_ingest_once.await_args.kwargs
    assert ingest_kwargs["raw"] == valid_sample
    assert isinstance(uuid.UUID(ingest_kwargs["correlation_id"]), uuid.UUID)
    snapshot = await svc.counter_service.get_snapshot()
    assert snapshot["runtime_adapter_last_batch_size"] == 1
    assert snapshot["runtime_adapter_invalid_samples"] == 0
    assert snapshot["runtime_adapter_dropped_samples"] == 0
    assert snapshot["runtime_adapter_ingest_attempts"] == 1
    assert snapshot["runtime_adapter_ingest_failures"] == 0


@pytest.mark.asyncio
async def test_runtime_poll_action_ignores_invalid_batch_type_fail_open(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    adapter = AsyncMock()
    adapter.poll = AsyncMock(return_value={"not": "a-list"})

    with patch.object(runner, "ingest_once", new=AsyncMock()) as mock_ingest_once:
        poll_action = build_runtime_poll_action(collector_runner=runner, adapter=adapter)
        await poll_action()

    mock_ingest_once.assert_not_awaited()
    snapshot = await svc.counter_service.get_snapshot()
    assert snapshot["runtime_adapter_last_batch_size"] == 0
    assert snapshot["runtime_adapter_invalid_samples"] == 0
    assert snapshot["runtime_adapter_dropped_samples"] == 0
    assert snapshot["runtime_adapter_ingest_attempts"] == 0
    assert snapshot["runtime_adapter_ingest_failures"] == 0


@pytest.mark.asyncio
async def test_runtime_poll_action_skips_invalid_samples_and_keeps_valid_ones(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    valid_sample = {
        "device_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "metric": "latency_ms",
        "value": 10,
    }
    adapter = AsyncMock()
    adapter.poll = AsyncMock(
        return_value=[
            "not-an-object",
            {"device_id": "", "metric": "cpu", "value": 1},
            valid_sample,
        ]
    )

    with patch.object(runner, "ingest_once", new=AsyncMock(return_value="1-0")) as mock_ingest_once:
        poll_action = build_runtime_poll_action(collector_runner=runner, adapter=adapter)
        await poll_action()

    mock_ingest_once.assert_awaited_once()
    assert mock_ingest_once.await_args.kwargs["raw"] == valid_sample
    snapshot = await svc.counter_service.get_snapshot()
    assert snapshot["runtime_adapter_last_batch_size"] == 3
    assert snapshot["runtime_adapter_invalid_samples"] == 2
    assert snapshot["runtime_adapter_dropped_samples"] == 2
    assert snapshot["runtime_adapter_ingest_attempts"] == 1
    assert snapshot["runtime_adapter_ingest_failures"] == 0


@pytest.mark.asyncio
async def test_runtime_poll_action_adapter_failure_raises_for_retry(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    adapter = AsyncMock()
    adapter.poll = AsyncMock(side_effect=RuntimeError("adapter failure"))

    poll_action = build_runtime_poll_action(collector_runner=runner, adapter=adapter)
    with pytest.raises(RuntimeError):
        await poll_action()


@pytest.mark.asyncio
async def test_runtime_poll_action_ingest_failure_raises_for_retry(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    valid_sample = {
        "device_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "metric": "packet_loss",
        "value": 0.1,
    }
    adapter = AsyncMock()
    adapter.poll = AsyncMock(return_value=[valid_sample])

    with patch.object(runner, "ingest_once", new=AsyncMock(side_effect=RuntimeError("ingest failed"))):
        poll_action = build_runtime_poll_action(collector_runner=runner, adapter=adapter)
        with pytest.raises(RuntimeError):
            await poll_action()

    snapshot = await svc.counter_service.get_snapshot()
    assert snapshot["runtime_adapter_last_batch_size"] == 1
    assert snapshot["runtime_adapter_invalid_samples"] == 0
    assert snapshot["runtime_adapter_dropped_samples"] == 1
    assert snapshot["runtime_adapter_ingest_attempts"] == 1
    assert snapshot["runtime_adapter_ingest_failures"] == 1


@pytest.mark.asyncio
async def test_runtime_poll_action_counter_update_failures_are_fail_open(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    valid_sample = {
        "device_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "metric": "cpu_usage",
        "value": 42.0,
    }
    adapter = AsyncMock()
    adapter.poll = AsyncMock(return_value=[valid_sample])

    with (
        patch.object(
            runner.counter_service,
            "set_runtime_adapter_last_batch_size",
            new=AsyncMock(side_effect=RuntimeError("counter set failed")),
        ),
        patch.object(
            runner.counter_service,
            "increment_runtime_adapter_ingest_attempt",
            new=AsyncMock(side_effect=RuntimeError("counter increment failed")),
        ),
        patch.object(runner, "ingest_once", new=AsyncMock(return_value="1-0")) as mock_ingest_once,
    ):
        poll_action = build_runtime_poll_action(collector_runner=runner, adapter=adapter)
        await poll_action()

    mock_ingest_once.assert_awaited_once()


@pytest.mark.asyncio
async def test_collector_runner_start_stop_and_ingest_once(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    assert runner.running is False
    await runner.start()
    assert runner.running is True

    with patch.object(svc, "ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = "1-0"
        entry_id = await runner.ingest_once(raw={"metric": "cpu", "value": 1}, correlation_id=str(uuid.uuid4()))

    assert entry_id == "1-0"
    mock_ingest.assert_awaited_once()

    await runner.stop()
    assert runner.running is False


@pytest.mark.asyncio
async def test_compute_bounded_backoff_seconds_is_bounded_and_exponential():
    assert compute_bounded_backoff_seconds(
        1,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
    ) == 0.5
    assert compute_bounded_backoff_seconds(
        2,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
    ) == 1.0
    assert compute_bounded_backoff_seconds(
        3,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
    ) == 2.0
    assert compute_bounded_backoff_seconds(
        4,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
    ) == 2.0


@pytest.mark.asyncio
async def test_collector_runner_start_with_retry_succeeds_after_transient_failures(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    sleep = AsyncMock()
    with patch.object(
        runner,
        "start",
        new=AsyncMock(side_effect=[RuntimeError("first"), RuntimeError("second"), None]),
    ):
        started = await runner.start_with_retry(
            max_attempts=3,
            base_backoff_seconds=0.5,
            max_backoff_seconds=2.0,
            sleep=sleep,
        )

    assert started is True
    assert sleep.await_count == 2
    assert sleep.await_args_list[0].args[0] == 0.5
    assert sleep.await_args_list[1].args[0] == 1.0


@pytest.mark.asyncio
async def test_collector_runner_start_with_retry_exhausts_attempts(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    sleep = AsyncMock()
    with patch.object(
        runner,
        "start",
        new=AsyncMock(side_effect=[RuntimeError("first"), RuntimeError("second"), RuntimeError("third")]),
    ):
        started = await runner.start_with_retry(
            max_attempts=3,
            base_backoff_seconds=0.5,
            max_backoff_seconds=2.0,
            sleep=sleep,
        )

    assert started is False
    assert runner.running is False
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_collector_runner_start_with_retry_immediate_success_avoids_sleep(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    sleep = AsyncMock()
    started = await runner.start_with_retry(
        max_attempts=3,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
        sleep=sleep,
    )

    assert started is True
    assert runner.running is True
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_single_poll_with_retry_recovers_after_transient_failures(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(side_effect=[RuntimeError("first"), RuntimeError("second"), None])
    sleep = AsyncMock()

    succeeded = await runner.run_single_poll_with_retry(
        poll_action=poll_action,
        max_attempts=3,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
        sleep=sleep,
    )

    assert succeeded is True
    assert poll_action.await_count == 3
    assert sleep.await_count == 2
    assert sleep.await_args_list[0].args[0] == 0.5
    assert sleep.await_args_list[1].args[0] == 1.0


@pytest.mark.asyncio
async def test_run_single_poll_with_retry_exhausts_and_returns_false(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(side_effect=[RuntimeError("first"), RuntimeError("second"), RuntimeError("third")])
    sleep = AsyncMock()

    succeeded = await runner.run_single_poll_with_retry(
        poll_action=poll_action,
        max_attempts=3,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
        sleep=sleep,
    )

    assert succeeded is False
    assert poll_action.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_run_single_poll_with_retry_immediate_success_without_sleep(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(return_value=None)
    sleep = AsyncMock()

    succeeded = await runner.run_single_poll_with_retry(
        poll_action=poll_action,
        max_attempts=3,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
        sleep=sleep,
    )

    assert succeeded is True
    poll_action.assert_awaited_once()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_loop_runs_poll_cycles_on_interval_until_stopped(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock()

    async def controlled_sleep(_: float) -> None:
        if poll_action.await_count >= 2:
            runner._runtime_stop_event.set()

    sleep = AsyncMock(side_effect=controlled_sleep)

    await runner.start_runtime_loop(
        poll_action=poll_action,
        interval_seconds=0.1,
        poll_max_attempts=2,
        poll_base_backoff_seconds=0.5,
        poll_max_backoff_seconds=2.0,
        sleep=sleep,
    )

    assert runner._runtime_loop_task is not None
    await runner._runtime_loop_task

    assert poll_action.await_count == 2
    assert sleep.await_count >= 1
    runner._runtime_loop_task = None


@pytest.mark.asyncio
async def test_runtime_loop_continues_after_exhausted_cycle(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(return_value=None)
    sleep = AsyncMock()

    side_effects = [False, True]

    async def fake_run_single_poll_with_retry(**_: object) -> bool:
        result = side_effects.pop(0)
        if result and not side_effects:
            runner._runtime_stop_event.set()
        return result

    with patch.object(
        runner,
        "run_single_poll_with_retry",
        new=AsyncMock(side_effect=fake_run_single_poll_with_retry),
    ) as mock_retry:
        await runner.start_runtime_loop(
            poll_action=poll_action,
            interval_seconds=0.1,
            poll_max_attempts=2,
            poll_base_backoff_seconds=0.5,
            poll_max_backoff_seconds=2.0,
            sleep=sleep,
        )
        assert runner._runtime_loop_task is not None
        await runner._runtime_loop_task

    assert mock_retry.await_count == 2
    assert sleep.await_count >= 1
    runner._runtime_loop_task = None


@pytest.mark.asyncio
async def test_stop_runtime_loop_awaits_task_and_clears_reference(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(return_value=None)

    async def controlled_sleep(_: float) -> None:
        await asyncio.sleep(0)

    sleep = AsyncMock(side_effect=controlled_sleep)

    await runner.start_runtime_loop(
        poll_action=poll_action,
        interval_seconds=1.0,
        poll_max_attempts=2,
        poll_base_backoff_seconds=0.5,
        poll_max_backoff_seconds=2.0,
        sleep=sleep,
    )

    assert runner._runtime_loop_task is not None
    task = runner._runtime_loop_task

    await runner.stop_runtime_loop()

    assert runner._runtime_loop_task is None
    assert task.done()


@pytest.mark.asyncio
async def test_collector_stop_stops_runtime_loop_when_running(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)
    await runner.start()

    poll_action = AsyncMock(return_value=None)

    async def controlled_sleep(_: float) -> None:
        await asyncio.sleep(0)
        while not runner._runtime_stop_event.is_set():
            await asyncio.sleep(0)

    sleep = AsyncMock(side_effect=controlled_sleep)

    await runner.start_runtime_loop(
        poll_action=poll_action,
        interval_seconds=1.0,
        poll_max_attempts=2,
        poll_base_backoff_seconds=0.5,
        poll_max_backoff_seconds=2.0,
        sleep=sleep,
    )

    assert runner._runtime_loop_task is not None
    task = runner._runtime_loop_task

    await runner.stop()

    assert runner.running is False
    assert runner._runtime_loop_task is None
    assert task.done()


@pytest.mark.asyncio
async def test_runtime_loop_sets_sustained_failure_active_after_threshold(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(return_value=None)
    sleep = AsyncMock()
    cycle_results = [False, False, False]

    async def fake_run_single_poll_with_retry(**_: object) -> bool:
        result = cycle_results.pop(0)
        if not cycle_results:
            runner._runtime_stop_event.set()
        return result

    with patch.object(
        runner,
        "run_single_poll_with_retry",
        new=AsyncMock(side_effect=fake_run_single_poll_with_retry),
    ):
        await runner.start_runtime_loop(
            poll_action=poll_action,
            interval_seconds=0.1,
            poll_max_attempts=2,
            poll_base_backoff_seconds=0.5,
            poll_max_backoff_seconds=2.0,
            runtime_sustained_failure_threshold=3,
            sleep=sleep,
        )
        assert runner._runtime_loop_task is not None
        await runner._runtime_loop_task

    snapshot = await svc.counter_service.get_snapshot()
    assert snapshot["runtime_exhausted_cycles"] == 3
    assert snapshot["runtime_exhausted_streak"] == 3
    assert snapshot["runtime_sustained_failure_windows"] == 1
    assert snapshot["runtime_sustained_failure_active"] == 1
    runner._runtime_loop_task = None


@pytest.mark.asyncio
async def test_runtime_loop_success_resets_sustained_failure_state(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(return_value=None)
    sleep = AsyncMock()
    cycle_results = [False, False, False, True]

    async def fake_run_single_poll_with_retry(**_: object) -> bool:
        result = cycle_results.pop(0)
        if not cycle_results:
            runner._runtime_stop_event.set()
        return result

    with patch.object(
        runner,
        "run_single_poll_with_retry",
        new=AsyncMock(side_effect=fake_run_single_poll_with_retry),
    ):
        await runner.start_runtime_loop(
            poll_action=poll_action,
            interval_seconds=0.1,
            poll_max_attempts=2,
            poll_base_backoff_seconds=0.5,
            poll_max_backoff_seconds=2.0,
            runtime_sustained_failure_threshold=3,
            sleep=sleep,
        )
        assert runner._runtime_loop_task is not None
        await runner._runtime_loop_task

    snapshot = await svc.counter_service.get_snapshot()
    assert snapshot["runtime_exhausted_cycles"] == 3
    assert snapshot["runtime_exhausted_streak"] == 0
    assert snapshot["runtime_sustained_failure_windows"] == 1
    assert snapshot["runtime_sustained_failure_active"] == 0
    runner._runtime_loop_task = None


@pytest.mark.asyncio
async def test_runtime_loop_transient_exhaustion_does_not_activate_sustained_failure(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(return_value=None)
    sleep = AsyncMock()
    cycle_results = [False, False, True]

    async def fake_run_single_poll_with_retry(**_: object) -> bool:
        result = cycle_results.pop(0)
        if not cycle_results:
            runner._runtime_stop_event.set()
        return result

    with patch.object(
        runner,
        "run_single_poll_with_retry",
        new=AsyncMock(side_effect=fake_run_single_poll_with_retry),
    ):
        await runner.start_runtime_loop(
            poll_action=poll_action,
            interval_seconds=0.1,
            poll_max_attempts=2,
            poll_base_backoff_seconds=0.5,
            poll_max_backoff_seconds=2.0,
            runtime_sustained_failure_threshold=3,
            sleep=sleep,
        )
        assert runner._runtime_loop_task is not None
        await runner._runtime_loop_task

    snapshot = await svc.counter_service.get_snapshot()
    assert snapshot["runtime_exhausted_cycles"] == 2
    assert snapshot["runtime_exhausted_streak"] == 0
    assert snapshot["runtime_sustained_failure_windows"] == 0
    assert snapshot["runtime_sustained_failure_active"] == 0
    runner._runtime_loop_task = None


@pytest.mark.asyncio
async def test_runtime_loop_emits_transition_events_on_sustained_failure_and_recovery(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(return_value=None)
    sleep = AsyncMock()
    cycle_results = [False, False, False, True]

    async def fake_run_single_poll_with_retry(**_: object) -> bool:
        result = cycle_results.pop(0)
        if not cycle_results:
            runner._runtime_stop_event.set()
        return result

    with (
        patch.object(
            runner,
            "run_single_poll_with_retry",
            new=AsyncMock(side_effect=fake_run_single_poll_with_retry),
        ),
        patch("app.modules.telemetry.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_publish.side_effect = ["111-0", "112-0"]
        await runner.start_runtime_loop(
            poll_action=poll_action,
            interval_seconds=0.1,
            poll_max_attempts=2,
            poll_base_backoff_seconds=0.5,
            poll_max_backoff_seconds=2.0,
            runtime_sustained_failure_threshold=3,
            sleep=sleep,
        )
        assert runner._runtime_loop_task is not None
        await runner._runtime_loop_task

    assert mock_publish.await_count == 2
    first_kwargs = mock_publish.await_args_list[0].kwargs
    second_kwargs = mock_publish.await_args_list[1].kwargs
    assert first_kwargs["event_type"] == "telemetry.collector.sustained_failure_activated"
    assert second_kwargs["event_type"] == "telemetry.collector.sustained_failure_recovered"
    assert first_kwargs["payload"]["exhausted_streak"] == 3
    assert second_kwargs["payload"]["exhausted_streak"] == 3
    runner._runtime_loop_task = None


@pytest.mark.asyncio
async def test_runtime_loop_publish_failure_is_fail_open(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(return_value=None)
    sleep = AsyncMock()
    cycle_results = [False, False, False, True]

    async def fake_run_single_poll_with_retry(**_: object) -> bool:
        result = cycle_results.pop(0)
        if not cycle_results:
            runner._runtime_stop_event.set()
        return result

    with (
        patch.object(
            runner,
            "run_single_poll_with_retry",
            new=AsyncMock(side_effect=fake_run_single_poll_with_retry),
        ),
        patch(
            "app.modules.telemetry.service.publish_event",
            new=AsyncMock(side_effect=RuntimeError("redis publish failed")),
        ),
    ):
        await runner.start_runtime_loop(
            poll_action=poll_action,
            interval_seconds=0.1,
            poll_max_attempts=2,
            poll_base_backoff_seconds=0.5,
            poll_max_backoff_seconds=2.0,
            runtime_sustained_failure_threshold=3,
            sleep=sleep,
        )
        assert runner._runtime_loop_task is not None
        await runner._runtime_loop_task

    snapshot = await svc.counter_service.get_snapshot()
    assert snapshot["runtime_sustained_failure_windows"] == 1
    assert snapshot["runtime_sustained_failure_active"] == 0
    runner._runtime_loop_task = None


@pytest.mark.asyncio
async def test_runtime_loop_does_not_reemit_activation_while_already_active(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    poll_action = AsyncMock(return_value=None)
    sleep = AsyncMock()
    cycle_results = [False, False, False, False]

    async def fake_run_single_poll_with_retry(**_: object) -> bool:
        result = cycle_results.pop(0)
        if not cycle_results:
            runner._runtime_stop_event.set()
        return result

    with (
        patch.object(
            runner,
            "run_single_poll_with_retry",
            new=AsyncMock(side_effect=fake_run_single_poll_with_retry),
        ),
        patch("app.modules.telemetry.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_publish.return_value = "111-0"
        await runner.start_runtime_loop(
            poll_action=poll_action,
            interval_seconds=0.1,
            poll_max_attempts=2,
            poll_base_backoff_seconds=0.5,
            poll_max_backoff_seconds=2.0,
            runtime_sustained_failure_threshold=3,
            sleep=sleep,
        )
        assert runner._runtime_loop_task is not None
        await runner._runtime_loop_task

    assert mock_publish.await_count == 1
    assert mock_publish.await_args.kwargs["event_type"] == "telemetry.collector.sustained_failure_activated"
    runner._runtime_loop_task = None
