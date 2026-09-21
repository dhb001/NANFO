"""Pure bounded byte-conserving finite-buffer fluid evaluator. See MATH.md."""

from __future__ import annotations

import copy
import hashlib
import json
import math

from app.modules.simulation.schemas import ScenarioConfig

MODEL_VERSION = "finite-buffer-fluid.v1"
LATENCY_DEFINITION = "delivered-byte-weighted residence time; proportional mixed-fluid queue approximation; tick-rounded propagation; not measured RTT"


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def canonical_config(config: ScenarioConfig) -> dict:
    value = config.model_dump(mode="json")
    value["links"].sort(key=lambda link: link["link_id"])
    value["flows"].sort(key=lambda flow: flow["flow_id"])
    return value


def workload_hash(config: ScenarioConfig) -> str:
    return digest(
        {
            "seed": config.seed,
            "tick_ms": config.tick_ms,
            "duration_ticks": config.duration_ticks,
            "flows": [
                {
                    "flow_id": f.flow_id,
                    "source": f.source,
                    "target": f.target,
                    "demand_mbps": f.demand_mbps * config.duration_ticks
                    if len(f.demand_mbps) == 1
                    else f.demand_mbps,
                }
                for f in sorted(config.flows, key=lambda f: f.flow_id)
            ],
        }
    )


def _seal(state: dict) -> dict:
    return {"state": state, "checkpoint_sha256": digest(state)}


def initial_checkpoint(config: ScenarioConfig) -> dict:
    config = ScenarioConfig.model_validate(canonical_config(config))
    queues = {link.link_id: {} for link in config.links}
    for flow in config.flows:
        for link in flow.path:
            queues[link][flow.flow_id] = [0.0, 0.0]
    return _seal(
        {
            "model_version": MODEL_VERSION,
            "input_sha256": digest(canonical_config(config)),
            "tick": 0,
            "queues": queues,
            "pipeline": {},
            "background": {
                link.link_id: {
                    "initial_bytes": link.initial_queue_bytes,
                    "queued_bytes": link.initial_queue_bytes,
                    "inflight_bytes": 0.0,
                    "delivered_bytes": 0.0,
                }
                for link in config.links
            },
            "flows": {
                flow.flow_id: {
                    "offered_bytes": 0.0,
                    "delivered_bytes": 0.0,
                    "dropped_bytes": 0.0,
                    "queued_bytes": 0.0,
                    "inflight_bytes": 0.0,
                    "delivered_residence_byte_ms": 0.0,
                }
                for flow in config.flows
            },
            "trace": [],
        }
    )


def _conservation(state: dict) -> None:
    for flow_id, flow in state["flows"].items():
        values = list(flow.values())
        if any(
            not isinstance(v, (int, float)) or not math.isfinite(v) or v < -1e-6
            for v in values
        ):
            raise ValueError("Invalid checkpoint fluid values")
        total = sum(
            flow[key]
            for key in (
                "delivered_bytes",
                "dropped_bytes",
                "queued_bytes",
                "inflight_bytes",
            )
        )
        if not math.isclose(flow["offered_bytes"], total, rel_tol=1e-10, abs_tol=1e-6):
            raise ValueError("Flow conservation failed")
        queued = sum(q.get(flow_id, [0])[0] for q in state["queues"].values())
        inflight = sum(
            item[2]
            for items in state["pipeline"].values()
            for item in items
            if item[0] == flow_id
        )
        if not math.isclose(
            queued, flow["queued_bytes"], rel_tol=1e-10, abs_tol=1e-6
        ) or not math.isclose(
            inflight, flow["inflight_bytes"], rel_tol=1e-10, abs_tol=1e-6
        ):
            raise ValueError("Checkpoint queue/pipeline mismatch")
    for link_id, bg in state["background"].items():
        if any(not math.isfinite(value) or value < -1e-6 for value in bg.values()):
            raise ValueError("Invalid checkpoint background values")
        total = bg["queued_bytes"] + bg["inflight_bytes"] + bg["delivered_bytes"]
        inflight = sum(
            item[2]
            for items in state["pipeline"].values()
            for item in items
            if item[0] is None and item[1] == link_id
        )
        if not math.isclose(
            bg["initial_bytes"], total, rel_tol=1e-10, abs_tol=1e-6
        ) or not math.isclose(
            inflight, bg["inflight_bytes"], rel_tol=1e-10, abs_tol=1e-6
        ):
            raise ValueError("Initial background conservation failed")


def validate_checkpoint(config: ScenarioConfig, checkpoint: dict) -> dict:
    try:
        state = checkpoint["state"]
        if (
            checkpoint["checkpoint_sha256"] != digest(state)
            or state["model_version"] != MODEL_VERSION
            or state["input_sha256"] != digest(canonical_config(config))
            or type(state["tick"]) is not int
            or not 0 <= state["tick"] <= config.duration_ticks
            or len(state["trace"]) != state["tick"]
        ):
            raise ValueError("Checkpoint identity/hash/tick mismatch")
        expected = initial_checkpoint(config)["state"]
        if set(state["flows"]) != set(expected["flows"]) or set(state["queues"]) != set(
            expected["queues"]
        ):
            raise ValueError("Checkpoint graph mismatch")
        if set(state["background"]) != set(expected["background"]):
            raise ValueError("Checkpoint background graph mismatch")
        flow_paths = {flow.flow_id: flow.path for flow in config.flows}
        entries = 0
        for due, items in state["pipeline"].items():
            if (
                not str(due).isdigit()
                or not state["tick"] <= int(due) <= state["tick"] + 60001
            ):
                raise ValueError("Checkpoint pipeline due tick invalid")
            entries += len(items)
            if entries > 16384:
                raise ValueError("Checkpoint pipeline exceeds work bound")
            for flow_id, hop, amount, moment in items:
                if (
                    not math.isfinite(amount + moment)
                    or amount < 0
                    or moment < 0
                    or moment > amount * state["tick"] * config.tick_ms + 1e-6
                ):
                    raise ValueError("Checkpoint pipeline fluid invalid")
                if flow_id is None:
                    if hop not in state["background"] or moment != 0:
                        raise ValueError("Checkpoint background pipeline invalid")
                elif (
                    flow_id not in flow_paths
                    or type(hop) is not int
                    or not 1 <= hop <= len(flow_paths[flow_id])
                ):
                    raise ValueError("Checkpoint pipeline route invalid")
        for link in config.links:
            if set(state["queues"][link.link_id]) != set(
                expected["queues"][link.link_id]
            ):
                raise ValueError("Checkpoint flow route mismatch")
            if (
                state["background"][link.link_id]["initial_bytes"]
                != link.initial_queue_bytes
            ):
                raise ValueError("Checkpoint background mismatch")
            total = state["background"][link.link_id]["queued_bytes"]
            for amount, moment in state["queues"][link.link_id].values():
                if (
                    not math.isfinite(amount + moment)
                    or amount < -1e-6
                    or moment < -1e-6
                    or moment > amount * state["tick"] * config.tick_ms + 1e-6
                ):
                    raise ValueError("Checkpoint invalid queue")
                total += amount
            if total > link.buffer_bytes + 1e-6:
                raise ValueError("Checkpoint buffer exceeded")
        _conservation(state)
        return state
    except (KeyError, TypeError, OverflowError, IndexError, AttributeError) as exc:
        raise ValueError("Malformed checkpoint") from exc


def _metrics(flow: dict, elapsed_ms: int) -> dict:
    offered, delivered = flow["offered_bytes"], flow["delivered_bytes"]
    return {
        **flow,
        "loss_pct": 100 * flow["dropped_bytes"] / offered if offered else None,
        "delivery_ratio": delivered / offered if offered else None,
        "throughput_mbps": delivered * 8 / (elapsed_ms * 1000) if elapsed_ms else None,
        "latency_ms": flow["delivered_residence_byte_ms"] / delivered
        if delivered
        else None,
    }


def advance(config: ScenarioConfig, checkpoint: dict, *, ticks: int = 8) -> dict:
    if type(ticks) is not int or not 1 <= ticks <= 32:
        raise ValueError("Batch must contain 1..32 ticks")
    state = copy.deepcopy(validate_checkpoint(config, checkpoint))
    flows = {
        flow.flow_id: flow for flow in sorted(config.flows, key=lambda f: f.flow_id)
    }
    links = sorted(config.links, key=lambda link: link.link_id)
    for tick in range(state["tick"], min(state["tick"] + ticks, config.duration_ticks)):
        start, end = tick * config.tick_ms, (tick + 1) * config.tick_ms
        arrivals = {link.link_id: {} for link in links}

        def arrive(item, start=start, arrivals=arrivals):
            flow_id, hop, amount, moment = item
            if flow_id is None:
                bg = state["background"][hop]
                bg["inflight_bytes"] -= amount
                bg["delivered_bytes"] += amount
                return
            stats = state["flows"][flow_id]
            stats["inflight_bytes"] -= amount
            if hop == len(flows[flow_id].path):
                stats["delivered_bytes"] += amount
                stats["delivered_residence_byte_ms"] += amount * start - moment
            else:
                queue = arrivals[flows[flow_id].path[hop]].setdefault(
                    flow_id, [0.0, 0.0]
                )
                queue[0] += amount
                queue[1] += moment

        for item in state["pipeline"].pop(str(tick), []):
            arrive(item)
        for flow_id, flow in flows.items():
            amount = (
                flow.demand_mbps[0 if len(flow.demand_mbps) == 1 else tick]
                * config.tick_ms
                * 125
            )
            state["flows"][flow_id]["offered_bytes"] += amount
            arrivals[flow.path[0]][flow_id] = [amount, amount * start]
        link_trace = {}
        for link in links:
            queues, incoming = state["queues"][link.link_id], arrivals[link.link_id]
            bg = state["background"][link.link_id]
            existing = bg["queued_bytes"] + sum(q[0] for q in queues.values())
            incoming_total = sum(q[0] for q in incoming.values())
            admission = (
                min(1.0, max(0.0, link.buffer_bytes - existing) / incoming_total)
                if incoming_total
                else 1.0
            )
            per_flow = {}
            for flow_id in sorted(queues):
                amount, moment = incoming.get(flow_id, [0.0, 0.0])
                accepted, dropped = amount * admission, amount * (1 - admission)
                queues[flow_id][0] += accepted
                queues[flow_id][1] += moment * admission
                state["flows"][flow_id]["queued_bytes"] += accepted
                state["flows"][flow_id]["dropped_bytes"] += dropped
                per_flow[flow_id] = {"arrived_bytes": amount, "dropped_bytes": dropped}
            total = bg["queued_bytes"] + sum(q[0] for q in queues.values())
            budget = link.capacity_mbps * config.tick_ms * 125
            fraction = min(1.0, budget / total) if total else 0.0
            due = tick + 1 + math.ceil(link.delay_ms / config.tick_ms)
            for flow_id in sorted(queues):
                queue = queues[flow_id]
                amount, moment = queue[0] * fraction, queue[1] * fraction
                queue[0] -= amount
                queue[1] -= moment
                stats = state["flows"][flow_id]
                stats["queued_bytes"] -= amount
                stats["inflight_bytes"] += amount
                if amount:
                    state["pipeline"].setdefault(str(due), []).append(
                        [
                            flow_id,
                            flows[flow_id].path.index(link.link_id) + 1,
                            amount,
                            moment,
                        ]
                    )
                per_flow[flow_id].update(served_bytes=amount, queued_bytes=queue[0])
            served_background = bg["queued_bytes"] * fraction
            bg["queued_bytes"] -= served_background
            bg["inflight_bytes"] += served_background
            if served_background:
                state["pipeline"].setdefault(str(due), []).append(
                    [None, link.link_id, served_background, 0.0]
                )
            link_trace[link.link_id] = {
                "flows": per_flow,
                "served_bytes": total * fraction,
                "queued_bytes": total * (1 - fraction),
                "utilization": total * fraction / budget,
                "background_queued_bytes": bg["queued_bytes"],
                "background_served_bytes": served_background,
            }
        # Boundary deliveries count at the horizon; intermediate arrivals stay in
        # the pipeline until the next tick, never receiving multiple services/tick.
        pending = []
        for item in state["pipeline"].pop(str(tick + 1), []):
            flow_id, hop, amount, moment = item
            if flow_id is None:
                bg = state["background"][hop]
                bg["inflight_bytes"] -= amount
                bg["delivered_bytes"] += amount
            elif hop == len(flows[flow_id].path):
                stats = state["flows"][flow_id]
                stats["inflight_bytes"] -= amount
                stats["delivered_bytes"] += amount
                stats["delivered_residence_byte_ms"] += amount * end - moment
            else:
                pending.append(item)
        if pending:
            state["pipeline"][str(tick + 1)] = pending
        state["tick"] = tick + 1
        state["trace"].append(
            {
                "tick": tick + 1,
                "elapsed_ms": end,
                "links": link_trace,
                "flows": {
                    key: _metrics(value, end) for key, value in state["flows"].items()
                },
            }
        )
        _conservation(state)
    return _seal(state)


def output(config: ScenarioConfig, checkpoint: dict) -> dict:
    state = validate_checkpoint(config, checkpoint)
    elapsed = state["tick"] * config.tick_ms
    total = {
        key: sum(flow[key] for flow in state["flows"].values())
        for key in next(iter(state["flows"].values()))
    }
    metrics = _metrics(total, elapsed)
    checks = {
        "max_loss_pct": metrics["loss_pct"] is not None
        and metrics["loss_pct"] <= config.limits.max_loss_pct,
        "max_latency_ms": metrics["latency_ms"] is not None
        and metrics["latency_ms"] <= config.limits.max_latency_ms,
        "min_throughput_mbps": metrics["throughput_mbps"] is not None
        and metrics["throughput_mbps"] >= config.limits.min_throughput_mbps,
    }
    result = {
        **metrics,
        "model_version": MODEL_VERSION,
        "input_sha256": state["input_sha256"],
        "workload_sha256": workload_hash(config),
        "checkpoint_sha256": checkpoint["checkpoint_sha256"],
        "elapsed_ms": elapsed,
        "duration_ticks": config.duration_ticks,
        "tick": state["tick"],
        "source": "operator_configured_model",
        "physical_safety_authorized": False,
        "latency_definition": LATENCY_DEFINITION,
        "objective_checks": checks,
        "risk_gate": "passed"
        if state["tick"] == config.duration_ticks and all(checks.values())
        else "blocked",
        "flows": {
            key: _metrics(value, elapsed) for key, value in state["flows"].items()
        },
        "initial_background": copy.deepcopy(state["background"]),
        "trace": copy.deepcopy(state["trace"]),
    }
    return {**result, "output_sha256": digest(result)}
