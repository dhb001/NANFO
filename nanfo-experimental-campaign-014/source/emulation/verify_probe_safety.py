"""Private Lab: real capture cancellation latency, expiry delivery and restart safety.

No backend or training. The expiry callback models the operator worker publishing
its exact cancel command; the lab does not invent a new post-completion TTL policy.
"""

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from emulation.actions import Actions
from emulation.mailbox import Mailbox, planHash, safeWrite
from emulation.measurements import atomicJson
from emulation.probe_paths import CaptureInterrupted, capturePaths
from emulation.runner import Lab, requireContainer


def main():
    requireContainer()
    lab = Lab(Path("/output"))
    report = {"passed": False}
    commands, results = Path("/tmp/safety-commands"), Path("/tmp/safety-results")
    commands.mkdir()
    results.mkdir()
    box = None
    try:
        lab.start()
        driver = Actions(lab)
        box = Mailbox(driver, lab.runId, "a" * 64, commands, results)
        lab.mailbox = box
        report["baseline"] = capturePaths(lab)
        plan = {
            "operation": "reroute",
            "source_host": "h1",
            "destination_host": "h3",
            "paths": [["access1", "dist1", "core", "dist2", "access2"]],
            "weights": [],
            "rate_mbps": None,
            "dscp": None,
        }
        for mode in ("expiry", "STOP"):
            time.sleep(3.1)
            lab.probe()
            cmd = {
                "version": 1,
                "execution_id": str(uuid.uuid4()),
                "run_id": lab.runId,
                "binding_digest": "a" * 64,
                "plan_hash": planHash(plan),
                "fence": 1,
                "deadline": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
                "dispatch_expires_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=5)
                ).isoformat(),
                "operation": "execute",
                "plan": plan,
            }
            assert box.handle(cmd)["status"] == "completed"
            generation = box.control_generation
            sender_seen = None
            published = restored = None
            checks = []

            def controls(cmd=cmd, mode=mode, checks=checks, generation=generation):
                nonlocal sender_seen, published, restored
                now = time.monotonic()
                checks.append(now)
                if sender_seen is None and any(
                    "emulation.probe_paths" in process.args for process in lab.processes
                ):
                    sender_seen = now
                if sender_seen is not None and now - sender_seen >= 0.1 and published is None:
                    published = time.monotonic()
                    safeWrite(
                        commands / (cmd["execution_id"] + ".json"),
                        {**cmd, "operation": "cancel", "fence": 2},
                    )
                box.poll(cancel_only=True)
                if published is not None and box.load()["active"] is None and restored is None:
                    restored = time.monotonic()
                    if mode == "STOP":
                        lab.stopping = True
                return generation != box.control_generation

            try:
                capturePaths(lab, service_controls=controls)
                raise AssertionError("Interrupted capture claimed success")
            except CaptureInterrupted:
                pass
            finally:
                lab.stopping = False
            record = box.load()["records"][cmd["execution_id"]]
            assert record["result"]["status"] == "cancelled"
            assert record["result"]["rollback"]["verified"]
            driver.reconcile()
            assert published is not None and restored is not None
            assert restored - published < 3
            assert not lab.processes
            report[mode] = {
                "cancel_to_verified_restoration_seconds": restored - published,
                "max_checkpoint_gap_seconds": max(b - a for a, b in zip(checks, checks[1:])),
                "capture_status": "partial",
                "rollback_verified": True,
                "no_new_artifact": json.loads((lab.output / "probe-paths.json").read_bytes())[
                    "window_id"
                ]
                == report["baseline"]["window_id"],
            }
            assert report[mode]["no_new_artifact"]
        report["restored"] = capturePaths(lab)
        # Seed the persisted restart state; absence verification uses real OVS/TC.
        # This exercises recovery readback, not an actual container restart.
        state = box.load()
        old = state["records"][cmd["execution_id"]]
        old["command"]["run_id"] = str(uuid.uuid4())
        old["result"]["run_id"] = old["command"]["run_id"]
        old["result"]["status"] = "completed"
        state["active"] = cmd["execution_id"]
        box.save(state)
        box.recover(state)
        obsolete = box.handle({**old["command"], "operation": "cancel", "fence": 3})
        assert (
            obsolete["status"] == "cancelled" and obsolete["verification"]["no_mutation_verified"]
        )
        report["obsolete_cancel"] = obsolete
        report["passed"] = report["baseline"]["passed"] and report["restored"]["passed"]
        atomicJson(lab.output / "probe-safety-verification.json", report)
        print(json.dumps(report, indent=2))
    finally:
        if box is not None:
            state = box.load()
            if state["active"]:
                active = state["records"][state["active"]]["command"]
                box.handle({**active, "operation": "cancel", "fence": active["fence"] + 1})
        lab.close()


if __name__ == "__main__":
    main()
