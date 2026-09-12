"""Reconstruct completed V5 sessions from raw evidence, not summary assertions."""

import statistics

from evidence import Request, phase, validate
from frozen import digest, module

c = module("contracts")
env = module("env")


def reconstruct(path, plan, schedule, policy, agent=None):
    episodes, values = [], []
    before = None
    data = None
    index, closed = 0, False
    with path.open("rb") as source:
        for line in source:
            if len(line) > 2 * 1024 * 1024:
                raise ValueError("oversized evidence record")
            row = c.parseJson(line)
            if row["kind"] == "session":
                if row["plan_sha256"] != plan["plan_sha256"] or row["schedule"] != schedule:
                    raise ValueError("raw session not bound to frozen schedule")
                continue
            if row["kind"] == "ppo_update":
                continue
            request = Request.model_validate(row["request"])
            if row["kind"] == "close":
                if data is None:
                    raise ValueError("close before any measured data")
                if row["response"] != {
                    "version": 1,
                    "ok": True,
                    "error": None,
                    "data": {
                        "closed": True,
                        "cleanup_verified": True,
                        "episode_id": data.episode_id,
                    },
                }:
                    raise ValueError("raw cleanup not verified")
                closed = True
                continue
            if closed or len(episodes) >= len(schedule):
                raise ValueError("unexpected extra measurement")
            expected = schedule[len(episodes)]
            if (request.seed, request.scenario, request.step_index or 0) != (
                expected["seed"],
                expected["scenario"],
                index,
            ) or request.command != ("reset" if index == 0 else "step"):
                raise ValueError("raw measurement order/context differs")
            data = validate(
                row["response"],
                request,
                plan["release"],
                phase(request.seed, request.scenario, index, plan["release"]["environment_spec"]),
            )
            if index:
                if agent is not None:
                    decision = agent.model.decide(env.encode([before]), deterministic=True)
                    if row["decision"] != list(decision) or request.action != decision[0]:
                        raise ValueError("actual action not deterministic checkpoint inference")
                elif policy not in ("candidate", "incumbent"):
                    action = (
                        env.heuristic(before)
                        if policy == "heuristic"
                        else int(policy == "constant1")
                    )
                    if request.action != action:
                        raise ValueError("baseline action differs")
                reward = env.rewardComponents(
                    data.observation,
                    before.previous_action,
                    censoredDelay=data.evidence["latency_timeout_ms"],
                )
                values.append(
                    {
                        "reward": reward["total"],
                        "delivery": reward["raw"]["goodput_ratio"],
                        "rtt": data.observation.latency_ms
                        if data.observation.latency_ms is not None
                        else 1000.0,
                        "changes": reward["raw"]["route_change"],
                        "outages": int(data.evidence["service_outage"]),
                    }
                )
            before = data.observation
            index += 1
            if index == 5:
                episodes.append(
                    {
                        **expected,
                        **{key: statistics.mean(v[key] for v in values) for key in values[0]},
                    }
                )
                index, values, before = 0, [], None
    if not closed or len(episodes) != len(schedule) or index:
        raise ValueError("incomplete raw session")
    return {"episodes": episodes, "evidence_sha256": digest(path), "raw_audit": True}
