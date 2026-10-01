"""ADR-028 successor qualification protocol, declared before any successor training.

The ADR024 gates are too weak: the policy argmax(observed path_capacity_mbps) passes all of
them (constant-policy margins, nominal-OSPF goodput/RTT intervals and the directional
majority), so they cannot show that a learned policy adds anything beyond reading the
shaped capacities. A successor model must instead beat the capacity baselines and the
heuristic, also on whole held-out profiles, for every one of at least five independently
trained model seeds, with a recorded capacity-feature ablation. Historical ADR013-ADR024
results are never re-evaluated or relabelled by this module.
"""

import math
from functools import lru_cache

from .contracts import SPLITS

VERSION = "nanfo.successor-qualification/v1"
LEARNED = "ppo"
ABLATION = "ppo-no-capacity"
CAPACITY_BASELINES = ("capacity-oracle", "capacity-aware-ospf")
BASELINES = (*CAPACITY_BASELINES, "heuristic", "ospf", "constant0", "constant1")
POLICIES = (LEARNED, ABLATION, *BASELINES)
METRICS = ("reward", "goodput_mbps", "icmp_rtt_ms")
OSPF_REFERENCE_MBPS = 100


def protocol():
    """The frozen declaration a successor campaign plan must embed unchanged."""
    return {
        "version": VERSION,
        "learned_policy": LEARNED,
        "ablation_policy": ABLATION,
        "ablation": (
            "same seeds and hyperparameters with capacity features (path_capacity_mbps) "
            "zeroed in training and evaluation"
        ),
        "baselines": list(BASELINES),
        "capacity_oracle": "argmax observed HTB path_capacity_mbps; ties keep the previous action",
        "capacity_aware_ospf": (
            f"OSPF auto-cost {OSPF_REFERENCE_MBPS} Mbps // observed capacity (integer, min 1); "
            "ties prefer the nominal first path"
        ),
        "training_profiles": ["low", "path0", "path1", "balanced", "moderate0", "moderate1"],
        "holdout_profiles": ["severe0", "severe1", "overload"],
        "holdout_rule": "held-out profiles never enter training, validation or selection",
        "test_seed_range": list(SPLITS["test"]),
        "min_test_seed_span": 500,
        "min_paired_test_seeds_per_profile": 24,
        "reserved_seeds": "every seed of any historical plan, ledger or summary is excluded",
        "min_model_seeds": 5,
        "model_seed_selection": "none; every trained model seed is evaluated and must pass",
        "reward_margin_strict_gt": 0.02,
        "interval": "two-sided 95% Student-t interval of paired deltas with df = pairs - 1",
        "gates": [
            "reward vs every baseline: mean paired delta > margin and interval lower > 0",
            "held-out profiles only, reward vs capacity baselines and heuristic: lower > 0",
            "nominal OSPF: goodput interval lower > 0 and ICMP RTT interval upper < 0",
        ],
        "qualification": "fresh measured successor campaign only; never historical evidence",
    }


def capacityOracle(observation):
    capacity = observation.path_capacity_mbps
    if capacity[0] == capacity[1]:
        return observation.previous_action
    return int(capacity[1] > capacity[0])


def capacityAwareOspf(observation):
    costs = [
        max(1, OSPF_REFERENCE_MBPS // max(value, 1e-9)) for value in observation.path_capacity_mbps
    ]
    return int(costs[1] < costs[0])


def _continuedFraction(a, b, x):
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    result = d
    for m in range(1, 400):
        for numerator in (
            m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
            -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1)),
        ):
            d = 1.0 + numerator * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + numerator / c
            c = c if abs(c) > tiny else tiny
            result *= d * c
        if abs(d * c - 1.0) < 1e-15:
            break
    return result


def _incompleteBeta(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1) / (a + b + 2):
        return front * _continuedFraction(a, b, x) / a
    return 1.0 - front * _continuedFraction(b, a, 1.0 - x) / b


def studentTCdf(value, df):
    tail = 0.5 * _incompleteBeta(df / 2, 0.5, df / (df + value * value))
    return 1.0 - tail if value > 0 else tail


@lru_cache(maxsize=256)
def studentTQuantile(probability, df):
    """Upper quantile of Student's t with df degrees of freedom (0.5 < probability < 1)."""
    if not 0.5 < probability < 1 or df < 1:
        raise ValueError("invalid Student-t quantile request")
    low, high = 0.0, 1.0
    while studentTCdf(high, df) < probability:
        high *= 2
    for _ in range(200):
        middle = (low + high) / 2
        low, high = (middle, high) if studentTCdf(middle, df) < probability else (low, middle)
    return (low + high) / 2


def pairedInterval(deltas):
    count = len(deltas)
    mean = math.fsum(deltas) / count
    if count < 2:
        return mean, None
    deviation = math.sqrt(math.fsum((value - mean) ** 2 for value in deltas) / (count - 1))
    half = studentTQuantile(0.975, count - 1) * deviation / math.sqrt(count)
    return mean, [mean - half, mean + half]


def _series(outcomes, plan, failures):
    profiles = set(plan["training_profiles"]) | set(plan["holdout_profiles"])
    low, high = plan["test_seed_range"]
    series = {}
    for row in outcomes:
        policy, modelSeed = row.get("policy"), row.get("model_seed")
        learned = policy in (LEARNED, ABLATION)
        if (
            policy not in POLICIES
            or (type(modelSeed) is not int if learned else modelSeed is not None)
            or row.get("profile") not in profiles
            or type(row.get("seed")) is not int
            or not low <= row["seed"] <= high
            or any(
                type(row.get(name)) not in (int, float) or not math.isfinite(row[name])
                for name in METRICS
            )
        ):
            failures.append("invalid_outcome")
            continue
        key = (row["profile"], row["seed"])
        target = series.setdefault((policy, modelSeed), {})
        if key in target:
            failures.append("duplicate_outcome")
        target[key] = row
    return series


def _completeness(series, plan, reserved, failures):
    if not plan["holdout_profiles"] or set(plan["holdout_profiles"]) & set(
        plan["training_profiles"]
    ):
        failures.append("whole_profile_holdout_missing_or_overlapping")
    modelSeeds = sorted(seed for policy, seed in series if policy == LEARNED)
    if len(modelSeeds) < plan["min_model_seeds"]:
        failures.append("fewer_than_min_model_seeds")
    if sorted(seed for policy, seed in series if policy == ABLATION) != modelSeeds:
        failures.append("capacity_ablation_missing_for_model_seed")
    for baseline in BASELINES:
        if (baseline, None) not in series:
            failures.append("baseline_missing:" + baseline)
    keys = {key for rows in series.values() for key in rows}
    for profile in [*plan["training_profiles"], *plan["holdout_profiles"]]:
        seeds = sorted(seed for name, seed in keys if name == profile)
        if len(seeds) < plan["min_paired_test_seeds_per_profile"]:
            failures.append("too_few_paired_test_seeds:" + profile)
        elif seeds[-1] - seeds[0] < plan["min_test_seed_span"]:
            failures.append("test_seed_span_too_narrow:" + profile)
    if any(rows.keys() != keys for rows in series.values()):
        failures.append("unpaired_test_episodes")
    if {seed for _, seed in keys} & set(reserved):
        failures.append("reserved_seed_reused")
    return modelSeeds


def _gate(candidate, baseline, keys, metric):
    return pairedInterval([candidate[key][metric] - baseline[key][metric] for key in sorted(keys)])


def evaluate(outcomes, plan=None, reserved=()):
    """Independent successor gates from raw per-episode outcomes; never trusts reported CIs."""
    plan = plan or protocol()
    if plan.get("version") != VERSION:
        raise ValueError("successor protocol version differs")
    failures = []
    series = _series(outcomes, plan, failures)
    modelSeeds = _completeness(series, plan, reserved, failures)
    margin = plan["reward_margin_strict_gt"]
    perSeed, ablation = {}, {}
    if not failures:
        keys = set(series[(LEARNED, modelSeeds[0])])
        holdout = {key for key in keys if key[0] in plan["holdout_profiles"]}
        for modelSeed in modelSeeds:
            candidate, checks = series[(LEARNED, modelSeed)], {}
            for baseline in BASELINES:
                mean, interval = _gate(candidate, series[(baseline, None)], keys, "reward")
                checks["reward_vs_" + baseline] = mean > margin and interval[0] > 0
            for baseline in (*CAPACITY_BASELINES, "heuristic"):
                _, interval = _gate(candidate, series[(baseline, None)], holdout, "reward")
                checks["holdout_reward_vs_" + baseline] = interval[0] > 0
            _, goodput = _gate(candidate, series[("ospf", None)], keys, "goodput_mbps")
            _, rtt = _gate(candidate, series[("ospf", None)], keys, "icmp_rtt_ms")
            checks["goodput_vs_ospf"] = goodput[0] > 0
            checks["rtt_vs_ospf"] = rtt[1] < 0
            perSeed[str(modelSeed)] = checks
            mean, interval = _gate(candidate, series[(ABLATION, modelSeed)], keys, "reward")
            ablation[str(modelSeed)] = {"reward_mean_delta": mean, "reward_ci95": interval}
    qualified = not failures and all(all(checks.values()) for checks in perSeed.values())
    return {
        "protocol": VERSION,
        "qualified": qualified,
        "failures": sorted(set(failures)),
        "model_seed_checks": perSeed,
        "capacity_ablation": ablation,
        "safety_calibrated": False,
        "autonomous_activation": False,
    }
