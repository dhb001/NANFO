"""Analytic ADR-017 fluid/conservation/reproducibility regressions."""

import copy
import math

import pytest
from pydantic import ValidationError

from app.modules.simulation.evaluator import (
    advance,
    canonical_config,
    digest,
    initial_checkpoint,
    output,
    validate_checkpoint,
    workload_hash,
)
from app.modules.simulation.schemas import ScenarioConfig
from tests.simulation_support import completed, scenario


def test_analytic_bottleneck_finite_buffer_and_residence():
    config = scenario()
    _, result = completed(config)
    assert result["offered_bytes"] == 250000
    assert result["delivered_bytes"] == 125000
    assert result["dropped_bytes"] == 112500
    assert result["queued_bytes"] == 12500
    assert result["inflight_bytes"] == 0
    assert result["throughput_mbps"] == 1
    assert result["loss_pct"] == 45
    assert 100 < result["latency_ms"] < 200
    # Independent analytic mixed queue moment recurrence.
    moment = delivered_moment = 0
    for tick in range(10):
        accepted = 25000 if tick == 0 else 12500
        moment += accepted * tick * 100
        served_moment = moment / 2
        moment -= served_moment
        delivered_moment += 12500 * (tick + 1) * 100 - served_moment
    assert result["latency_ms"] == delivered_moment / 125000
    assert result["risk_gate"] == "passed"
    strict = config.model_copy(
        update={"limits": config.limits.model_copy(update={"max_loss_pct": 1.0})}
    )
    assert completed(strict)[1]["risk_gate"] == "blocked"


@pytest.mark.parametrize(
    "delay,delivered,inflight,latency",
    [(0, 125000, 0, 100), (100, 112500, 12500, 200), (150, 100000, 25000, 300)],
)
def test_exact_pipeline_horizon(delay, delivered, inflight, latency):
    value = scenario().model_dump(mode="json")
    value["flows"][0]["demand_mbps"] = [1.0]
    value["links"][0]["delay_ms"] = float(delay)
    _, result = completed(ScenarioConfig.model_validate(value))
    assert result["delivered_bytes"] == delivered
    assert result["inflight_bytes"] == inflight
    assert result["latency_ms"] == latency


def test_multihop_conservation_and_route_effect_no_same_tick_forwarding():
    value = scenario().model_dump(mode="json")
    value["links"].append(
        {
            **value["links"][0],
            "link_id": "bc",
            "source": "b",
            "target": "c",
            "capacity_mbps": 0.5,
        }
    )
    value["flows"][0].update(target="c", path=["ab", "bc"])
    config = ScenarioConfig.model_validate(value)
    _, result = completed(config)
    assert result["throughput_mbps"] == 0.45
    assert result["latency_ms"] > 200
    assert result["trace"][0]["links"]["bc"]["served_bytes"] == 0
    assert result["trace"][1]["links"]["bc"]["served_bytes"] == 6250
    assert result["offered_bytes"] == pytest.approx(
        sum(
            result[k]
            for k in (
                "delivered_bytes",
                "dropped_bytes",
                "queued_bytes",
                "inflight_bytes",
            )
        )
    )


def test_proportional_flows_background_never_attributed():
    value = scenario().model_dump(mode="json")
    value["duration_ticks"] = 1
    value["links"][0].update(buffer_bytes=100000.0, initial_queue_bytes=12500.0)
    value["flows"][0]["demand_mbps"] = [1.0]
    value["flows"].append({**value["flows"][0], "flow_id": "g", "demand_mbps": [2.0]})
    _, result = completed(ScenarioConfig.model_validate(value))
    assert result["flows"]["f"]["delivered_bytes"] == 3125
    assert result["flows"]["g"]["delivered_bytes"] == 6250
    assert result["initial_background"]["ab"] == {
        "initial_bytes": 12500,
        "queued_bytes": 9375,
        "inflight_bytes": 0,
        "delivered_bytes": 3125,
    }
    assert result["offered_bytes"] == 37500


def test_noninteger_replay_batching_order_and_no_input_mutation():
    value = scenario().model_dump(mode="json")
    value["links"][0].update(
        capacity_mbps=0.713, delay_ms=241.3, initial_queue_bytes=978.8
    )
    value["flows"].append({**value["flows"][0], "flow_id": "g", "demand_mbps": [0.673]})
    config = ScenarioConfig.model_validate(value)
    initial = initial_checkpoint(config)
    original = copy.deepcopy(initial)
    one = initial
    for _ in range(config.duration_ticks):
        one = advance(config, one, ticks=1)
    assert initial == original
    assert completed(config)[0] == one
    value["flows"].reverse()
    reverse = ScenarioConfig.model_validate(value)
    assert completed(reverse)[1] == output(config, one)
    assert canonical_config(reverse) == canonical_config(config)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.update(version=True),
        lambda c: c.update(duration_ticks=1001),
        lambda c: c.update(tick_ms=True),
        lambda c: c.update(seed="7"),
        lambda c: c["links"][0].update(capacity_mbps=math.inf),
        lambda c: c["links"][0].update(initial_queue_bytes=25001.0),
        lambda c: c["flows"][0].update(path=["missing"]),
        lambda c: c["flows"][0].update(path=["ab", "ab"]),
        lambda c: c["flows"][0].update(target="missing"),
        lambda c: c["flows"][0].update(demand_mbps=[1.0, 2.0]),
        lambda c: c["links"].append(c["links"][0]),
        lambda c: c["flows"].append(c["flows"][0]),
        lambda c: c.update(unknown=1),
        lambda c: c.update(
            duration_ticks=1000,
            flows=[{**c["flows"][0], "flow_id": f"f{i}"} for i in range(9)],
        ),
    ],
)
def test_strict_graph_finite_and_work_bounds(mutation):
    value = scenario().model_dump(mode="json")
    mutation(value)
    with pytest.raises(ValidationError):
        ScenarioConfig.model_validate(value)


def test_zero_demand_cannot_pass_unavailable_latency_and_loss():
    value = scenario().model_dump(mode="json")
    value["flows"][0]["demand_mbps"] = [0.0]
    _, result = completed(ScenarioConfig.model_validate(value))
    assert result["latency_ms"] is None and result["loss_pct"] is None
    assert result["risk_gate"] == "blocked"


def test_checkpoint_corruption_and_input_change_rejected():
    config = scenario()
    checkpoint = advance(config, initial_checkpoint(config))
    bad = copy.deepcopy(checkpoint)
    bad["state"]["tick"] = 0
    with pytest.raises(ValueError):
        advance(config, bad)
    bad = copy.deepcopy(checkpoint)
    bad["state"]["flows"]["f"]["delivered_bytes"] += 1
    bad["checkpoint_sha256"] = digest(bad["state"])
    with pytest.raises(ValueError, match="conservation"):
        validate_checkpoint(config, bad)
    with pytest.raises(ValueError):
        advance(scenario(seed=8), checkpoint)


def test_workload_allows_route_change_not_demand_change():
    config = scenario()
    value = config.model_dump(mode="json")
    value["links"][0]["capacity_mbps"] = 20.0
    assert workload_hash(config) == workload_hash(ScenarioConfig.model_validate(value))
    value["flows"][0]["demand_mbps"] = [3.0]
    assert workload_hash(config) != workload_hash(ScenarioConfig.model_validate(value))
