"""Offline safety/learning regressions. None of these fixtures qualifies a real policy."""

import hashlib
import json
from copy import deepcopy

import numpy as np
import pytest
import torch

from nanfo_routing import cli, qualification
from nanfo_routing.artifacts import loadCheckpoint, saveCheckpoint
from nanfo_routing.contracts import CONTRACT, STATE_DIM, Observation, Request, Response, jsonBytes
from nanfo_routing.env import RoutingEnv, encode
from nanfo_routing.evidence import validateMeasurement, validateSpec
from nanfo_routing.ppo import PPO, PPOConfig


def test_actor_small_balanced_separate_and_pressure_preserving(observation):
    assert STATE_DIM == 16 and CONTRACT["version"] == 3
    for seed in (41, 42, 43):
        agent = PPO(PPOConfig(seed=seed))
        assert agent.config.hidden == 32
        state = encode([Observation.model_validate(observation)])
        assert 0.48 < agent.model.decide(state)[3][0] < 0.52
        assert not (
            {id(p) for p in agent.model.actorBody.parameters()}
            & {id(p) for p in agent.model.criticBody.parameters()}
        )
    assert state[0] > state[1] and state[11] < state[12]
    changed = deepcopy(observation)
    changed["path_utilization"] = [8.0, 2.0]
    encoded = encode([Observation.model_validate(changed)])
    assert np.expm1(encoded[0]) / np.expm1(encoded[1]) == pytest.approx(4.0)


def test_stationary_categorical_policy_can_learn_with_fresh_on_policy_updates(observation):
    # Synthetic rewards are exclusively a unit learnability check, never stored as lab evidence.
    agent = PPO(PPOConfig(seed=41, learning_rate=0.003, gamma=0.0, rollout=32))
    states = []
    for capacity in ([2.0, 20.0], [20.0, 2.0]):
        states.append(
            encode([Observation.model_validate({**observation, "path_capacity_mbps": capacity})])
        )
    for _ in range(35):
        rows = []
        for index in range(32):
            target = 1 - index % 2
            state = states[index % 2]
            action, logprob, value, _ = agent.model.decide(state)
            rows.append(
                {
                    "state": state,
                    "action": action,
                    "log_prob": logprob,
                    "value": value,
                    "next_value": 0.0,
                    "reward": float(action == target),
                    "terminated": True,
                    "truncated": False,
                    "valid_transition": True,
                }
            )
        agent.update(rows)
    assert [agent.model.decide(state, deterministic=True)[0] for state in states] == [1, 0]
    assert all(torch.isfinite(parameter).all() for parameter in agent.model.parameters())


def test_v2_spec_and_checkpoint_rejected(tmp_path, transport):
    import zipfile

    request = Request(command="reset", seed=1000, scenario="path0")
    spec = transport.exchange(request)["data"]["evidence"]["environment_spec"]
    spec["version"] = 2
    with pytest.raises(ValueError, match="semantics"):
        validateSpec(spec, hashlib.sha256(jsonBytes(spec)).hexdigest())
    path = tmp_path / "old.ptz"
    saveCheckpoint(
        path,
        PPO(),
        provenance="offline-fixture-not-trained-model",
        trainingSeeds=[],
        episodes=0,
        evidenceHash="0" * 64,
    )
    with zipfile.ZipFile(path) as source:
        manifest = json.loads(source.read("manifest.json"))
        weights = source.read("weights.pt")
    manifest["version"] = 2
    with zipfile.ZipFile(path, "w") as output:
        output.writestr("manifest.json", jsonBytes(manifest))
        output.writestr("weights.pt", weights)
    with pytest.raises(ValueError, match="v3 requires fresh"):
        loadCheckpoint(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e["capacity_readback"][0]["classes"][0]["options"].update(rate=1),
        lambda e: e["capacity_readback_end"].pop(),
        lambda e: e["route"]["readback"]["owned"]["access1:19110"]["rules"][0].update(src="all"),
        lambda e: e["route"]["readback"]["paths"]["h3->h1"].update(nodes=["h3", "dist2", "h1"]),
        lambda e: e["phase_relationship"].update(workload_advanced_before_action=True),
    ],
)
def test_matched_capacity_and_foreground_only_evidence_fail_closed(transport, mutation):
    request = Request(command="reset", seed=1000, scenario="path0")
    raw = transport.exchange(request)
    mutation(raw["data"]["evidence"])
    with pytest.raises(ValueError):
        validateMeasurement(Response.model_validate(raw).data, request)


def test_stationary_demand_cannot_advance(transport):
    env = RoutingEnv(transport)
    env.reset(seed=1000)

    def mutate(raw):
        raw["data"]["observation"]["offered_mbps"] = 6.1
        raw["data"]["evidence"]["phase"]["offered_mbps"] = 6.1

    transport.mutate = mutate
    assert not env.step(1)[4]["valid_transition"]


def test_plan_budget_approval_duplicate_and_test_freeze(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    assert cli.main(["plan", "--output", str(plan)]) == 0
    args = cli.parser().parse_args(
        [
            "train",
            "--operator-experiment",
            "--plan",
            str(plan),
            "--output",
            str(tmp_path / "run"),
            "--model-seed",
            "41",
            "--seed",
            "1500",
            "--episodes",
            "8",
            "--window",
            "2",
        ]
    )
    with pytest.raises(ValueError, match="approval"):
        with qualification.collectionAdmission(args):
            pytest.fail("not approved")
    args.parent_approved = args.lab_released = True
    args.calibration = [tmp_path / "c0.json", tmp_path / "c1.json"]
    monkeypatch.setattr(qualification, "actionEffectChecks", lambda *args: ([], {}))
    with qualification.collectionAdmission(args):
        pass
    with pytest.raises(ValueError, match="already consumed"):
        with qualification.collectionAdmission(args):
            pytest.fail("duplicate admission")
    monkeypatch.setattr(qualification.time, "time", lambda: 1e12)
    with pytest.raises(ValueError, match="budget exhausted"):
        with qualification.collectionAdmission(args):
            pytest.fail("deadline admission")
    assert qualification.frozenPlan()["collection_budget_seconds"] == 1200
    assert qualification.frozenPlan()["validation_margin_strictly_greater_than"] == 0.02


def test_paired_statistics_use_seed_means_not_windows():
    def session(offset):
        return {
            "seeds": [2600, 2601],
            "reconstructed_steps": [
                {
                    "seed": seed,
                    "reward": {"total": value + offset},
                    "goodput_mbps": value,
                    "loss_fraction": 0.1,
                    "observed_latency_ms": None,
                }
                for seed, value in ((2600, 1.0), (2600, 3.0), (2601, 5.0), (2601, 7.0))
            ],
        }

    result = qualification.pairedComparison(session(0.03), session(0))
    assert result["reward"]["paired_seed_count"] == 2
    assert result["reward"]["mean_delta"] == pytest.approx(0.03)
    assert result["reward"]["ci95"] == pytest.approx([0.03, 0.03])
    assert result["icmp_rtt_ms"]["ci95"] is None


def test_select_rejects_oldbest_self_attestation(tmp_path):
    path = tmp_path / "best.json"
    path.write_bytes(jsonBytes({"qualified": True, "best": 999.0}))
    with pytest.raises((ValueError, KeyError)):
        qualification.selectPolicy([path])


def test_qualification_requires_parsed_training_calibration_not_boolean(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    plan.write_bytes(jsonBytes(qualification.frozenPlan()))
    monkeypatch.setattr(
        cli, "report", lambda *a, **k: {"sessions": [], "matched_offered_schedules": True}
    )
    with pytest.raises(ValueError, match="train-only action-effect"):
        qualification.qualify(tmp_path / "checkpoint.ptz", tmp_path / "train.json", [], plan, [])


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("none", True),
        ("ties_constant1", False),
        ("wrong_direction", False),
        ("checkpoint", "checkpoint"),
        ("training_digest", "training evidence"),
        ("test", "never test"),
        ("fixture", "fixtures"),
        ("generalization", "generalized"),
        ("missing_constant", "BOTH constants"),
        ("unmatched", "not matched"),
    ],
)
def test_qualification_gate_matrix_injected_only(
    tmp_path, monkeypatch, observation, mutation, expected
):
    from types import SimpleNamespace

    from nanfo_routing.artifacts import trainingDistribution

    plan = qualification.frozenPlan()
    planPath = tmp_path / "plan.json"
    planPath.write_bytes(jsonBytes(plan))
    planHash = hashlib.sha256(jsonBytes(plan)).hexdigest()
    identity = {"checkpoint_sha256": "a" * 64}
    from conftest import producerSpec

    spec = producerSpec()
    provenance = {"source_sha256": "c" * 64, "lab_image_id": "sha256:" + "d" * 64}
    manifest = SimpleNamespace(
        training_distribution=trainingDistribution(2.0, 4),
        config=PPOConfig(seed=41),
        training_seeds=list(range(1500, 1508)),
        transitions=32,
        updates=2,
        evidence_sha256="e" * 64,
        lab_provenance=provenance,
        environment_spec=spec,
    )

    def decide(state, **kwargs):
        action = int(state[12] > state[11]) if mutation != "wrong_direction" else 0
        return action, 0.0, 0.0, [0.5, 0.5]

    agent = SimpleNamespace(model=SimpleNamespace(decide=decide))
    monkeypatch.setattr(
        qualification, "loadCheckpointIdentity", lambda path: (agent, manifest, identity)
    )
    base = {
        "kind": "evaluation",
        "status": "completed",
        "generalization": False,
        "lab_provenance": provenance,
        "environment_spec": spec,
        "evidence_sha256": "f" * 64,
        "checkpoint": None,
        "seeds": plan["validation_seeds"],
        "split": "validation",
        "mode": "matched",
        "derived_metrics": {"mean_reward": 1.0},
    }
    train = {
        **base,
        "kind": "train",
        "policy": "ppo",
        "split": "train",
        "seeds": manifest.training_seeds,
        "evidence_sha256": manifest.evidence_sha256,
        "checkpoint": identity,
    }
    sessions = []
    for policy in ("ppo", "constant0", "constant1", "heuristic", "ospf"):
        steps = []
        for index, seed in enumerate(plan["validation_seeds"]):
            for _ in range(4):
                steps.append(
                    {
                        "seed": seed,
                        "scenario": f"path{index % 2}",
                        "input": {
                            **observation,
                            "path_capacity_mbps": [2.0, 20.0] if index % 2 == 0 else [20.0, 2.0],
                        },
                        "reward": {"total": 1.0 if policy == "ppo" else 0.9},
                        "goodput_mbps": 6.0,
                        "loss_fraction": 0.0,
                        "observed_latency_ms": 25.0,
                    }
                )
        sessions.append(
            {
                **deepcopy(base),
                "policy": policy,
                "reconstructed_steps": steps,
                "checkpoint": identity if policy == "ppo" else None,
            }
        )
    if mutation == "ties_constant1":
        for row in sessions[2]["reconstructed_steps"]:
            row["reward"]["total"] = 1.0
    if mutation == "checkpoint":
        sessions[0]["checkpoint"] = {"checkpoint_sha256": "0" * 64}
    if mutation == "training_digest":
        train["evidence_sha256"] = "0" * 64
    if mutation == "test":
        sessions[0]["split"] = "test"
    if mutation == "fixture":
        spec["source_files"] = {"offline-fixture": "b" * 64}
        for row in sessions:
            row["environment_spec"] = spec
    if mutation == "generalization":
        sessions[0]["generalization"] = True
    if mutation == "missing_constant":
        sessions.pop(2)
    paths = [tmp_path / name / "summary.json" for name in ("train", "v0", "v1", "v2", "v3", "v4")]
    for path in paths:
        path.parent.mkdir()
        (path.parent / "evidence.jsonl").write_bytes(
            jsonBytes({"kind": "session", "summary": {"plan_sha256": planHash}}) + b"\n"
        )
    monkeypatch.setattr(
        qualification, "actionEffectChecks", lambda *a: ([], {"path0": 0.1, "path1": 0.1})
    )
    monkeypatch.setattr(
        cli,
        "report",
        lambda p, **kwargs: {
            "sessions": [train] if p == [paths[0]] else sessions,
            "comparable_held_out_schedules": mutation != "unmatched",
        },
    )
    if isinstance(expected, str):
        with pytest.raises(ValueError, match=expected):
            qualification.qualify(
                tmp_path / "fake.ptz", paths[0], paths[1 : len(sessions) + 1], planPath, []
            )
    else:
        result = qualification.qualify(tmp_path / "fake.ptz", paths[0], paths[1:], planPath, [])
        assert result["qualified"] is expected
        assert result["autonomous_dispatch"] == "blocked"
