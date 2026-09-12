"""ADR015 offline-only regressions. No fixture is admitted into live training."""

import copy
import hashlib
import runpy
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/refinement"))

from evidence import Request, Transport, phase, validate  # noqa: E402
from frozen import PARENT_HASH, ROOT, digest, incumbent, module  # noqa: E402
from launch import argv  # noqa: E402
from model import load, save, warmstart  # noqa: E402
from plan import PROFILES, admission, compare, declaration, interval, schedule  # noqa: E402


@pytest.fixture
def v5(monkeypatch, observation):
    import conftest

    _, metadata, _ = incumbent()
    # Unit fixture generation uses the historical fixture's actual V4 schema,
    # then constructs a clearly synthetic V5 specimen. Never a live adapter rewrite.
    monkeypatch.setattr(conftest, "producerSpec", lambda: metadata.environment_spec)
    profiles = runpy.run_path(str(ROOT.parent / "emulation/workloads.py"))["MATCHED_PROFILES"]
    spec = {
        **metadata.environment_spec,
        "version": 5,
        "profiles": profiles,
        "scenarios": list(profiles),
        "schedule_version": "seeded-stationary-profiles-v5",
    }
    request = Request(
        command="reset", seed=1800, scenario="balanced", window_seconds=2.0, episode_steps=4
    )
    expected = phase(1800, "balanced", 0, spec)
    observation.update(
        {k: expected[k] for k in ("offered_mbps", "background_mbps", "path_capacity_mbps")}
    )
    observation["actual_offered_mbps"] = expected["offered_mbps"]
    e = conftest.evidenceFixture(observation, request)
    spec["source_files"] = e["environment_spec"]["source_files"]
    spec["source_sha256"] = e["environment_spec"]["source_sha256"]
    e["environment_spec"] = spec
    e["spec_hash"] = hashlib.sha256(module("contracts").jsonBytes(spec)).hexdigest()
    e["provenance"]["lab_image_id"] = "sha256:" + "1" * 64
    peers = {
        "core": [("dist1", 1), ("dist2", 2)],
        "dist1": [("core", 1), ("dist2", 2), ("access1", 3), ("access2", 4)],
        "dist2": [("core", 1), ("dist1", 2), ("access1", 3), ("access2", 4)],
        "access1": [("dist1", 1), ("dist2", 2)],
        "access2": [("dist1", 1), ("dist2", 2)],
    }
    ids = {n: f"10.255.0.{i}" for i, n in enumerate(peers, 1)}
    neighbors = {
        n: {
            "neighbors": {
                ids[p]: [{"state": "Full/-", "ifaceName": f"{n}-eth{port}"}] for p, port in rows
            }
        }
        for n, rows in peers.items()
    }
    for key, begin, end in (
        ("routing_health_start", 98.0, 99.0),
        ("routing_health_end", 103.1, 103.2),
    ):
        e[key] = {
            "start": begin,
            "end": end,
            "neighbors": copy.deepcopy(neighbors),
            "paths": copy.deepcopy(e["route"]["readback"]["paths"]),
        }
    raw = {
        "version": 1,
        "ok": True,
        "error": None,
        "data": {
            "episode_id": "00000000-0000-4000-8000-000000000001",
            "step_index": 0,
            "mode": "matched",
            "seed": 1800,
            "scenario": "balanced",
            "terminated": False,
            "truncated": False,
            "observation": observation,
            "evidence": e,
        },
    }
    release = {
        "environment_spec": spec,
        "spec_hash": e["spec_hash"],
        "image_id": e["provenance"]["lab_image_id"],
    }
    return raw, request, release, expected


def testExactWarmstartAndNoOldOptimizer():
    parent, _, path = incumbent()
    agent, _ = warmstart()
    assert digest(path) == PARENT_HASH
    assert all(
        torch.equal(v, agent.model.state_dict()[k]) for k, v in parent.model.state_dict().items()
    )
    assert not agent.optimizer.state and agent.transitions == agent.updates == 0
    assert agent.config.learning_rate == 0.0005 and agent.config.gamma == 0.9


def testRealPpoWeightsUpdateAndInferenceRoundtrip(tmp_path, v5):
    agent, metadata = warmstart()
    before = {k: v.clone() for k, v in agent.model.state_dict().items()}
    rollout = []
    for i in range(16):
        state = np.full(16, i / 16, dtype=np.float32)
        action, logp, value, _ = agent.model.decide(state)
        rollout.append(
            {
                "state": state,
                "action": action,
                "log_prob": logp,
                "value": value,
                "next_value": value,
                "reward": float(i % 2),
                "terminated": False,
                "truncated": i % 4 == 3,
                "valid_transition": True,
            }
        )
    metrics = agent.update(rollout)
    assert all(np.isfinite(v) for v in metrics.values() if v is not None)
    assert any(
        not torch.equal(before[k], v) for k, v in agent.model.state_dict().items() if "actor" in k
    )
    plan = {
        **declaration(),
        "release": v5[2],
        "refinement_sources": {},
        "parent_source_sha256": metadata.client_source_files,
        "parent_environment_spec": metadata.environment_spec,
        "plan_sha256": "2" * 64,
    }
    path = tmp_path / "candidate.ptz"
    sha = save(path, agent, plan, [1808, 1809, 1810, 1811], ["3" * 64])
    loaded, _ = load(path, sha, plan)
    state = np.arange(16, dtype=np.float32) / 16
    assert loaded.model.decide(state, deterministic=True) == agent.model.decide(
        state, deterministic=True
    )
    with pytest.raises(ValueError, match="immutable"):
        save(path, agent, plan, [], [])
    with pytest.raises(ValueError, match="hash"):
        load(path, "0" * 64, plan)


def testV5RawEvidenceAcceptedWithoutMutation(v5):
    original = copy.deepcopy(v5)
    assert validate(*v5).scenario == "balanced"
    assert v5 == original


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["data"].update(seed=1801),
        lambda r: r["data"]["evidence"]["phase"].update(offered_mbps=5.0),
        lambda r: r["data"]["evidence"]["udp_sent"][0].update(started_monotonic_seconds=102.0),
        lambda r: r["data"]["evidence"].update(drain_status="timeout"),
        lambda r: r["data"]["evidence"].update(late_received_packets=[0, 0]),
        lambda r: r["data"]["evidence"]["routing_health_end"].update(end=999.0),
        lambda r: r["data"]["evidence"]["routing_health_start"]["neighbors"]["core"].update(
            neighbors={}
        ),
        lambda r: r["data"]["evidence"]["route_end"].update(changed=True),
        lambda r: r["data"]["observation"].update(previous_action=True),
        lambda r: r["data"]["observation"].update(goodput_mbps=999.0),
    ],
)
def testV5RejectsForgedOrIncompleteRawEvidence(v5, mutation):
    mutation(v5[0])
    with pytest.raises(ValueError):
        validate(*v5)


def testSeedReplayAllProfilesAndMirrors(v5):
    producer = runpy.run_path(str(ROOT.parent / "emulation/workloads.py"))["schedule"]
    for seed in (1800, 1999, 2800, 3610):
        for profile in PROFILES:
            expected = producer(seed, profile, 4, "matched")
            assert [
                phase(seed, profile, i, v5[2]["environment_spec"]) for i in range(5)
            ] == expected


def episodes(reward=1.0, changes=0.25, delivery=1.0, rtt=25.0):
    return [
        {
            **row,
            "reward": reward,
            "changes": changes,
            "delivery": delivery,
            "rtt": rtt,
            "outages": 0,
        }
        for row in schedule(2800, 16)
    ]


def testQualityAndFinalGates():
    base = episodes()
    assert not compare(episodes(), base)["passed"]
    assert compare(episodes(reward=1.03), base)["passed"]
    assert compare(episodes(changes=0.1875), base)["passed"]
    assert not compare(episodes(reward=1.1, delivery=0.969), base)["passed"]
    assert not compare(episodes(reward=1.1, rtt=29.6), base)["passed"]
    assert not compare(episodes(changes=0), episodes(changes=0))["passed"]
    assert compare(episodes(reward=1.03), base, final=True, endpoint="reward")["passed"]
    assert not compare(episodes(reward=1.0, changes=0), base, final=True, endpoint="reward")[
        "passed"
    ]
    candidate = episodes(reward=1.1)
    candidate[6]["delivery"] = 0.5
    assert not compare(candidate, base)["passed"]
    with pytest.raises(ValueError, match="paired"):
        compare(candidate[::-1], base)


def testPlanBudgetTimerAndTransport():
    plan = declaration()
    assert plan["minimum_transitions"] == 256 and plan["maximum_transitions"] == 512
    assert len(plan["training"]) == 192 and len(plan["test"]) == 24
    assert admission(14400, 64 + 80 + 32, 144, 25, starts=14)
    assert not admission(3000, 48, 144, 25, starts=8)
    assert admission(6500, 0, 144, 25, starts=6)
    assert not admission(6500, 48, 144, 35, starts=8)
    args = argv("release.json")
    cap = next(x for x in args if x.startswith("--property=RuntimeMaxSec="))
    assert 0 < int(cap.split("=")[-1]) <= 14400
    assert "--property=Restart=no" in args
    assert any("ExecStopPost=" in x and x.endswith(" cleanup") for x in args)
    assert Transport.exchange.__globals__["Request"] is Request
    with pytest.raises(ValueError):
        Transport("foreign")
    assert interval([0.1, 0.1])["ci95"] == [0.1, 0.1]


@pytest.mark.parametrize("quality", [True, False])
def testCampaignMinimumSelectionAndOneFinalPass(tmp_path, monkeypatch, v5, quality):
    import campaign

    _, metadata, _ = incumbent()
    frozen = {
        **declaration(),
        "campaign_id": "a" * 32,
        "started_unix": campaign.time.time(),
        "plan_sha256": "2" * 64,
        "release": v5[2],
        "refinement_sources": {},
        "parent_source_sha256": metadata.client_source_files,
        "parent_environment_spec": metadata.environment_spec,
    }
    runner = campaign.Campaign(tmp_path, frozen)
    for name in ("checkSources", "exclusiveLab", "heartbeat"):
        monkeypatch.setattr(runner, name, lambda: None)
    monkeypatch.setattr(runner, "preserve", lambda: {"unchanged": True})
    calls = []

    def measured(stage, split, rows, policy, agent=None, checkpoint=None):
        calls.append((stage, split, policy, checkpoint))
        if split == "train":
            agent.transitions += 128
            agent.updates += 8
        values = [
            {
                **r,
                "reward": 1.1 if quality and policy == "candidate" else 1.0,
                "changes": 0.25,
                "delivery": 1.0,
                "rtt": 25.0,
                "outages": 0,
            }
            for r in rows
        ]
        return {"episodes": values, "evidence_sha256": "3" * 64}

    monkeypatch.setattr(runner, "measured", measured)
    result = runner.campaign()
    assert runner.agent.transitions == 512
    candidates = campaign.read(tmp_path / "validation.json")["checkpoints"]
    assert [r["transitions"] for r in candidates] == [128, 256, 384, 512]
    assert candidates[0]["eligible"] is False
    tests = [call for call in calls if call[1] == "test"]
    outcome = campaign.read(tmp_path / "outcome.json")
    assert outcome["default"] == PARENT_HASH
    if quality:
        assert [call[2] for call in tests] == frozen["test_order"]
        assert len(tests) == 6
        assert outcome["selection"]["transitions"] == 256
        assert result == "final_pass_incumbent_not_overwritten"
    else:
        assert not tests
        assert not (tmp_path / "selection.json").exists()
        assert result == "no_validation_quality_incumbent_retained"


def testRecordedEvaluationRejectsActorSubstitution(tmp_path, v5):
    from audit import reconstruct

    raw, request, released, _ = v5
    agent, _ = warmstart()
    log = module("artifacts").EvidenceLog(tmp_path / "evidence.jsonl")
    rows = [{"seed": 1800, "scenario": "balanced"}]
    log.append({"kind": "session", "plan_sha256": "2" * 64, "schedule": rows})
    log.append(
        {"kind": "measurement", "request": request.model_dump(), "response": raw, "decision": None}
    )
    step = copy.deepcopy(raw)
    step["data"]["step_index"] = 1
    step["data"]["evidence"]["phase"]["phase_index"] = 1
    step["data"]["evidence"]["phase_relationship"].update(
        action_observation_phase_index=0, measurement_phase_index=1
    )
    step["data"]["evidence"].update(initial_window=False, decision_windows=1)
    req = Request(
        command="step",
        seed=1800,
        scenario="balanced",
        window_seconds=2.0,
        episode_steps=4,
        episode_id=raw["data"]["episode_id"],
        step_index=1,
        action=0,
    )
    validate(step, req, released, phase(1800, "balanced", 1, released["environment_spec"]))
    log.append(
        {
            "kind": "measurement",
            "request": req.model_dump(),
            "response": step,
            "decision": [0, 0.0, 0.0, [0.5, 0.5]],
        }
    )
    log.close()
    with pytest.raises(ValueError, match="checkpoint inference"):
        reconstruct(
            tmp_path / "evidence.jsonl",
            {"plan_sha256": "2" * 64, "release": released},
            rows,
            "candidate",
            agent,
        )
