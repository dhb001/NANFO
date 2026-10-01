"""ADR016 offline verification; no synthetic sample enters the live campaign."""

import importlib.util
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from private_store import requirePrivateStore

requirePrivateStore(__file__)
pytestmark = pytest.mark.private_artifacts

DIRECTORY = Path(__file__).resolve().parents[1] / "scripts/refinement_long"


def loadModules():
    modules, saved = {}, {}
    try:
        for name in (
            "history",
            "protocol",
            "contract",
            "checkpoint",
            "preflight",
            "runner",
            "launch",
        ):
            saved[name] = sys.modules.get(name)
            spec = importlib.util.spec_from_file_location(
                "_test_adr016_" + name, DIRECTORY / (name + ".py")
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            modules[name] = mod
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return modules


M = loadModules()
H, P, C, K, F, R, L = [
    M[n] for n in ("history", "protocol", "contract", "checkpoint", "preflight", "runner", "launch")
]


@pytest.fixture
def plan():
    _, metadata = H.parent()
    return {
        **C.declaration(),
        "started_unix": time.time() - 20,
        "campaign_id": "b" * 32,
        "plan_sha256": "a" * 64,
        "parent_manifest_sha256": "c" * 64,
        "sources": {},
        "release": H.read(H.ROOT / "artifacts/adr015-release.json"),
        "parent_metadata": metadata,
    }


def testParentExactTensorTransferNewOptimizerAndNamespaces():
    reference, _ = H.parent()
    agent, _ = K.warmstart()
    assert H.digest(H.PREVIOUS / "candidate-512.ptz") == H.PARENT_HASH
    assert K.modelHash(agent) == K.modelHash(reference)
    assert not agent.optimizer.state and agent.transitions == agent.updates == 0
    assert agent.config.rollout == agent.config.minibatch == 32
    assert agent.config.learning_rate == 0.0005 and agent.config.gamma == 0.9
    assert H.c.SPLITS["train"] == [1000, 1999]
    P.validateSchedule("train", P.schedule(10000, 32))
    with pytest.raises(ValueError):
        H.c.validateSeed("train", 10000)


@pytest.mark.parametrize("split,first", [("train", 10000), ("validation", 20000), ("test", 30000)])
def testStrictNewNamespace(split, first):
    rows = P.schedule(first, 8)
    P.validateSchedule(split, rows)
    for broken in (
        P.schedule(first - 1, 8),
        rows[::-1],
        rows[:7],
        [{**rows[0], "seed": True}, *rows[1:]],
    ):
        with pytest.raises(ValueError):
            P.validateSchedule(split, broken)
    assert P.Request(command="reset", seed=first, scenario="balanced").seed == first


def testBalancedUpdatesActuallyMoveWeightsAndRoundtrip(plan, tmp_path):
    agent, _ = K.warmstart()
    before = K.modelHash(agent)
    rollout = []
    for index in range(32):
        state = np.full(16, index / 32, dtype=np.float32)
        action, logp, value, _ = agent.model.decide(state)
        rollout.append(
            {
                "state": state.tolist(),
                "action": action,
                "log_prob": logp,
                "value": value,
                "next_value": value,
                "reward": float(index % 3),
                "terminated": False,
                "truncated": index % 4 == 3,
                "valid_transition": True,
            }
        )
    metrics = agent.update(rollout)
    assert metrics["preclip_grad_norm"] > 0 and before != K.modelHash(agent)
    path = tmp_path / "candidate.ptz"
    sha = K.save(path, agent, plan, list(range(10000, 10008)), ["d" * 64])
    loaded, metadata = K.load(path, sha, plan)
    assert K.modelHash(agent) == K.modelHash(loaded)
    assert metadata["transitions"] == 32 and metadata["updates"] == 1
    state = np.ones(16, dtype=np.float32)
    assert agent.model.decide(state, deterministic=True) == loaded.model.decide(
        state, deterministic=True
    )
    with pytest.raises(ValueError, match="immutable"):
        K.save(path, agent, plan, [], [])
    with pytest.raises(ValueError, match="hash"):
        K.load(path, "0" * 64, plan)


def testCounterbalanceAndFullBudgetFit():
    p = C.declaration()
    assert len(p["training"]) == 512 and len(p["validation"]) == 64 and len(p["test"]) == 128
    for sessions in [*p["validation_sessions"].values(), p["test_sessions"]]:
        for method in C.METHODS:
            rows = [r for s in sessions if s["policy"] == method for r in s["rows"]]
            assert len(set(r["seed"] for r in rows)) == len(rows)
        firstSeven = [sessions[i * 7 : (i + 1) * 7] for i in range(7)]
        for position in range(7):
            assert {block[position]["policy"] for block in firstSeven} == set(C.METHODS)
    assert C.budget(86400, 512 + 896, 16 + 112, 25)["admitted"]
    assert C.budget(86400, 512 + 896, 16 + 112, 25)["final_reserve_seconds"] >= 28800
    assert not C.budget(30000, 512 + 896, 16 + 112, 25)["admitted"]
    with pytest.raises(ValueError):
        C.budget(float("nan"), 0, 0, 25)


def episodes(reward, changes=0.25, delivery=1.0):
    return [
        {
            **row,
            "reward": reward,
            "changes": changes,
            "delivery": delivery,
            "rtt": 25.0,
            "outages": 0,
        }
        for row in P.schedule(20000, 64)
    ]


def testBothReferenceGatesAndLockedFinalEndpoint():
    incumbent, parent = episodes(1.0), episodes(1.04)
    assert not C.qualify(episodes(1.03), incumbent, parent)["qualified"]
    assert C.qualify(episodes(1.05), incumbent, parent)["qualified"]
    assert not C.qualify(episodes(1.05, delivery=0.96), incumbent, parent)["qualified"]
    result = C.qualify(episodes(1.05), incumbent, parent)
    assert C.qualify(episodes(1.05), incumbent, parent, final=True, endpoints=result["endpoints"])[
        "qualified"
    ]
    assert not C.qualify(
        episodes(1.04), incumbent, parent, final=True, endpoints=result["endpoints"]
    )["qualified"]


def testPoststopElapsedCountersAndNoFalseFailure(tmp_path, plan, monkeypatch):
    runner = R.LongCampaign(tmp_path, plan)
    runner.status.update(
        state="stopped",
        stage="finished",
        finished_unix=plan["started_unix"] + 12,
        completed_rounds=3,
        completed_sessions=5,
        train_updates=12,
        train_transitions=384,
        stop_reason="operator_stop",
    )
    runner.heartbeat()
    previous = H.read(tmp_path / "status.json")
    runner.heartbeat()
    current = H.read(tmp_path / "status.json")
    assert current["elapsed_seconds"] == previous["elapsed_seconds"] == 12
    assert current["completed_rounds"] == 3 and current["train_transitions"] == 384
    assert current["state"] == "stopped" and current["stop_reason"] == "operator_stop"


def testAdmissionOrderNoReplayAndNoUnqualifiedTest(tmp_path, plan):
    runner = R.LongCampaign(tmp_path, plan)
    session = {
        "stage": "train-0128",
        "split": "train",
        "policy": "candidate",
        "rows": plan["training"][:32],
    }
    runner.admit(session, None)
    runner.ledger["attempts"].append(session)
    with pytest.raises(ValueError, match="retry"):
        runner.admit(session, None)
    H.write(tmp_path / "selection.json", {"qualified": False})
    with pytest.raises(ValueError, match="qualified"):
        runner.admit(plan["test_sessions"][0], None)
    runner.status["train_transitions"] = 1024
    with pytest.raises(ValueError, match="order"):
        runner.admit(plan["validation_sessions"]["1024"][1], None)


def testServiceCapsAndHistoricalSeedAudit():
    cmd = L.command()
    for value in (
        "--property=RuntimeMaxSec=86400",
        "--property=TimeoutStopSec=180",
        "--property=Restart=no",
        "--property=CPUQuota=200%",
        "--property=MemoryMax=2G",
    ):
        assert value in cmd
    assert any("ExecStopPost=" in value and value.endswith("runner.py cleanup") for value in cmd)
    assert F.seedsIn({"attempts": [{"identity": {"seed": 10000, "episodes": 3}}]}) == {
        10000,
        10001,
        10002,
    }
    assert F.seedsIn({"request": {"seed": 30000}, "data": {"seed": 30001}}) == {30000, 30001}


def testFailureStopsAndCleansWithoutReplay(tmp_path, plan, monkeypatch):
    runner = R.LongCampaign(tmp_path, plan)
    calls = []

    def fail():
        raise ValueError("live measurement failed")

    monkeypatch.setattr(runner, "campaign", fail)
    monkeypatch.setattr(runner, "cleanup", lambda: calls.append("cleanup"))
    monkeypatch.setattr(runner, "preserve", lambda: {"unchanged": True})
    assert runner.run() == 1
    assert calls == ["cleanup"]
    assert H.read(tmp_path / "status.json")["state"] == "failed"
    assert H.read(tmp_path / "outcome.json")["test_attempts"] == 0


def testWhole128CollectionSerializesBalancedRealUpdates(tmp_path, plan, monkeypatch):
    from types import SimpleNamespace

    runner = R.LongCampaign(tmp_path, plan)
    agent, _ = K.warmstart()
    cleanupCalls = []
    for name in ("check", "checkSources", "diskUsage"):
        monkeypatch.setattr(runner, name, lambda: None)
    monkeypatch.setattr(runner, "startLab", lambda *args: "unit-only")
    monkeypatch.setattr(runner, "cleanup", lambda: cleanupCalls.append(True))
    expectedEpisodes = []

    class Wire:
        previous = 0
        values = []

        def exchange(self, request):
            if request.command == "close":
                return {
                    "version": 1,
                    "ok": True,
                    "error": None,
                    "data": {
                        "closed": True,
                        "cleanup_verified": True,
                        "episode_id": request.episode_id,
                    },
                }
            if request.command == "reset":
                self.previous = 0
                self.values = []
            before = self.previous
            self.previous = request.action if request.action is not None else 0
            observation = H.c.Observation(
                path_capacity_mbps=[20.0, 20.0],
                path_utilization=[0.3, 0.1],
                path_queue_packets=[0.0, 0.0],
                latency_ms=25.0,
                loss_fraction=0.0,
                goodput_mbps=4.0,
                offered_mbps=4.0,
                actual_offered_mbps=4.0,
                background_mbps=1.0,
                previous_action=self.previous,
                seconds_since_change=2.0,
            )
            if request.command == "step":
                reward = H.env.rewardComponents(observation, before)
                self.values.append(
                    {
                        "reward": reward["total"],
                        "delivery": 1.0,
                        "rtt": 25.0,
                        "changes": float(before != self.previous),
                        "outages": 0,
                    }
                )
                if request.step_index == 4:
                    import statistics

                    expectedEpisodes.append(
                        {
                            "seed": request.seed,
                            "scenario": request.scenario,
                            **{
                                k: statistics.mean(v[k] for v in self.values)
                                for k in self.values[0]
                            },
                        }
                    )
            return {
                "observation": observation.model_dump(),
                "before": before,
                "seed": request.seed,
                "scenario": request.scenario,
            }

    wire = Wire()
    monkeypatch.setattr(R, "Transport", lambda *args, **kwargs: wire)

    def validated(raw, *args):
        return SimpleNamespace(
            observation=H.c.Observation.model_validate(raw["observation"]),
            seed=raw["seed"],
            scenario=raw["scenario"],
            episode_id="00000000-0000-4000-8000-000000000001",
            evidence={
                "latency_timeout_ms": None,
                "service_outage": False,
                "routing_health_start": {"paths": {"h1->h3": {"action": raw["before"]}}},
            },
        )

    monkeypatch.setattr(R, "validate", validated)
    monkeypatch.setattr(
        H.OLD["audit"],
        "reconstruct",
        lambda path, *args: {
            "episodes": expectedEpisodes,
            "evidence_sha256": H.digest(path),
            "raw_audit": True,
        },
    )
    session = {
        "stage": "train-0128",
        "split": "train",
        "policy": "candidate",
        "rows": plan["training"][:32],
    }
    result = runner.measured(session, agent)
    assert agent.transitions == 128 and agent.updates == 4
    assert result["valid_transitions"] == 128 and cleanupCalls == [True]
    assert runner.status["completed_sessions"] == 1
    with (tmp_path / "train-0128/evidence.jsonl").open("rb") as source:
        records = [H.c.parseJson(line) for line in source]
    updates = [r for r in records if r["kind"] == "ppo_update"]
    assert len(updates) == 4
    for update in updates:
        assert update["model_before"] != update["model_after"]
        assert update["profiles"] == [p for p in P.PROFILES for _ in range(4)]
        assert len(update["rollout"]) == 32
