"""ADR014 offline contracts only. No fixture is a qualifying learned policy."""

import hashlib
from copy import deepcopy
from types import SimpleNamespace

import pytest

from nanfo_routing import cli, expanded, extended_supervisor, qualification
from nanfo_routing.contracts import Request, Response, jsonBytes
from nanfo_routing.drain import validateDrain
from nanfo_routing.evidence import validateMeasurement
from nanfo_routing.ppo import PPOConfig, generalizedAdvantage


def test_plan_fresh_disjoint_fixed_budget_and_not_old_pilots(tmp_path):
    plan = expanded.frozenPlan()
    assert plan["collection_budget_seconds"] == 7200
    assert plan["minimum_quality_stop_transitions"] == 512
    assert plan["checkpoint_transitions"] == list(range(64, 1025, 64))
    assert plan["train_seeds"] == list(range(1600, 1856))
    assert plan["validation_seeds"] == list(range(2700, 2708))
    assert plan["test_seeds"] == list(range(3900, 3912))
    groups = [
        set(plan[key])
        for key in ("train_seeds", "validation_seeds", "test_seeds", "calibration_seeds")
    ]
    assert sum(map(len, groups)) == len(set.union(*groups))
    assert not groups[0] & set(range(1500, 1548))
    path = tmp_path / "plan.json"
    path.write_bytes(jsonBytes(plan))
    assert qualification.readPlan(path)[0] == plan
    plan["ppo_config"]["gamma"] = 0.95
    path.write_bytes(jsonBytes(plan))
    with pytest.raises(ValueError, match="ADR014"):
        qualification.readPlan(path)
    assert qualification.frozenPlan()["version"] == 3


@pytest.mark.parametrize("seed,episodes", [(1500, 16), (1600, 8), (1616, 16), (2700, 16)])
def test_no_micro_pilot_or_skip_or_validation_warmstart(seed, episodes):
    plan = expanded.frozenPlan()
    with pytest.raises(ValueError, match="next unique"):
        expanded.checkTrainingBlock(
            plan, list(range(seed, seed + episodes)), PPOConfig(**plan["ppo_config"]), None
        )


def test_resume_exact_config_seed_and_counters(monkeypatch):
    plan = expanded.frozenPlan()
    config = PPOConfig(**plan["ppo_config"])
    parent = SimpleNamespace(
        config=config,
        transitions=64,
        updates=4,
        environment_spec={"version": 4},
        training_seeds=list(range(1600, 1616)),
    )
    monkeypatch.setattr(expanded, "loadCheckpoint", lambda *a, **k: (None, parent))
    expanded.checkTrainingBlock(plan, list(range(1616, 1632)), config, "parent")
    parent.environment_spec["version"] = 3
    with pytest.raises(ValueError, match="exact V4"):
        expanded.checkTrainingBlock(plan, list(range(1616, 1632)), config, "parent")
    with pytest.raises(ValueError, match="hyperparameters"):
        expanded.checkTrainingBlock(plan, list(range(1600, 1616)), PPOConfig(), None)


def test_gae_stationary_horizon_no_reset_leak_or_terminal_bootstrap():
    advantage, returns = generalizedAdvantage(
        [1, 2, 3, 4, 100],
        [0] * 5,
        [10] * 5,
        [False, False, False, True, True],
        [False] * 5,
        gamma=0.9,
        gaeLambda=0.95,
    )
    expected = [0, 0, 12 + 0.855 * 4, 4, 100]
    expected[1] = 11 + 0.855 * expected[2]
    expected[0] = 10 + 0.855 * expected[1]
    assert advantage.tolist() == pytest.approx(expected)
    assert returns.tolist() == pytest.approx(expected)


def test_learning_tracks_probabilities_without_argmax_gate():
    def row(p):
        return {
            "validation_mean_reward": -1,
            "directional_dependence": {
                key: {"mean_desired_probability": p, "desired_route_fraction": 0}
                for key in ("path0", "path1")
            },
        }

    assert extended_supervisor.learning([row(0.2)] * 3)
    assert not extended_supervisor.learning([row(0.2)] * 8)
    assert extended_supervisor.learning([row(0.2)] * 2 + [row(0.24)] * 2)


def test_actual_direction_not_inconsistent_swap_veto(observation):
    plan = expanded.frozenPlan()

    def decide(state, **kwargs):
        # Test double uses latency marker (which pressure swap leaves unchanged).
        action = int(state[4] > 1)
        return action, 0, 0, [0.2, 0.8] if action else [0.8, 0.2]

    agent = SimpleNamespace(model=SimpleNamespace(decide=decide))
    learned = {
        "reconstructed_steps": [
            {
                "scenario": f"path{i % 2}",
                "action": 1 - i % 2,
                "input": {**observation, "latency_ms": 200 if i % 2 == 0 else 1},
            }
            for i in range(32)
        ]
    }
    result = expanded.directionalDependence(agent, learned, plan)
    assert all(row["desired_route_fraction"] == 1 for row in result.values())
    assert all(row["pressure_swap_desired_route_fraction"] == 0 for row in result.values())
    assert all(row["mean_desired_probability"] == 0.8 for row in result.values())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e.update(drain_status="timeout"),
        lambda e: e.update(drain_end=e["drain_begin"] + 4),
        lambda e: e["drain_empty_observations"].pop(),
        lambda e: e["queue_begin"].pop("h1-eth0"),
        lambda e: e["queue_end"]["h1-eth0"].update(backlog_bytes=1200),
        lambda e: e["queue_end"]["h1-eth0"]["raw_leaf_qdiscs"][0].update(qlen=1),
        lambda e: e.update(late_received_packets=[0, 0]),
        lambda e: e["udp_received"][0].update(finished_monotonic_seconds=e["drain_begin"]),
        lambda e: e["drain_empty_observations"][1].update(start=e["drain_begin"]),
        lambda e: e.update(senders_stopped_monotonic_seconds=e["drain_end"] + 1),
    ],
)
def test_drain_fails_closed_on_raw_queues_endpoints_and_chronology(transport, mutation):
    request = Request(command="reset", seed=1600, scenario="path0")
    raw = transport.exchange(request)
    validateMeasurement(Response.model_validate(raw).data, request)
    mutation(raw["data"]["evidence"])
    with pytest.raises(ValueError):
        validateMeasurement(Response.model_validate(raw).data, request)


def test_goodput_v4_uses_final_delivered_bytes_not_drain_time(transport):
    request = Request(command="reset", seed=1600, scenario="path0")
    raw = transport.exchange(request)
    e = raw["data"]["evidence"]
    validateDrain(e)
    o = raw["data"]["observation"]
    assert o["goodput_mbps"] == pytest.approx(
        e["udp_received"][0]["bytes"] * 8 / e["udp_sent"][0]["duration_seconds"] / 1e6
    )
    o["goodput_mbps"] = (
        e["udp_received"][0]["bytes"] * 8 / e["udp_received"][0]["duration_seconds"] / 1e6
    )
    with pytest.raises(ValueError, match="disagrees"):
        validateMeasurement(Response.model_validate(raw).data, request)


def test_release_missing_or_unreleased_never_launches(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(extended_supervisor, "outputPath", lambda *a, **k: tmp_path / "new")
    monkeypatch.setattr(extended_supervisor.Supervisor, "command", lambda *a, **k: calls.append(a))
    path = tmp_path / "release.json"
    path.write_bytes(jsonBytes({"released": False}))
    assert (
        extended_supervisor.main(
            [
                "run",
                "--operator-experiment",
                "--image-id",
                "sha256:" + "a" * 64,
                "--release",
                str(path),
                "--output",
                str(tmp_path / "new"),
            ]
        )
        == 1
    )
    assert not calls and not (tmp_path / "new").exists()


def test_v4_validation_checkpoint_identity_allows_multiple_not_retries(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    path.write_bytes(jsonBytes(expanded.frozenPlan()))
    args = cli.parser().parse_args(
        [
            "evaluate",
            "--operator-experiment",
            "--parent-approved",
            "--lab-released",
            "--plan",
            str(path),
            "--output",
            str(tmp_path / "eval"),
            "--split",
            "validation",
            "--seed",
            "2700",
            "--episodes",
            "8",
            "--model-seed",
            "44",
            "--checkpoint",
            str(tmp_path / "model"),
        ]
    )
    monkeypatch.setattr(
        qualification,
        "loadCheckpoint",
        lambda *a: (None, SimpleNamespace(config=PPOConfig(seed=44))),
    )
    identity = {"checkpoint_sha256": "a" * 64}
    monkeypatch.setattr(qualification, "inspectCheckpoint", lambda *a: deepcopy(identity))
    with qualification.collectionAdmission(args):
        pass
    with pytest.raises(ValueError, match="already consumed"):
        with qualification.collectionAdmission(args):
            pass
    identity["checkpoint_sha256"] = "b" * 64
    with qualification.collectionAdmission(args):
        pass
    assert hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_two_fresh_blocks_resume_exact_rng_metadata_and_lineage(
    tmp_path, monkeypatch, transport
):
    from nanfo_routing.artifacts import loadCheckpoint

    planPath = tmp_path / "plan.json"
    planPath.write_bytes(jsonBytes(expanded.frozenPlan()))
    monkeypatch.setattr(cli, "DockerTransport", lambda *a: transport)
    monkeypatch.setattr(qualification, "actionEffectChecks", lambda *a: ([], {}))
    monkeypatch.setattr(expanded, "actionEffectChecks", lambda *a: ([], {}))
    previous = None
    for index in range(2):
        output = tmp_path / f"train-{index + 1:02}"
        args = [
            "train",
            "--operator-experiment",
            "--parent-approved",
            "--lab-released",
            "--plan",
            str(planPath),
            "--output",
            str(output),
            "--seed",
            str(1600 + index * 16),
            "--episodes",
            "16",
            "--steps",
            "4",
            "--window",
            "2",
            "--model-seed",
            "44",
            "--learning-rate",
            "0.003",
            "--gamma",
            "0.9",
            "--calibration",
            str(tmp_path / "c0"),
            str(tmp_path / "c1"),
        ]
        if previous:
            args += ["--resume", str(previous)]
        assert cli.main(args) == 0
        previous = output / "checkpoint.ptz"
        _, manifest = loadCheckpoint(previous)
        assert manifest.transitions == (index + 1) * 64
        assert manifest.updates == (index + 1) * 4
        assert manifest.training_seeds == list(range(1600, 1600 + (index + 1) * 16))
    # Walk both actual unit-generated blocks successfully, then refuse missing validation.
    # These fixture bundles remain in pytest temp storage, never qualify or feed a campaign.
    with pytest.raises(ValueError, match="report requires"):
        expanded.qualify(previous, output / "summary.json", [], planPath, [])


def test_supervisor_fixed_argmax_reaches512_before_quality_stop(tmp_path, monkeypatch):
    import time

    frozen = {"campaign_id": "a" * 32, "image_id": "sha256:" + "b" * 64}
    runner = extended_supervisor.ExtendedSupervisor(tmp_path, frozen)
    calls = []
    monkeypatch.setattr(runner, "checkSources", lambda: None)
    monkeypatch.setattr(runner, "exclusiveLab", lambda: None)
    monkeypatch.setattr(runner, "command", lambda *a, **k: frozen["image_id"])
    monkeypatch.setattr(runner, "heartbeat", lambda: None)
    monkeypatch.setattr(runner, "offline", lambda *a: None)

    def measured(stage, *args, **kwargs):
        calls.append((stage, args, kwargs))
        if stage == "train-01":
            (tmp_path / stage).mkdir()
            (tmp_path / stage / "evidence.jsonl").write_bytes(b' {"kind":"ppo_update"}\n' * 4)
        return tmp_path / stage / "summary.json"

    monkeypatch.setattr(runner, "measured", measured)
    monkeypatch.setattr(extended_supervisor, "actionEffectChecks", lambda *a: ([], {}))
    monkeypatch.setattr(
        extended_supervisor, "report", lambda *a: {"comparable_held_out_schedules": True}
    )

    def qualified(checkpoint, *args):
        count = int(checkpoint.parent.name.split("-")[1]) * 64
        return {
            "transitions": count,
            "qualified": False,
            "validation_mean_reward": -1,
            "directional_dependence": {
                key: {"mean_desired_probability": 0.4, "desired_route_fraction": 0}
                for key in ("path0", "path1")
            },
        }

    monkeypatch.setattr(extended_supervisor, "qualify", qualified)
    runner.workDeadline = time.monotonic() + 7080
    assert runner.campaign() == "no_quality_or_probability_learning_after_minimum512"
    assert len([c for c in calls if c[0].startswith("train-")]) == 8
    assert len([c for c in calls if c[0].startswith("validation-")]) == 4
    assert not any(c[0].startswith("test-") for c in calls)
    assert runner.status["train_transitions"] == 512
    assert calls[-2][2]["checkpoint"] == tmp_path / "train-07" / "checkpoint.ptz"
