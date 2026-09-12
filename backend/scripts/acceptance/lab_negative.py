"""Runs ONLY inside the campaign's isolated Docker lab, using existing Lab/Actions controls.

No remote endpoint is added. Controller SIGSTOP, SIGTERM and Mininet link status
are real faults. Preparation must reject stale/incomplete topology before mutation.
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path


def main():
    from emulation.actions import Actions
    from emulation.runner import Lab, requireContainer

    requireContainer()
    lab = Lab(Path("/output"))
    report = {"passed": False, "cases": {}}
    plan = {"operation": "reroute", "source_host": "h1", "destination_host": "h3",
            "paths": [["access1", "dist1", "core", "dist2", "access2"]],
            "weights": [1], "rate_mbps": None, "dscp": None}
    try:
        lab.start()
        driver = Actions(lab)
        controller_args = lab.controller.args
        for case in ("linkfail", "stale", "disconnect"):
            driver.reconcile()
            if case == "linkfail":
                lab.net.configLinkStatus("access1", "dist1", "down")
            elif case == "stale":
                os.kill(lab.controller.pid, signal.SIGSTOP)
            else:
                lab.controller.terminate()
                lab.controller.wait(timeout=5)
            started = time.monotonic()
            try:
                time.sleep(8)
                try:
                    driver.prepare(plan)
                except ValueError:
                    pass
                else:
                    raise RuntimeError("Fault did not reject preparation")
                absent = driver.reconcile()
                report["cases"][case] = {"fault_injected": True, "proposal_rejected": True,
                                         "no_mutation_readback": absent}
            finally:
                if case == "linkfail":
                    lab.net.configLinkStatus("access1", "dist1", "up")
                elif case == "stale":
                    os.kill(lab.controller.pid, signal.SIGCONT)
                else:
                    lab.controller = subprocess.Popen(controller_args, stdout=subprocess.DEVNULL,
                                                      stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 45
            while not lab.ready(lab.controllerState(), hosts=False):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Recovery readiness deadline")
                time.sleep(0.3)
            probes = lab.probe()
            if len(probes) != 4 or any(p["sent"] != p["received"] for p in probes):
                raise RuntimeError("Recovered physical probe failed")
            report["cases"][case].update(recovery_seconds=time.monotonic() - started, probes=probes)
        report["passed"] = True
    finally:
        lab.close()
        # No exception text, environment, controller logs or credentials exported.
        (Path("/output") / "negative.json").write_text(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
