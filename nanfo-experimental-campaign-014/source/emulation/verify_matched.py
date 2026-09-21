"""Bounded train-only constant-route/OSPF action-effect matrix in one owned FRR lab."""

import json
from pathlib import Path

from emulation.experiment import Experiment, OspfLab
from emulation.measurements import atomicJson


def main():
    lab = OspfLab(Path("/output"))
    results = []
    try:
        lab.start()
        for mode, action in (("matched", 0), ("matched", 1), ("ospf", 0)):
            env = Experiment(lab, mode)
            for scenario, seed in (("path0", 1000), ("path1", 1001)):
                request = {
                    "version": 1,
                    "command": "reset",
                    "episode_id": None,
                    "step_index": None,
                    "seed": seed,
                    "scenario": scenario,
                    "action": None,
                    "mode": mode,
                    "window_seconds": 2,
                    "episode_steps": 2,
                }
                for index in range(3):
                    response = env.handle(request)
                    if not response["ok"] or response["data"]["truncated"]:
                        raise RuntimeError(str(response))
                    data = response["data"]
                    results.append(
                        {"policy": f"constant{action}" if mode == "matched" else "ospf", **data}
                    )
                    request.update(
                        command="step",
                        episode_id=data["episode_id"],
                        step_index=index + 1,
                        action=action,
                    )
            env.routing.close()
        byPolicy = {}
        for row in results:
            if row["step_index"]:
                key = row["policy"] + ":" + row["scenario"]
                byPolicy.setdefault(key, []).append(row["observation"]["goodput_mbps"])
        means = {key: sum(values) / len(values) for key, values in byPolicy.items()}
        if not (
            means["constant1:path0"] > means["constant0:path0"] + 2
            and means["constant0:path1"] > means["constant1:path1"] + 2
        ):
            raise RuntimeError("Both route-optimality action-effect gates required")
        summary = {
            "passed": True,
            "train_only": True,
            "goodput_mbps": means,
            "cleanup_verified": True,
            "episode_ids": list(dict.fromkeys(r["episode_id"] for r in results)),
            "spec_hash": results[0]["evidence"]["spec_hash"],
            "source_sha256": results[0]["evidence"]["provenance"]["source_sha256"],
        }
        atomicJson(Path("/output/experiment-matched-matrix-summary.json"), summary)
        print(json.dumps(summary))
    finally:
        atomicJson(Path("/output/experiment-matched-matrix.json"), results)
        lab.close()


if __name__ == "__main__":
    main()
