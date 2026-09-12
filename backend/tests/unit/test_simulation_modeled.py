"""Modeled scope, branch, reference and legacy-consumer regressions."""

import copy
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.simulation.evaluator import advance, digest
from app.modules.simulation.modeled import current_network_state_hash, verified_output
from app.modules.simulation.service import (
    SimulationStartService,
    SimulationTerminalEventService,
)
from tests.simulation_support import record, scenario


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
    row = record(scenario(action_binding=binding), complete=True)
    service._repo.get_by_id = AsyncMock(return_value=row)
    args = dict(
        simulation_id=row.simulation_id,
        workspace_id=row.workspace_id,
        network_id=row.network_id,
        actor_id=row.requested_by_user_id,
        **binding,
    )
    assert (await service.validate_execution_reference(**args))[
        "physical_safety_authorized"
    ] is False
    mutate(row)
    with pytest.raises(HTTPException) as err:
        await service.validate_execution_reference(**args)
    assert err.value.status_code in {403, 409}


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


def test_state_hash_ignores_only_outer_observed_at_and_sorts_objects():
    binding = SimpleNamespace(model_dump=lambda **_: {"network_id": "n", "capacity": 1})
    value = {
        "observed_at": "now",
        "sequence": 1,
        "run_id": "run",
        "links": [{"id": 1}, {"id": 2}],
    }
    snapshot = SimpleNamespace(model_dump=lambda **_: copy.deepcopy(value))
    before = current_network_state_hash(binding=binding, snapshot=snapshot)
    value["observed_at"] = "later"
    value["links"].reverse()
    assert current_network_state_hash(binding=binding, snapshot=snapshot) == before
    value["sequence"] += 1
    assert current_network_state_hash(binding=binding, snapshot=snapshot) != before


def test_historical_or_changed_output_never_verified():
    row = record(complete=True)
    assert verified_output(row)
    row.run_output["output_sha256"] = digest({})
    assert verified_output(row) is None
    row.scenario_config = None
    assert verified_output(row) is None
