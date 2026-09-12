import ast
import hashlib
import math
import runpy
from pathlib import Path

import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env
from pydantic import ValidationError

from nanfo_routing.contracts import (
    CONTRACT,
    FRAME_DIM,
    SPLITS,
    STATE_DIM,
    Observation,
    Request,
    Response,
    jsonBytes,
    parseJson,
    validateSeed,
)
from nanfo_routing.env import InvalidMeasurement, RoutingEnv, encode, heuristic, rewardComponents
from nanfo_routing.evidence import validateMeasurement
from nanfo_routing.transport import DockerTransport, TransportError


def test_state_fixed_topology_absolute_demand_masks(observation):
    raw = Observation.model_validate(observation)
    state = encode([raw])
    assert state.shape == (STATE_DIM,)
    assert STATE_DIM == 16
    assert state[7] == pytest.approx(np.log1p(0.3))
    observation["offered_mbps"] *= 2
    observation["goodput_mbps"] *= 2
    bigger = encode([Observation.model_validate(observation)])
    assert bigger[7] == pytest.approx(np.log1p(0.6))
    assert np.expm1(bigger[6]) == pytest.approx(np.expm1(state[6]) * 2)
    observation["latency_ms"] = None
    missing = encode([Observation.model_validate(observation)])
    assert missing[4] == 0 and missing[13] == 0
    assert missing[-2:].tolist() == [1.0, 0.0]


def test_reward_contributions_and_scaling(observation):
    reward = rewardComponents(Observation.model_validate(observation), 0)
    assert reward["total"] == pytest.approx(0.9 - 0.1 - 0.1 - 0.08 - 0.02)
    assert reward["total"] == sum(reward["contributions"].values())
    observation["previous_action"] = 1
    changed = rewardComponents(Observation.model_validate(observation), 0)
    assert changed["total"] == pytest.approx(reward["total"] - 0.05)
    observation["goodput_mbps"] = 100.0
    assert rewardComponents(Observation.model_validate(observation), 1)["raw"]["goodput_ratio"] == 1
    observation["latency_ms"] = None
    with pytest.raises(InvalidMeasurement):
        rewardComponents(Observation.model_validate(observation), 1)


def test_hysteresis_uses_measured_pressure(observation):
    assert heuristic(Observation.model_validate(observation)) == 1
    observation["path_utilization"] = [0.21, 0.2]
    observation["path_queue_packets"] = [0.0, 0.0]
    assert heuristic(Observation.model_validate(observation)) == 0


def test_reset_step_time_limit_and_session_close(transport):
    env = RoutingEnv(transport, episode_steps=2)
    state, info = env.reset(seed=1000)
    assert env.observation_space.contains(state)
    assert info["valid_transition"]
    assert (
        transport.requests[0]
        == Request(command="reset", scenario="path0", seed=1000, episode_steps=2).model_dump()
    )
    assert env.step(1)[2:4] == (False, False)
    _, _, terminated, truncated, info = env.step(1)
    assert not terminated and truncated and info["valid_transition"] and info["time_limit"]
    env.reset(seed=1001)
    env.close()
    assert [row["command"] for row in transport.requests] == [
        "reset",
        "step",
        "step",
        "reset",
        "close",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["data"]["observation"].update(latency_ms=None),
        lambda r: r["data"]["observation"].update(loss_fraction=1.1),
        lambda r: r["data"]["observation"].update(goodput_mbps=float("nan")),
        lambda r: r["data"]["observation"].update(path_utilization=[0.5]),
        lambda r: r["data"]["observation"].update(previous_action=True),
        lambda r: r["data"]["observation"].update(latency_ms="1.0"),
        lambda r: r["data"].update(episode_id="wrong"),
        lambda r: r["data"].update(step_index=0),
        lambda r: r["data"].update(seed=3000),
        lambda r: r["data"].update(mode="ospf"),
        lambda r: r["data"].update(scenario="burst"),
        lambda r: r["data"].update(truncated=True),
        lambda r: r["data"].update(evidence={}),
        lambda r: r["data"]["evidence"].update(error="uncertain state"),
        lambda r: r["data"]["evidence"].update(cleanup_verified=False),
        lambda r: r.update(version=True),
        lambda r: r.update(extra=1),
        lambda r: r.update(ok=False, error="failed", data=None),
    ],
)
def test_invalid_windows_truncate_without_reward(transport, mutation):
    env = RoutingEnv(transport, episode_steps=2)
    env.reset(seed=1000)
    transport.mutate = mutation
    _, reward, terminated, truncated, info = env.step(0)
    assert math.isnan(reward) and not terminated and truncated
    assert not info["valid_transition"] and info["reward"] is None
    with pytest.raises(InvalidMeasurement):
        env.step(0)


def test_invalid_horizon_cannot_bootstrap(transport):
    env = RoutingEnv(transport, episode_steps=2)
    env.reset(seed=1000)
    env.step(0)
    transport.mutate = lambda raw: raw["data"].update(truncated=True)
    assert env.step(0)[4]["valid_transition"] is False


def test_invalid_reset_and_action_fail_closed(transport):
    env = RoutingEnv(transport)
    with pytest.raises(ValueError):
        env.reset(seed=3000)
    assert not transport.requests
    env.reset(seed=1000)
    for action in (-1, 2, True):
        with pytest.raises(ValueError):
            env.step(action)
    transport.mutate = lambda raw: raw["data"]["observation"].update(latency_ms=None)
    env.close()
    with pytest.raises(InvalidMeasurement):
        env.reset(seed=1001)


def test_early_termination_is_invalid_not_absorbing(transport):
    env = RoutingEnv(transport, episode_steps=4)
    env.reset(seed=1000)
    transport.mutate = lambda raw: raw["data"].update(terminated=True)
    result = env.step(0)
    assert result[2:4] == (False, True) and not result[4]["valid_transition"]


def test_no_train_test_leakage():
    sets = {key: set(range(bounds[0], bounds[1] + 1)) for key, bounds in SPLITS.items()}
    assert not sets["train"] & sets["validation"]
    assert not sets["train"] & sets["test"]
    assert not sets["validation"] & sets["test"]
    for split in SPLITS:
        for other in SPLITS:
            if split != other:
                with pytest.raises(ValueError):
                    validateSeed(split, SPLITS[other][0])
    with pytest.raises(ValueError):
        validateSeed("train", True)


@pytest.mark.parametrize("name", ["-x", "a;sh", "$(id)", "a b", "x/../y", "x" * 129])
def test_transport_rejects_shell_and_unbounded_config(name):
    with pytest.raises(ValueError):
        DockerTransport(container=name)
    with pytest.raises(ValueError):
        DockerTransport(timeout=1000)


def test_response_schema_rejects_nonfinite_evidence(transport):
    raw = transport.exchange(Request(command="reset", scenario="low", seed=1000))
    raw["data"]["evidence"]["bad"] = float("inf")
    with pytest.raises(ValidationError):
        Response.model_validate(raw)


def test_transport_failure_invalidates_window(transport):
    env = RoutingEnv(transport)
    env.reset(seed=1000)

    def fail(request):
        raise TransportError("timeout")

    transport.exchange = fail
    assert env.step(0)[4]["valid_transition"] is False


def test_gym_contract_with_seed_adapter(transport):
    # Gym checker uses seed=123 outside ADR011's splits, so adapt only this checker fixture.
    class CheckerEnv(RoutingEnv):
        def reset(self, *, seed=None, options=None):
            if self.active:
                self.active = False
            result = super().reset(seed=1000 if seed is None else 1000 + seed % 1000)
            if seed is not None:
                self._np_random = np.random.default_rng(seed)
            result[1]["raw_response"]["data"]["episode_id"] = "stable-checker-fixture"
            return result

    # Fresh real episode IDs are intentionally nondeterministic, despite seeded workloads.
    env = CheckerEnv(transport)
    env.spec = __import__("gymnasium").envs.registration.EnvSpec(
        "RoutingUnitFixture-v0", nondeterministic=True
    )
    check_env(env, skip_render_check=True, skip_close_check=True)


@pytest.mark.parametrize("evidence", [{"error": "failed"}, {"cleanup_verified": False}])
def test_reset_rejects_failed_evidence_even_with_complete_metrics(transport, evidence):
    transport.mutate = lambda raw: raw["data"]["evidence"].update(evidence)
    env = RoutingEnv(transport)
    with pytest.raises(InvalidMeasurement):
        env.reset(seed=1000)
    with pytest.raises(InvalidMeasurement, match="failed session"):
        env.reset(seed=1001)
    env.close()
    assert transport.requests[-1]["step_index"] == 0


@pytest.mark.parametrize("raw", ['{"ok":true,"ok":false}', '{"x":NaN}', '{"x":Infinity}'])
def test_wire_json_rejects_duplicate_and_nonfinite_values(raw):
    with pytest.raises(ValueError):
        parseJson(raw)


def test_failed_window_cannot_be_followed_by_reset(transport):
    env = RoutingEnv(transport)
    env.reset(seed=1000)
    transport.mutate = lambda raw: raw["data"].update(truncated=True)
    env.step(0)
    with pytest.raises(InvalidMeasurement, match="failed session"):
        env.reset(seed=1001)


def test_frozen_topology_matches_trusted_lab_manifest():
    # Read-only cross-package contract check; no Mininet/Ryu dependency or live service.
    path = Path(__file__).resolve().parents[2] / "emulation" / "topology.py"
    manifest = runpy.run_path(str(path))["manifest"]()
    assert manifest["topology_id"] == CONTRACT["topology_id"]
    assert [row["name"] for row in manifest["switches"]] == CONTRACT["nodes"]
    links = manifest["links"][:7]
    assert [[row["a"][0], row["b"][0]] for row in links] == CONTRACT["link_endpoints"]
    assert [row["capacity_mbps"] for row in links] == CONTRACT["link_capacity_mbps"]
    assert [row["delay_ms"] for row in links] == CONTRACT["link_delay_ms"]
    for link in manifest["links"]:
        assert link["max_queue_size"] == CONTRACT["queue_capacity_packets"]


def test_history_rolling_reset_and_no_future_input(transport):
    env = RoutingEnv(transport, episode_steps=4)
    initial, _ = env.reset(seed=1000)
    np.testing.assert_array_equal(initial[:FRAME_DIM], initial[-FRAME_DIM:])
    one = env.step(1)[0].reshape(1, FRAME_DIM)
    assert one[-1, -2:].tolist() == [0, 1]
    two = env.step(0)[0].reshape(1, FRAME_DIM)
    assert two[-1, -2:].tolist() == [1, 0]
    env.step(1)
    env.step(1)
    reset, _ = env.reset(seed=1000)
    np.testing.assert_array_equal(initial, reset)
    # Another seed changes measured demand, but identity itself is not an actor input.
    other = RoutingEnv(transport, scenario="path0", episode_steps=4)
    state, _ = other.reset(seed=1001)
    assert not np.array_equal(initial, state)
    np.testing.assert_array_equal(state, encode([other.data.observation]))


def test_reward_actual_sent_denominator_not_target(observation):
    observation.update(actual_offered_mbps=8.0, goodput_mbps=7.2)
    reward = rewardComponents(Observation.model_validate(observation), 0)
    assert reward["raw"]["goodput_ratio"] == pytest.approx(0.9)
    assert encode([Observation.model_validate(observation)])[7] == pytest.approx(np.log1p(0.3))


def test_verified_outage_is_learnable_but_missing_probe_is_not(transport):
    env = RoutingEnv(transport, episode_steps=4)
    env.reset(seed=1000)

    def outage(raw):
        data = raw["data"]
        data["observation"]["latency_ms"] = None
        data["evidence"]["ping"].update(received=0, rtt_avg_ms=None)
        data["evidence"].update(service_outage=True, latency_censored=True, latency_timeout_ms=1000)

    transport.mutate = outage
    state, reward, _, _, info = env.step(0)
    assert info["valid_transition"] and math.isfinite(reward)
    assert info["reward"]["delay_censored"]
    assert info["reward"]["observed_latency_ms"] is None
    assert info["reward"]["raw"]["delay"] == 20.0
    assert state.reshape(1, FRAME_DIM)[-1, 13] == 0
    transport.mutate = lambda raw: raw["data"]["evidence"].update(ping=None)
    assert not env.step(0)[4]["valid_transition"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e.update(measurement_complete=False),
        lambda e: e.update(spec_hash="0" * 64),
        lambda e: e["post_control_interval"].update(end=101.0),
        lambda e: e["udp_sent"][0].update(packets=0),
        lambda e: e["udp_received"][0].update(bytes=1),
        lambda e: e["udp_received"][0].update(started_monotonic_seconds=103.0),
        lambda e: e["ping"].update(received=0),
        lambda e: e["ping"].update(sent=0),
        lambda e: e.update(actual_offered_mbps=[1.0, 1.0]),
        lambda e: e["counter_windows"].pop("access1-eth1"),
        lambda e: e["counter_windows"]["access1-eth1"]["after"].update(tx_bytes=-1),
        lambda e: e["queue_peaks"]["access1-eth1"].update(backlog_packets=999),
        lambda e: e["queue_peaks"]["access1-eth1"].update(monotonic_seconds=0),
        lambda e: e["route"]["readback"].update(owned={}),
        lambda e: e["route_end"].update(changed=True),
        lambda e: e["phase_relationship"].update(measurement_phase_index=99),
    ],
)
def test_plausible_aggregates_do_not_override_bad_evidence(transport, mutation):
    env = RoutingEnv(transport)
    env.reset(seed=1000)
    transport.mutate = lambda raw: mutation(raw["data"]["evidence"])
    assert not env.step(0)[4]["valid_transition"]


def test_environment_spec_mismatch_rejected_on_reset(transport):
    env = RoutingEnv(transport, expectedSpec={"unrecognized": True})
    with pytest.raises(InvalidMeasurement, match="spec"):
        env.reset(seed=1000)


def test_current_producer_outcome_and_spec_match_client(transport):
    from conftest import producerSpec

    # Execute only the producer's pure measurement derivation, never its lab lifecycle.
    path = Path(__file__).resolve().parents[2] / "emulation" / "experiment.py"
    source = ast.parse(path.read_text())
    selected = [
        node
        for node in source.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ENVIRONMENT_SPEC"
                for target in node.targets
            )
        )
        or (isinstance(node, ast.FunctionDef) and node.name == "measurementOutcome")
    ]
    namespace = {"math": math}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    request = Request(command="reset", seed=1000, scenario="low", episode_steps=4)
    raw = transport.exchange(request)
    data = raw["data"]
    evidence = data["evidence"]
    spec = {
        **producerSpec(),
        "source_files": evidence["environment_spec"]["source_files"],
        "source_sha256": evidence["environment_spec"]["source_sha256"],
    }
    evidence.update(environment_spec=spec, spec_hash=hashlib.sha256(jsonBytes(spec)).hexdigest())
    for outage in (False, True):
        if outage:
            evidence["ping"].update(received=0, rtt_avg_ms=None)
        namespace["measurementOutcome"](
            data["observation"], evidence, evidence["control_start_monotonic_seconds"]
        )
        validateMeasurement(Response.model_validate(raw).data, request)
