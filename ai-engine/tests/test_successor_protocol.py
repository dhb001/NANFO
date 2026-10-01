"""ADR-028 successor protocol: argmax(capacity) passes ADR024 gates but never successor gates."""

import copy
import importlib
import math
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanfo_routing import successor as s

REPO = Path(__file__).resolve().parents[2]
DEMAND = 6.0
CAPACITY = {
    "low": [20, 20],
    "path0": [2, 20],
    "path1": [20, 2],
    "balanced": [20, 20],
    "moderate0": [6, 20],
    "moderate1": [20, 6],
    "severe0": [4, 16],
    "severe1": [16, 4],
    "overload": [7, 7],
}
SEEDS = [3000 + 25 * index for index in range(24)]
MODEL_SEEDS = [41, 42, 43, 44, 45]


def observation(profile, previous=0):
    return SimpleNamespace(path_capacity_mbps=CAPACITY[profile], previous_action=previous)


RULES = {
    "constant0": lambda profile: 0,
    "constant1": lambda profile: 1,
    "ospf": lambda profile: 0,  # nominal costs prefer dist1 regardless of impairment
    "heuristic": lambda profile: int(CAPACITY[profile][0] < DEMAND),
    "capacity-oracle": lambda profile: s.capacityOracle(observation(profile)),
    "capacity-aware-ospf": lambda profile: s.capacityAwareOspf(observation(profile)),
}


def metrics(profile, action, bonus=0.0, noise=None):
    capacity = CAPACITY[profile][action]
    congested = capacity < DEMAND
    jitter = (lambda: noise.gauss(0, 0.01)) if noise else (lambda: 0.0)
    return {
        "reward": min(capacity, DEMAND) / DEMAND - 0.2 * congested + bonus + jitter(),
        "goodput_mbps": min(capacity, DEMAND) + bonus + jitter(),
        "icmp_rtt_ms": 5.0 + 40.0 * congested - bonus + jitter(),
    }


def campaign(learned, *, bonus=0.0, noise=None, modelSeeds=MODEL_SEEDS, profiles=CAPACITY):
    rows = []

    def add(policy, modelSeed, rule, extra=0.0):
        for profile in profiles:
            for seed in SEEDS:
                values = metrics(profile, rule(profile), extra, noise)
                rows.append(
                    dict(policy=policy, model_seed=modelSeed, profile=profile, seed=seed, **values)
                )

    for policy, rule in RULES.items():
        add(policy, None, rule)
    for modelSeed in modelSeeds:
        add(s.LEARNED, modelSeed, learned, bonus)
        add(s.ABLATION, modelSeed, RULES["heuristic"])
    return rows


def argmaxCapacity(profile):
    return s.capacityOracle(observation(profile))


@pytest.mark.parametrize(
    "df,expected",
    [
        (1, 12.706204736),
        (2, 4.302652730),
        (4, 2.776445105),
        (11, 2.200985160),
        (30, 2.042272456),
        (1000, 1.962339081),
        (10**6, 1.959966),
    ],
)
def test_student_t_quantiles_follow_degrees_of_freedom(df, expected):
    assert s.studentTQuantile(0.975, df) == pytest.approx(expected, abs=2e-6)
    mean, interval = s.pairedInterval([1.0, 2.0, 3.0])
    assert mean == 2.0 and interval[0] == pytest.approx(2 - 4.302652730 / math.sqrt(3), abs=1e-6)
    with pytest.raises(ValueError):
        s.studentTQuantile(0.4, 3)


def test_capacity_baselines_are_the_declared_decision_rules():
    assert [s.capacityOracle(observation(p)) for p in ("path0", "path1", "moderate0")] == [1, 0, 1]
    assert s.capacityOracle(observation("low", previous=1)) == 1  # tie keeps the route
    assert [s.capacityAwareOspf(observation(p)) for p in ("path0", "path1", "low")] == [1, 0, 0]
    assert s.capacityAwareOspf(SimpleNamespace(path_capacity_mbps=[12, 13])) == 1  # 8 vs 7
    assert s.capacityAwareOspf(SimpleNamespace(path_capacity_mbps=[13.5, 14])) == 0  # 7 vs 7


def adr024Report():
    """The historical ADR024 report shape for a candidate that is argmax(capacity)."""
    seeds = [(profile, seed) for profile in ("path0", "path1") for seed in SEEDS[:6]]
    comparisons = []
    for baseline in ("constant0", "constant1", "ospf"):
        row = {"baseline": baseline, "metrics": {}}
        for metric in ("reward", "goodput_mbps", "icmp_rtt_ms"):
            deltas = [
                metrics(p, argmaxCapacity(p))[metric] - metrics(p, RULES[baseline](p))[metric]
                for p, _ in seeds
            ]
            mean, interval = s.pairedInterval(deltas)
            row["metrics"][metric] = dict(paired_seed_count=12, mean_delta=mean, ci95=interval)
        comparisons.append(row)
    steps = [dict(scenario=p, action=argmaxCapacity(p)) for p, _ in seeds for _ in range(4)]
    return dict(
        comparable_held_out_schedules=True,
        paired_seed_comparisons=comparisons,
        sessions=[dict(policy="ppo", reconstructed_steps=steps)],
    )


def test_argmax_capacity_passes_every_historical_adr024_gate():
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        adr024 = importlib.import_module("adr024_campaign")
    finally:
        sys.path.remove(str(REPO / "scripts"))
    result = adr024.assess(adr024Report())
    assert result["qualified"] and all(result["checks"].values())


def test_argmax_capacity_can_never_pass_the_successor_gates():
    result = s.evaluate(campaign(argmaxCapacity))
    assert result["failures"] == [] and not result["qualified"]
    for checks in result["model_seed_checks"].values():
        assert not checks["reward_vs_capacity-oracle"]
        assert not checks["holdout_reward_vs_capacity-oracle"]
        # It does beat the weak baselines; only the capacity baselines expose it.
        assert checks["reward_vs_constant0"] and checks["goodput_vs_ospf"] and checks["rtt_vs_ospf"]


def test_argmax_capacity_with_independent_session_noise_never_qualifies():
    noise = random.Random(20260924)
    for _ in range(40):
        assert not s.evaluate(campaign(argmaxCapacity, noise=noise))["qualified"]


def test_a_policy_that_genuinely_beats_the_capacity_baselines_can_qualify():
    result = s.evaluate(campaign(argmaxCapacity, bonus=0.05, noise=random.Random(7)))
    assert result["qualified"], result
    assert set(result["capacity_ablation"]) == {str(seed) for seed in MODEL_SEEDS}
    assert all(row["reward_ci95"][0] > 0 for row in result["capacity_ablation"].values())
    assert not result["safety_calibrated"] and not result["autonomous_activation"]


def test_every_model_seed_must_pass_without_selection():
    rows = campaign(argmaxCapacity, bonus=0.05)
    for row in rows:
        if row["policy"] == s.LEARNED and row["model_seed"] == 45:
            row["reward"] -= 0.05
    result = s.evaluate(rows)
    assert not result["qualified"]
    assert not result["model_seed_checks"]["45"]["reward_vs_capacity-oracle"]
    assert result["model_seed_checks"]["41"]["reward_vs_capacity-oracle"]


@pytest.mark.parametrize(
    "mutate,failure",
    [
        (lambda rows: [r for r in rows if r.get("model_seed") != 45], None),
        (
            lambda rows: [r for r in rows if (r["policy"], r["model_seed"]) != (s.ABLATION, 41)],
            "capacity_ablation_missing_for_model_seed",
        ),
        (
            lambda rows: [r for r in rows if r["policy"] != "capacity-aware-ospf"],
            "baseline_missing:capacity-aware-ospf",
        ),
        (
            lambda rows: [r for r in rows if r["profile"] != "overload"],
            "too_few_paired_test_seeds:overload",
        ),
        (
            lambda rows: [
                r for r in rows if not (r["policy"] == "heuristic" and r["seed"] == 3000)
            ],
            "unpaired_test_episodes",
        ),
        (lambda rows: rows + [dict(rows[0])], "duplicate_outcome"),
        (lambda rows: rows[:-1] + [dict(rows[-1], reward=math.nan)], "invalid_outcome"),
        (lambda rows: rows[:-1] + [dict(rows[-1], seed=4000)], "invalid_outcome"),
        (lambda rows: rows[:-1] + [dict(rows[-1], model_seed=None)], "invalid_outcome"),
    ],
)
def test_incomplete_or_malformed_campaigns_fail_closed(mutate, failure):
    rows = mutate(copy.deepcopy(campaign(argmaxCapacity, bonus=0.05)))
    result = s.evaluate(rows)
    assert not result["qualified"]
    assert (failure or "fewer_than_min_model_seeds") in result["failures"]


def test_seed_span_reserved_seeds_holdout_and_version_are_enforced():
    rows = campaign(argmaxCapacity, bonus=0.05)
    assert s.evaluate(rows, reserved=[3025])["failures"] == ["reserved_seed_reused"]
    narrow = [dict(row, seed=3000 + SEEDS.index(row["seed"])) for row in rows]
    assert "test_seed_span_too_narrow:low" in s.evaluate(narrow)["failures"]
    plan = s.protocol()
    plan["holdout_profiles"] = ["path0"]
    assert "whole_profile_holdout_missing_or_overlapping" in s.evaluate(rows, plan)["failures"]
    with pytest.raises(ValueError, match="version"):
        s.evaluate(rows, dict(plan, version="nanfo.adr024"))
    declared = s.protocol()
    assert declared["min_model_seeds"] >= 5 and declared["test_seed_range"] == [3000, 3999]
    assert not set(declared["holdout_profiles"]) & set(declared["training_profiles"])
