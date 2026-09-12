"""Immutable long-campaign schedule, counterbalancing, budgets and qualification."""

import math
import statistics

from history import OLD, ppo
from protocol import PROFILES, RANGES, schedule

METHODS = ["incumbent", "candidate512", "constant0", "constant1", "heuristic", "ospf", "candidate"]
UNIT = "nanfo-refinement-long-001.service"


def orderedSessions(split, count, methods, checkpoint):
    first = 20000 if split == "validation" else 30000
    sessions = []
    for block in range(count // 8):
        # Cyclic Latin-square order: each method visits every position in seven
        # blocks; the eighth/sixteenth blocks are explicitly recorded residuals.
        offset = block % len(methods)
        order = methods[offset:] + methods[:offset]
        for method in order:
            sessions.append(
                {
                    "stage": f"{split}-{checkpoint}-b{block:02}-{method}",
                    "split": split,
                    "policy": method,
                    "rows": schedule(first + block * 8, 8),
                }
            )
    return sessions


def declaration():
    return {
        "version": "adr016-balanced-long-v1",
        "adr": "ADR-016",
        "authorization": "explicit parent/user-approved finite24h experiment",
        "seed_namespaces": RANGES,
        "profiles": PROFILES,
        "training": schedule(10000, 512),
        "validation": schedule(20000, 64),
        "test": schedule(30000, 128),
        "steps": 4,
        "window_seconds": 2.0,
        "maximum_transitions": 2048,
        "validation_checkpoints": [1024, 2048],
        "training_block_transitions": 128,
        "ppo_config": ppo.PPOConfig(
            seed=46, learning_rate=0.0005, gamma=0.9, entropy=0.01, rollout=32, minibatch=32
        ).model_dump(),
        "initialization": "ADR015 candidate512 model tensors only; NEW Adam/RNG46; counters reset0",
        "reward": "unchanged ADR014 measured reward; route_change=-0.05",
        "balanced_updates": "32 transitions: eight episodes, each of eight profiles once",
        "validation_sessions": {
            "1024": orderedSessions("validation", 64, METHODS, 1024),
            "2048": orderedSessions("validation", 64, METHODS, 2048),
        },
        "test_sessions": orderedSessions("test", 128, METHODS, "selected"),
        "baseline_remeasurement": "all seven methods paired/counterbalanced at each checkpoint",
        "validation_gate": "ADR015 >.02 reward OR >=25% fewer switches vs incumbent; same margins",
        "parent_progress": "vs candidate512 reward>0 OR >=25% fewer switches from positive rate",
        "parent_nonregression": "same all/anchors/lowload margins also required vs candidate512",
        "final_gate": "locked endpoint95% paired-seed CI lower>0 vs BOTH refs; same group margins",
        "groups": {"anchors": ["path0", "path1"], "lowload": ["balanced"]},
        "margins": {
            "delivery_relative": 0.03,
            "rtt_relative": 0.1,
            "rtt_absolute_ms": 2.0,
            "reward_absolute": 0.02,
            "lowload_switch_increase": 0,
        },
        "ci": "paired seed means; percentile bootstrap20000, RNG15015; no decision IID",
        "selection": "highest qualified validation reward; earliest checkpoint on tie; after2048",
        "budget_seconds": 86400,
        "cleanup_reserve_seconds": 180,
        "final_reserve_min_seconds": 28800,
        "initial_seconds_per_episode": 25.0,
        "budget_model": (
            "1.25*max observed session-average episode seconds (excludes startup/cleanup); "
            "+max(30,1.25*observed startup/cleanup) per remaining session; final floor8h"
        ),
        "disk_limit_bytes": 4 * 1024**3,
        "disk_headroom_bytes": 64 * 1024**2,
        "retry": False,
        "restart": False,
        "autonomous_dispatch": "blocked",
        "default": "unchanged ADR014 incumbent",
        "old_final_seeds": "3600..3623 remain closed",
    }


def budget(remaining, episodes, sessions, secondsPerEpisode, *, finalReserve=True, startup=30.0):
    if any(
        not math.isfinite(x) or x < 0 for x in (remaining, episodes, sessions, secondsPerEpisode)
    ):
        raise ValueError("invalid budget accounting")
    perEpisode = 1.25 * max(25.0, secondsPerEpisode)
    startup = max(30.0, startup)
    final = max(28800, 896 * perEpisode + 112 * startup) if finalReserve else 0
    required = 180 + episodes * perEpisode + sessions * startup + final
    return {
        "admitted": remaining >= required,
        "required_seconds": required,
        "remaining_seconds": remaining,
        "final_reserve_seconds": final,
    }


def qualify(candidate, incumbent, parent, *, final=False, endpoints=None):
    againstIncumbent = OLD["plan"].compare(
        candidate, incumbent, final=final, endpoint=endpoints["incumbent"] if final else None
    )
    againstParent = OLD["plan"].compare(
        candidate, parent, final=final, endpoint=endpoints["candidate512"] if final else None
    )
    if not final:
        base = statistics.mean(r["changes"] for r in parent)
        gain = againstParent["reward"]["mean"] > 0
        reduction = base > 0 and againstParent["changes"]["mean"] >= 0.25 * base
        againstParent["endpoint"] = "reward" if gain else "changes"
        againstParent["passed"] = (gain or reduction) and all(
            g["passed"] for g in againstParent["groups"].values()
        )
    return {
        "qualified": againstIncumbent["passed"] and againstParent["passed"],
        "incumbent": againstIncumbent,
        "candidate512": againstParent,
        "endpoints": {
            "incumbent": againstIncumbent["endpoint"],
            "candidate512": againstParent["endpoint"],
        },
    }
