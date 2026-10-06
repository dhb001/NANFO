"""Modeled scope, branch, reference and legacy-consumer regressions."""

import copy
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.simulation import modeled
from app.modules.simulation.evaluator import advance, digest
from app.modules.simulation.modeled import (
    current_network_state_hash,
    stable_network_projection,
    verified_output,
    verified_output_async,
)
from app.modules.simulation.service import (
    SimulationStartService,
    SimulationTerminalEventService,
)
from tests.simulation_support import POLICY_LIMITS, policy_scenario, record, scenario


@pytest.fixture
def service(mock_db, fake_redis):
    svc = SimulationStartService(db=mock_db, redis=fake_redis)
    svc._workspace_svc.get_active_workspace = AsyncMock()
    svc._network_svc.assert_network_workspace_access = AsyncMock()
    return svc


def scope(row):
    return {
        "requested_by_user_id": row.requested_by_user_id,
        "requested_workspace_id": row.workspace_id,
        "claim_org_id": None,
    }


async def test_started_consumer_ignores_versioned_even_running(mock_db, fake_redis):
    row = record(state="running")
    svc = SimulationTerminalEventService(db=mock_db, redis=fake_redis)
    svc._repo.get_by_id = AsyncMock(return_value=row)
    await svc.process_started_event(
        event={"payload": {"simulation_id": str(row.simulation_id)}}
    )
    assert row.state == "running"
    mock_db.commit.assert_not_awaited()


async def test_branch_exact_checkpoint_and_override_reset(service, mock_db):
    parent = record()
    parent.checkpoint = advance(scenario(), parent.checkpoint, ticks=3)
    service._repo.get_by_id = service._repo.lock = AsyncMock(return_value=parent)
    service._network_svc.assert_network_workspace_access.return_value = parent
    await service.branch_simulation(
        parent_simulation_id=parent.simulation_id,
        scenario_name="Copy",
        correlation_id=str(uuid.uuid4()),
        **scope(parent),
    )
    copied = mock_db.add.call_args_list[-2].args[0]
    assert (
        copied.checkpoint == parent.checkpoint
        and copied.checkpoint is not parent.checkpoint
    )
    assert copied.state == "draft" and copied.audit_provenance["checkpoint_copied"]
    await service.branch_simulation(
        parent_simulation_id=parent.simulation_id,
        scenario_name="Override",
        scenario_config=scenario(seed=8),
        correlation_id=str(uuid.uuid4()),
        **scope(parent),
    )
    overridden = mock_db.add.call_args_list[-2].args[0]
    assert overridden.checkpoint["state"]["tick"] == 0
    assert overridden.input_sha256 != parent.input_sha256
    assert overridden.audit_provenance["input_override_restarted"]


async def test_completed_branch_cannot_refresh_evidence_expiry(service, mock_db):
    parent = record(complete=True)
    parent.completed_at = datetime.now(UTC) - timedelta(minutes=10)
    parent.evidence_expires_at = datetime.now(UTC) - timedelta(minutes=5)
    service._repo.get_by_id = service._repo.lock = AsyncMock(return_value=parent)
    service._network_svc.assert_network_workspace_access.return_value = parent
    await service.branch_simulation(
        parent_simulation_id=parent.simulation_id,
        scenario_name="Old evidence copy",
        correlation_id=str(uuid.uuid4()),
        **scope(parent),
    )
    copied = mock_db.add.call_args_list[-2].args[0]
    assert copied.completed_at == parent.completed_at
    assert copied.evidence_expires_at == parent.evidence_expires_at


async def test_resume_network_input_and_cross_tenant_denial(service):
    row = record(state="paused")
    service._repo.get_by_id = service._repo.lock = AsyncMock(return_value=row)
    args = dict(
        simulation_id=row.simulation_id,
        scenario_name="resume",
        validation_checks=[],
        correlation_id=str(uuid.uuid4()),
        **scope(row),
    )
    for extra in (
        {"network_id": uuid.uuid4()},
        {"network_id": row.network_id, "scenario_config": scenario(seed=8)},
        {"network_id": row.network_id, "requested_workspace_id": uuid.uuid4()},
    ):
        with pytest.raises(HTTPException) as err:
            await service.start_simulation(**{**args, **extra})
        assert err.value.status_code in {403, 409}
        assert row.state == "paused"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: setattr(r, "risk_gate", "blocked"),
        lambda r: setattr(r, "state", "paused"),
        lambda r: setattr(
            r, "evidence_expires_at", datetime.now(UTC) - timedelta(seconds=1)
        ),
        lambda r: setattr(r, "completed_at", datetime.now(UTC) - timedelta(minutes=6)),
        lambda r: setattr(r, "input_sha256", "0" * 64),
        lambda r: r.run_output.update(throughput_mbps=999),
        lambda r: setattr(r, "network_id", uuid.uuid4()),
        lambda r: setattr(r, "workspace_id", uuid.uuid4()),
        lambda r: r.scenario_config["action_binding"].update(plan_sha256="1" * 64),
    ],
)
async def test_execution_reference_fail_closed(service, mutate):
    binding = {
        "intent_id": str(uuid.uuid4()),
        "plan_sha256": "a" * 64,
        "network_state_sha256": "b" * 64,
    }
    row = record(policy_scenario(action_binding=binding), complete=True)
    service._repo.get_by_id = AsyncMock(return_value=row)
    args = dict(
        simulation_id=row.simulation_id,
        workspace_id=row.workspace_id,
        network_id=row.network_id,
        actor_id=row.requested_by_user_id,
        **binding,
    )
    evidence = await service.validate_execution_reference(**args)
    assert evidence["physical_safety_authorized"] is False
    assert evidence["policy_floors"] == POLICY_LIMITS | {"min_throughput_mbps": 0.0}
    mutate(row)
    with pytest.raises(HTTPException) as err:
        await service.validate_execution_reference(**args)
    assert err.value.status_code in {403, 409}


def _bound_args(row, binding):
    return dict(simulation_id=row.simulation_id, workspace_id=row.workspace_id, network_id=row.network_id,
                actor_id=row.requested_by_user_id, **binding)


async def test_passing_simulation_with_limits_weaker_than_policy_is_not_evidence(service):
    """Regression (C18): max_loss_pct=100 'passes' with 45% loss but cannot authorize execution."""
    binding = {"intent_id": str(uuid.uuid4()), "plan_sha256": "a" * 64, "network_state_sha256": "b" * 64}
    row = record(scenario(action_binding=binding), complete=True)
    assert row.risk_gate == "passed" and row.run_output["loss_pct"] == 45
    service._repo.get_by_id = AsyncMock(return_value=row)
    with pytest.raises(HTTPException) as err:
        await service.validate_execution_reference(**_bound_args(row, binding))
    assert err.value.status_code == 409
    assert err.value.detail["code"] == "SIMULATION_POLICY_VIOLATION"
    for limits in ({**POLICY_LIMITS, "max_latency_ms": 5000.0}, {**POLICY_LIMITS, "max_loss_pct": 1.5}):
        weaker = record(policy_scenario(action_binding=binding, limits=limits), complete=True)
        service._repo.get_by_id = AsyncMock(return_value=weaker)
        with pytest.raises(HTTPException) as err:
            await service.validate_execution_reference(**_bound_args(weaker, binding))
        assert err.value.detail["code"] == "SIMULATION_POLICY_VIOLATION"


async def test_policy_floors_are_server_configured_not_operator_supplied(service, monkeypatch):
    binding = {"intent_id": str(uuid.uuid4()), "plan_sha256": "a" * 64, "network_state_sha256": "b" * 64}
    strict = record(policy_scenario(action_binding=binding,
                                    limits={**POLICY_LIMITS, "min_throughput_mbps": 0.2}), complete=True)
    service._repo.get_by_id = AsyncMock(return_value=strict)
    monkeypatch.setattr(modeled, "get_settings", lambda: SimpleNamespace(
        SIMULATION_POLICY_MAX_LOSS_PCT=1.0, SIMULATION_POLICY_MAX_LATENCY_MS=1000.0,
        SIMULATION_POLICY_MIN_THROUGHPUT_MBPS=0.3))
    with pytest.raises(HTTPException) as err:
        await service.validate_execution_reference(**_bound_args(strict, binding))
    assert err.value.detail["code"] == "SIMULATION_POLICY_VIOLATION"
    monkeypatch.setattr(modeled, "get_settings", lambda: SimpleNamespace(
        SIMULATION_POLICY_MAX_LOSS_PCT=1.0, SIMULATION_POLICY_MAX_LATENCY_MS=1000.0,
        SIMULATION_POLICY_MIN_THROUGHPUT_MBPS=0.2))
    evidence = await service.validate_execution_reference(**_bound_args(strict, binding))
    assert evidence["policy_floors"]["min_throughput_mbps"] == 0.2


async def test_execution_reference_verifies_off_the_event_loop_every_time(service, monkeypatch):
    binding = {"intent_id": str(uuid.uuid4()), "plan_sha256": "a" * 64, "network_state_sha256": "b" * 64}
    row = record(policy_scenario(action_binding=binding), complete=True)
    service._repo.get_by_id = AsyncMock(return_value=row)
    calls = []
    real = modeled.asyncio.to_thread

    async def threaded(function, *args, **kwargs):
        calls.append(function)
        return await real(function, *args, **kwargs)

    monkeypatch.setattr(modeled.asyncio, "to_thread", threaded)
    for _ in range(2):
        await service.validate_execution_reference(**_bound_args(row, binding))
    # The security gate never reuses the read cache: one full verification per call.
    assert calls == [modeled._verify_values, modeled._verify_values]


async def test_compare_no_zero_fill_and_compatible_curves(service):
    a, b = record(complete=True), record(complete=True)
    b.network_id, b.workspace_id = a.network_id, a.workspace_id
    service._repo.get_by_id = AsyncMock(side_effect=[a, b])
    result = await service.compare_simulations(
        simulation_id=a.simulation_id,
        baseline_simulation_id=b.simulation_id,
        **scope(a),
    )
    assert result["compatible"] and result["deltas"] == {
        "latency_ms": 0,
        "loss_pct": 0,
        "throughput_mbps": 0,
    }
    b.run_output = {}
    service._repo.get_by_id = AsyncMock(side_effect=[a, b])
    result = await service.compare_simulations(
        simulation_id=a.simulation_id,
        baseline_simulation_id=b.simulation_id,
        **scope(a),
    )
    assert not result["compatible"] and all(
        v is None for v in result["deltas"].values()
    )


def _observation(**overrides):
    value = {
        "version": 1, "topology_id": "campus-small-v1", "run_id": "run", "sequence": 1, "observed_at": "now",
        "switches": [{"dpid": "0000000000000001", "name": "access1", "observed_at": "now",
                      "ports": [{"port_no": 2, "rx_bytes": 10, "tx_bytes": 5, "duration_sec": 1.0},
                                {"port_no": 1, "rx_bytes": 1, "tx_bytes": 1, "duration_sec": 1.0}],
                      "flows": [{"table_id": 0, "priority": 1, "cookie": 0, "packet_count": 3,
                                 "byte_count": 300, "duration_sec": 2.0}]}],
        "links": [{"src_dpid": "a", "src_port": 1, "dst_dpid": "b", "dst_port": 2},
                  {"src_dpid": "b", "src_port": 2, "dst_dpid": "a", "dst_port": 1}],
        "hosts": [{"name": "h1", "mac": "00:00:00:00:00:01", "ipv4": "10.0.0.1", "dpid": "a", "port_no": 3}],
        "queues": [{"dpid": "a", "port_no": 1, "observed_at": "now", "backlog_bytes": 10, "backlog_packets": 1}],
        "probes": [{"src_host": "h1", "dst_host": "h2", "observed_at": "now", "sent": 2, "received": 2,
                    "rtt_avg_ms": 1.0, "interval_seconds": 1.0}],
    }
    value.update(overrides)
    return value


def test_state_hash_covers_stable_topology_not_counters_or_timestamps():
    """ADR-028 C18: v2 hash is a stable projection; v1 changed on every sample."""
    binding_value = {"network_id": "n", "capacity": 1}
    binding = SimpleNamespace(model_dump=lambda **_: copy.deepcopy(binding_value))
    value = _observation()
    snapshot = SimpleNamespace(model_dump=lambda **_: copy.deepcopy(value))
    before = current_network_state_hash(binding=binding, snapshot=snapshot)
    # Sampling metadata, counters, reactive flow entries, backlog and probes are ignored.
    value.update(observed_at="later", sequence=99, queues=[], probes=[])
    value["switches"][0].update(observed_at="later", flows=[])
    value["switches"][0]["ports"][0].update(rx_bytes=10**9, tx_bytes=10**9, duration_sec=99.0)
    value["switches"][0]["ports"].reverse()
    value["links"].reverse()
    assert current_network_state_hash(binding=binding, snapshot=snapshot) == before
    assert stable_network_projection(value)["switches"][0]["ports"] == [1, 2]
    # Topology, run identity, host placement and binding configuration are covered.
    for key, mutated in (("run_id", "restarted"), ("links", value["links"][:1]),
                         ("hosts", [{**value["hosts"][0], "port_no": 4}])):
        original = copy.deepcopy(value[key])
        value[key] = mutated
        assert current_network_state_hash(binding=binding, snapshot=snapshot) != before
        value[key] = original
    value["switches"][0]["ports"].append({"port_no": 7, "rx_bytes": 0})
    assert current_network_state_hash(binding=binding, snapshot=snapshot) != before
    value["switches"][0]["ports"].pop()
    assert current_network_state_hash(binding=binding, snapshot=snapshot) == before
    binding_value["capacity"] = 2
    assert current_network_state_hash(binding=binding, snapshot=snapshot) != before


def test_state_hash_matches_real_emulation_models():
    import json

    from app.modules.telemetry.emulation import EmulationSnapshot
    from emulation.topology import manifest

    expected = manifest()
    names = {s["name"]: s["dpid"] for s in expected["switches"]}
    now = "2026-09-23T00:00:00+00:00"

    def snapshot(sequence, rx):
        return EmulationSnapshot.model_validate_json(json.dumps({"version": 1, "topology_id": expected["topology_id"],
            "run_id": str(uuid.UUID(int=7)), "sequence": sequence, "observed_at": now,
            "switches": [{"name": s["name"], "dpid": s["dpid"], "observed_at": now, "flows": [],
                          "ports": [{"port_no": 1, "rx_bytes": rx, "tx_bytes": rx, "rx_packets": 1, "tx_packets": 1,
                                     "rx_dropped": 0, "tx_dropped": 0, "duration_sec": 1.0}]}
                         for s in expected["switches"]],
            "hosts": expected["hosts"], "queues": [], "probes": [],
            "links": [{"src_dpid": names[a], "src_port": ap, "dst_dpid": names[b], "dst_port": bp}
                      for link in expected["links"] for (a, ap), (b, bp) in ((link["a"], link["b"]), (link["b"], link["a"]))
                      if a in names and b in names]}))

    binding = SimpleNamespace(model_dump=lambda **_: {"topology_id": expected["topology_id"]})
    assert (current_network_state_hash(binding=binding, snapshot=snapshot(1, 10))
            == current_network_state_hash(binding=binding, snapshot=snapshot(2, 10_000)))


async def test_detail_and_compare_verification_runs_in_thread_and_caches_per_revision(service, monkeypatch):
    row = record(complete=True)
    calls = []
    real = modeled.asyncio.to_thread

    async def threaded(function, *args, **kwargs):
        calls.append(function)
        return await real(function, *args, **kwargs)

    monkeypatch.setattr(modeled.asyncio, "to_thread", threaded)
    first = await verified_output_async(row)
    assert first == verified_output(row) and calls == [modeled._verify_values]
    assert await verified_output_async(row) is first and len(calls) == 1  # cache hit, no re-verification
    row.revision += 1  # a committed lifecycle/batch CAS always changes the revision
    assert await verified_output_async(row) == first and len(calls) == 2
    row.run_output = {**row.run_output, "output_sha256": "0" * 64}
    assert await verified_output_async(row) is None and len(calls) == 3
    service._repo.get_by_id = AsyncMock(return_value=row)
    detail = await service.get_simulation_detail(simulation_id=row.simulation_id, **scope(row))
    assert detail["validation"]["failure_reason"] == "model_evidence_invalid" and len(calls) == 3


@pytest.mark.parametrize("state", ["paused", "queued"])
async def test_same_state_transition_is_a_no_op(service, mock_db, state):
    """Regression: paused->paused bumped revision and enqueued a duplicate event."""
    row = record(state=state)
    row.status = state
    service._repo.get_by_id = service._repo.lock = AsyncMock(return_value=row)
    service._repo.active_count = AsyncMock(return_value=0)
    revision, validation = row.revision, dict(row.validation)
    if state == "paused":
        result = await service.pause_simulation(simulation_id=row.simulation_id, correlation_id="opaque-request",
                                                **scope(row))
        assert result["state"] == "paused"
    else:
        result = await service.start_simulation(simulation_id=row.simulation_id, network_id=row.network_id,
            scenario_name="resume", validation_checks=[], correlation_id="opaque-request", **scope(row))
        assert result["handoff"]["state"] == "queued" and result["queue_status"] == row.queue_status
    assert row.revision == revision and row.validation == validation
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()
    service._repo.active_count.assert_not_awaited()


async def test_real_transition_still_enqueues_once(service, mock_db):
    row = record(state="queued")
    service._repo.get_by_id = service._repo.lock = AsyncMock(return_value=row)
    result = await service.pause_simulation(simulation_id=row.simulation_id, correlation_id=str(uuid.uuid4()),
                                            **scope(row))
    assert result["state"] == "paused" and row.revision == 2
    assert mock_db.add.call_count == 1 and mock_db.commit.await_count == 1


async def test_workspace_active_quota_rejects_start_and_resume_with_429(service, mock_db, monkeypatch):
    monkeypatch.setattr(modeled, "get_settings", lambda: SimpleNamespace(SIMULATION_MAX_ACTIVE_PER_WORKSPACE=2))
    network = SimpleNamespace(network_id=uuid.uuid4(), workspace_id=uuid.uuid4())
    service._network_svc.assert_network_workspace_access.return_value = network
    service._repo.active_count = AsyncMock(return_value=2)
    with pytest.raises(HTTPException) as err:
        await service.start_simulation(network_id=network.network_id, scenario_name="new", simulation_id=None,
            validation_checks=[], correlation_id=str(uuid.uuid4()), requested_by_user_id="u",
            requested_workspace_id=network.workspace_id, claim_org_id=None, scenario_config=scenario())
    assert err.value.status_code == 429 and err.value.detail["code"] == "SIMULATION_QUOTA_EXCEEDED"
    assert err.value.headers["Retry-After"]
    service._repo.active_count.assert_awaited_once_with(network.workspace_id)
    paused = record(state="paused")
    service._repo.get_by_id = service._repo.lock = AsyncMock(return_value=paused)
    with pytest.raises(HTTPException) as err:
        await service.start_simulation(simulation_id=paused.simulation_id, network_id=paused.network_id,
            scenario_name="resume", validation_checks=[], correlation_id=str(uuid.uuid4()), **scope(paused))
    assert err.value.status_code == 429 and paused.state == "paused"
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()
    service._repo.active_count = AsyncMock(return_value=1)
    result = await service.start_simulation(simulation_id=paused.simulation_id, network_id=paused.network_id,
        scenario_name="resume", validation_checks=[], correlation_id=str(uuid.uuid4()), **scope(paused))
    assert result["handoff"]["state"] == "queued"


async def test_modeled_events_normalize_opaque_request_ids_and_keep_original(service, mock_db):
    network = SimpleNamespace(network_id=uuid.uuid4(), workspace_id=uuid.uuid4())
    service._network_svc.assert_network_workspace_access.return_value = network
    service._repo.active_count = AsyncMock(return_value=0)
    result = await service.start_simulation(network_id=network.network_id, scenario_name="new", simulation_id=None,
        validation_checks=[], correlation_id="client-trace-1", requested_by_user_id="u",
        requested_workspace_id=network.workspace_id, claim_org_id=None, scenario_config=scenario())
    from app.core.correlation import correlation_uuid

    expected = str(correlation_uuid("client-trace-1"))
    record_row, outbox = (call.args[0] for call in mock_db.add.call_args_list)
    assert result["handoff"]["correlation_id"] == expected and result["handoff"]["request_id"] == "client-trace-1"
    assert record_row.audit_provenance["correlation_id"] == expected
    assert record_row.audit_provenance["request_id"] == "client-trace-1"
    assert outbox.envelope["correlation_id"] == expected


def test_historical_or_changed_output_never_verified():
    row = record(complete=True)
    assert verified_output(row)
    row.run_output["output_sha256"] = digest({})
    assert verified_output(row) is None
    row.scenario_config = None
    assert verified_output(row) is None


async def test_detail_reports_whether_limits_can_authorize_execution(service):
    for config, allowed in ((policy_scenario(), True), (scenario(), False)):
        row = record(config, complete=True)
        service._repo.get_by_id = AsyncMock(return_value=row)
        detail = await service.get_simulation_detail(simulation_id=row.simulation_id, **scope(row))
        assert detail["execution_policy"] == {
            "policy_floors": {"max_loss_pct": 1.0, "max_latency_ms": 1000.0, "min_throughput_mbps": 0.0},
            "limits_respect_policy": allowed}
