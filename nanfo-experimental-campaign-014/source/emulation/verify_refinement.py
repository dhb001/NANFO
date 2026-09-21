"""ADR015 instrumentation only: fixed seed 15100, all profiles, both modes, no training."""

import hashlib
import json
import os
import random
import signal
import time
import uuid
from pathlib import Path

from emulation.experiment import Experiment, OspfLab, environmentSpec
from emulation.measurements import atomicJson
from emulation.workloads import MATCHED_SCENARIOS


def verifyWindow(data):
    evidence, observation = data["evidence"], data["observation"]
    spec, digest = environmentSpec(data["mode"])
    assert not data["truncated"] and evidence["measurement_complete"]
    assert evidence["environment_spec"] == spec and evidence["spec_hash"] == digest
    assert spec["version"] == 5
    assert evidence["provenance"]["lab_image_id"] == os.environ["NANFO_LAB_IMAGE_ID"]
    profile = spec["profiles"][data["scenario"]]
    rng = random.Random(data["seed"])
    expected = {
        "phase_index": data["step_index"],
        "background_path": 0,
        "offered_mbps": round(rng.uniform(*profile["offered_mbps"]), 3),
        "background_mbps": round(rng.uniform(*profile["background_mbps"]), 3),
    }
    capacities = [None, None]
    for path in profile["capacity_draw_order"]:
        choices = profile["path_capacity_mbps"][path]
        capacities[path] = choices[0] if len(choices) == 1 else rng.choice(choices)
    expected["path_capacity_mbps"] = capacities
    assert evidence["phase"] == expected
    assert observation["path_capacity_mbps"] == capacities
    for key in ("capacity_readback", "capacity_readback_end"):
        rows = evidence[key]
        assert len(rows) == 8 and len({r["interface"] for r in rows}) == 8
        assert [r["capacity_mbps"] for r in rows] == [capacities[0]] * 4 + [capacities[1]] * 4
        for row in rows:
            owned = [
                c for c in row["classes"] if c.get("kind") == "htb" and c.get("handle") == "5:1"
            ]
            assert len(owned) == 1
            assert all(
                owned[0]["options"][k] == row["capacity_mbps"] * 1e6 / 8 for k in ("rate", "ceil")
            )
    for i, key in enumerate(("offered_mbps", "background_mbps")):
        sent, received = evidence["udp_sent"][i], evidence["udp_received"][i]
        actual = sent["bytes"] * 8 / sent["duration_seconds"] / 1e6
        assert actual == evidence["actual_offered_mbps"][i]
        assert abs(actual / expected[key] - 1) <= 0.2
        assert 0 <= received["packets"] <= sent["packets"]
        assert received["bytes"] == received["packets"] * 1200
    assert observation["actual_offered_mbps"] == evidence["actual_offered_mbps"][0]
    assert evidence["drain_status"] == "verified_empty"
    assert 0 < evidence["drain_duration_seconds"] <= 3
    empty = evidence["drain_empty_observations"]
    assert len(empty) == 2 and empty[1]["start"] - empty[0]["end"] >= 0.08
    assert len(evidence["drain_queue_interfaces"]) == 22
    for sweep in empty:
        assert set(sweep["queues"]) == set(evidence["drain_queue_interfaces"])
        assert all(
            q["backlog_bytes"] == q["backlog_packets"] == 0 for q in sweep["queues"].values()
        )
    assert all(v is not None for k, v in observation.items() if k != "latency_ms")
    assert set(observation) == {
        "path_utilization",
        "path_queue_packets",
        "latency_ms",
        "loss_fraction",
        "goodput_mbps",
        "offered_mbps",
        "actual_offered_mbps",
        "background_mbps",
        "previous_action",
        "seconds_since_change",
        "path_capacity_mbps",
    }
    for key in ("routing_health_start", "routing_health_end"):
        paths = evidence[key]["paths"]
        assert paths["h2->h4"]["action"] == paths["h4->h2"]["action"] == 0
        if data["mode"] == "ospf":
            assert paths["h1->h3"]["action"] == paths["h3->h1"]["action"] == 0


def main():
    output = Path("/output") / ("adr015-smoke-" + str(uuid.uuid4()))
    output.mkdir()
    spec, digest = environmentSpec("matched")
    atomicJson(
        output / "plan.json",
        {
            "seed": 15100,
            "scenarios": list(MATCHED_SCENARIOS),
            "modes": ["matched", "ospf"],
            "decision_actions": [1, 0],
            "episode_steps": 2,
            "window_seconds": 2,
            "purpose": "instrumentation only; not training/validation/test or policy ranking",
            "wall_cap_seconds": 600,
            "environment_spec": spec,
            "spec_hash": digest,
            "image_id": os.environ["NANFO_LAB_IMAGE_ID"],
        },
    )
    lab = OspfLab(output)
    results, failure, env = [], None, None
    started = time.monotonic()

    def expired(signum, frame):
        raise RuntimeError("Refinement smoke deadline exceeded")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(600)
    try:
        lab.start()
        for mode in ("matched", "ospf"):
            env = Experiment(lab, mode)
            for scenario in MATCHED_SCENARIOS:
                request = {
                    "version": 1,
                    "command": "reset",
                    "episode_id": None,
                    "step_index": None,
                    "seed": 15100,
                    "scenario": scenario,
                    "action": None,
                    "mode": mode,
                    "window_seconds": 2,
                    "episode_steps": 2,
                }
                for index in range(3):
                    response = env.handle(request)
                    assert response["ok"], response
                    data = response["data"]
                    verifyWindow(data)
                    results.append(
                        {
                            "mode": mode,
                            "scenario": scenario,
                            "episode_id": data["episode_id"],
                            "step_index": index,
                            "drain_seconds": data["evidence"]["drain_duration_seconds"],
                            "path_capacity_mbps": data["observation"]["path_capacity_mbps"],
                        }
                    )
                    request.update(
                        command="step",
                        episode_id=data["episode_id"],
                        step_index=index + 1,
                        action=1 if index == 0 else 0,
                    )
                assert data["terminated"] and data["evidence"]["cleanup_verified"]
            request.update(command="close", step_index=2, action=None)
            response = env.handle(request)
            assert response["ok"] and response["data"]["cleanup_verified"]
    except Exception as error:
        failure = str(error)[:1000] or type(error).__name__
    finally:
        signal.alarm(0)
        try:
            if env is not None:
                env.routing.close()
            lab.close()
        except Exception as error:
            failure = failure or str(error)[:1000]
        inventory = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob("*.json")
        }
        summary = {
            "passed": failure is None and len(results) == 54,
            "error": failure,
            "cleanup_verified": failure is None and lab.network.net is None,
            "output": str(output),
            "windows": results,
            "artifact_sha256": inventory,
            "elapsed_seconds": time.monotonic() - started,
            "spec_hash": digest,
            "source_sha256": spec["source_sha256"],
            "image_id": os.environ["NANFO_LAB_IMAGE_ID"],
        }
        atomicJson(output / "summary.json", summary)
        print(
            json.dumps(
                {k: v for k, v in summary.items() if k not in ("windows", "artifact_sha256")}
            )
        )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
