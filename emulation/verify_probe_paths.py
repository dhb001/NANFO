"""Opt-in container-only ADR018 live reroute and exact restoration verification.

Run as a separate manual Lab owner, never against a running shared lab. Uses the
existing Actions driver; no training, experiment protocol or backend credentials.
"""

import json
import os
import signal
from pathlib import Path

from emulation.actions import Actions
from emulation.measurements import atomicJson, utcNow
from emulation.probe_paths import capturePaths
from emulation.runner import Lab, requireContainer


def main():
    requireContainer()
    if os.environ.get("EMULATION_CONTROL_ENABLED", "false").lower() != "false":
        raise RuntimeError("Verifier cannot share manual mailbox control")
    if Path("/results/.journal.json").exists() or Path("/results/.journal.json").is_symlink():
        raise RuntimeError("Reconcile the manual journal before using an isolated verifier")
    lab = Lab(Path("/output"))
    prepared = None
    driver = Actions(lab)
    report = {"passed": False, "observed_at": utcNow()}

    def stop(signum, frame):
        raise RuntimeError("Owned verifier interrupted")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        lab.start()
        report["run_id"] = lab.runId
        report["baseline"] = capturePaths(lab)
        plan = {
            "operation": "reroute",
            "source_host": "h1",
            "destination_host": "h3",
            "paths": [["access1", "dist1", "core", "dist2", "access2"]],
            "weights": [1],
            "rate_mbps": None,
            "dscp": None,
        }
        prepared = driver.prepare(plan)
        driver.apply(prepared, lab.checkController)
        driver.verify(prepared)
        report["rerouted"] = capturePaths(lab)
        driver.rollback(prepared)
        driver.verify(prepared, absent=True)
        prepared = None
        report["restored"] = capturePaths(lab)
        counts = {
            key: [len(p["observed_hops"]) for p in report[key]["paths"]]
            for key in ("baseline", "rerouted", "restored")
        }
        report["hop_counts"] = counts
        report["passed"] = all(report[k]["passed"] for k in counts) and counts == {
            "baseline": [3, 3, 3],
            "rerouted": [5, 5, 5],
            "restored": [3, 3, 3],
        }
        atomicJson(lab.output / "probe-paths-verification.json", report)
        print(json.dumps(report, indent=2))
        return 0 if report["passed"] else 1
    finally:
        try:
            if prepared is not None:
                driver.rollback(prepared)
                driver.verify(prepared, absent=True)
        finally:
            lab.close()


if __name__ == "__main__":
    raise SystemExit(main())
