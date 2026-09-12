"""ADR015 preregistration, validation-only selection and paired final gates."""

import math
import statistics

import numpy as np
from frozen import module

PROFILES = [
    "balanced",
    "moderate0",
    "moderate1",
    "severe0",
    "severe1",
    "overload",
    "path0",
    "path1",
]
POLICIES = ["incumbent", "candidate", "ospf", "heuristic", "constant0", "constant1"]


def schedule(first, count):
    return [{"seed": first + i, "scenario": PROFILES[i % 8]} for i in range(count)]


def declaration():
    return {
        "version": "adr015-refinement-v1",
        "adr": "ADR-015",
        "authorization": "explicit user request and accepted ADR015; isolated lab only",
        "profiles": PROFILES,
        "steps": 4,
        "window_seconds": 2.0,
        "training": schedule(1808, 192),
        "validation": schedule(2800, 16),
        "test": schedule(3600, 24),
        "validation_checkpoints": [128, 256, 384, 512],
        "minimum_transitions": 256,
        "maximum_transitions": 512,
        "ppo_config": module("ppo")
        .PPOConfig(
            seed=45,
            learning_rate=0.0005,
            gamma=0.9,
            entropy=0.01,
        )
        .model_dump(),
        "configurations": 1,
        "initialization": "verified incumbent model tensors only; fresh optimizer/RNG/counters",
        "rationale": "lower fixed LR preserves directional actor while learning stationary hold",
        "reward": "unchanged ADR014 reward including -0.05 per actual route change",
        "validation_order": [p for p in POLICIES if p != "candidate"],
        "test_order": ["ospf", "candidate", "constant1", "incumbent", "heuristic", "constant0"],
        "selection": "highest eligible validation mean reward; earliest checkpoint breaks tie",
        "validation_gain": 0.02,
        "route_reduction_fraction": 0.25,
        "delivery_relative_margin": 0.03,
        "rtt_relative_margin": 0.10,
        "rtt_absolute_margin_ms": 2.0,
        "reward_nonregression_margin": 0.02,
        "nonregression_groups": ["all", "anchors", "lowload"],
        "group_definitions": {"anchors": ["path0", "path1"], "lowload": ["balanced"]},
        "validation_rule": (
            "reward delta >.02 OR changes <=.75*incumbent with incumbent>0; "
            "all/anchors/lowload mean delivery >=.97*incumbent, "
            "RTT <=1.1*incumbent+2ms, reward >=incumbent-.02; "
            "lowload changes <=incumbent"
        ),
        "final_rule": (
            "selected endpoint paired seed mean 95% bootstrap CI lower>0; "
            "all/anchors/lowload paired delivery margin CI lower>=0, "
            "RTT margin CI lower>=0, reward margin CI lower>=0; "
            "lowload route increase CI upper<=0; any outage fails healthy gate"
        ),
        "ci": "paired seed means; percentile bootstrap 20000 draws; RNG15015; no decision IID",
        "final_attempts": 1,
        "retry": False,
        "tune_on_validation": False,
        "budget_seconds": 14400,
        "cleanup_reserve_seconds": 120,
        "budget_admission": "1.35*max seconds/episode (initial25); remaining episodes + startups90",
        "continue": "up to512 if next128+validation+final reserve fit; no quality stop below256",
        "autonomous_dispatch": "blocked",
        "default": "unchanged ADR014 incumbent",
    }


def admission(remaining, stageEpisodes, finalEpisodes, secondsPerEpisode=25.0, starts=1):
    if any(not math.isfinite(x) or x < 0 for x in (remaining, secondsPerEpisode)):
        raise ValueError("invalid budget clock")
    return (
        remaining
        >= 120 + 1.35 * max(25.0, secondsPerEpisode) * (stageEpisodes + finalEpisodes) + 90 * starts
    )


def interval(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("paired CI needs at least two finite independent seed means")
    rng = np.random.default_rng(15015)
    means = values[rng.integers(0, len(values), size=(20000, len(values)))].mean(axis=1)
    return {
        "mean": float(values.mean()),
        "ci95": np.quantile(means, [0.025, 0.975]).tolist(),
        "paired_seeds": len(values),
    }


def compare(candidate, incumbent, *, final=False, endpoint=None):
    if [(r["seed"], r["scenario"]) for r in candidate] != [
        (r["seed"], r["scenario"]) for r in incumbent
    ] or len({r["seed"] for r in candidate}) != len(candidate):
        raise ValueError("comparison requires exact unique paired seed/profile order")
    groups = {}
    for group, profiles in {
        "all": PROFILES,
        "anchors": ["path0", "path1"],
        "lowload": ["balanced"],
    }.items():
        pairs = [
            (c, i) for c, i in zip(candidate, incumbent, strict=True) if c["scenario"] in profiles
        ]
        if len(pairs) < 2:
            raise ValueError("missing nonregression group")
        margins = {
            "delivery": [c["delivery"] - 0.97 * i["delivery"] for c, i in pairs],
            "rtt": [1.1 * i["rtt"] + 2 - c["rtt"] for c, i in pairs],
            "reward": [c["reward"] - i["reward"] + 0.02 for c, i in pairs],
        }
        checks = {key: interval(values) for key, values in margins.items()}
        passed = all(
            row["ci95"][0] >= 0 if final else row["mean"] >= 0 for row in checks.values()
        ) and not any(c["outages"] for c, _ in pairs)
        if group == "lowload":
            checks["route_increase"] = interval([c["changes"] - i["changes"] for c, i in pairs])
            route = checks["route_increase"]
            passed &= (route["ci95"][1] if final else route["mean"]) <= 0
        groups[group] = {"passed": passed, "margins": checks}
    reward = interval(
        [c["reward"] - i["reward"] for c, i in zip(candidate, incumbent, strict=True)]
    )
    changes = interval(
        [i["changes"] - c["changes"] for c, i in zip(candidate, incumbent, strict=True)]
    )
    baseChanges = statistics.mean(i["changes"] for i in incumbent)
    selected = endpoint or ("reward" if reward["mean"] > 0.02 else "changes")
    meaningful = reward["mean"] > 0.02 or (
        baseChanges > 0 and changes["mean"] >= 0.25 * baseChanges
    )
    if final:
        if endpoint not in ("reward", "changes"):
            raise ValueError("final endpoint must be locked by validation")
        meaningful = {"reward": reward, "changes": changes}[endpoint]["ci95"][0] > 0
    return {
        "passed": meaningful and all(g["passed"] for g in groups.values()),
        "endpoint": selected,
        "reward": reward,
        "changes": changes,
        "groups": groups,
    }
