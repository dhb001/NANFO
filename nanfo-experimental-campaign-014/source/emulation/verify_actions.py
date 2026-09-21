"""Local-only real traffic and crash/fault harness. Not reachable from mailbox JSON."""

import fcntl
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from emulation.actions import COOKIE, Actions, cli
from emulation.mailbox import Mailbox, planHash, safeWrite
from emulation.measurements import atomicJson, utcNow


def verifyActions(lab):
    directory = Path("/results") / ("verify-" + lab.runId)
    directory.mkdir(mode=0o700)
    commands, results = directory / "commands", directory / "results"
    commands.mkdir()
    results.mkdir()
    driver = Actions(lab)
    digest = planHash({"local_verifier": lab.runId})
    mailbox = Mailbox(driver, lab.runId, digest, commands, results)
    report = {"run_id": lab.runId, "observed_at": utcNow(), "passed": False, "checks": {}}
    checks = report["checks"]

    def command(op, paths=None, dscp=None, rate=None):
        plan = {
            "operation": op,
            "source_host": "h1",
            "destination_host": "h3",
            "paths": paths or [],
            "weights": [],
            "rate_mbps": rate,
            "dscp": dscp,
        }
        return {
            "version": 1,
            "execution_id": str(uuid.uuid4()),
            "run_id": lab.runId,
            "binding_digest": digest,
            "plan_hash": planHash(plan),
            "fence": 1,
            "deadline": (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat(),
            "dispatch_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
            "operation": "execute",
            "plan": plan,
        }

    def execute(cmd, expected="completed", hook=None):
        time.sleep(3.05)
        lab.probe()
        time.sleep(1.1)
        lab.snapshot()
        cmd["dispatch_expires_at"] = min(
            datetime.now(timezone.utc) + timedelta(seconds=5),
            datetime.fromisoformat(cmd["deadline"].replace("Z", "+00:00")),
        ).isoformat()
        safeWrite(commands / (cmd["execution_id"] + ".json"), cmd)
        result = mailbox.handle(cmd, hook)
        if result["status"] != expected:
            raise RuntimeError(f"{cmd['plan']['operation']}: expected {expected}: {result}")
        return result

    def traffic(udp=False, dscp=0, parallel=1):
        server = lab.net["h3"].popen(
            ["iperf3", "-s", "-1", "-J"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        client = None
        try:
            time.sleep(0.2)
            args = [
                "iperf3",
                "-c",
                "10.77.0.3",
                "-t",
                "4",
                "-J",
                "-P",
                str(parallel),
                "--tos",
                str(dscp << 2),
            ]
            if udp:
                args += ["-u", "-b", "18M", "-l", "1200"]
            client = lab.net["h1"].popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            text, error = client.communicate(timeout=12)
            serverText, _ = server.communicate(timeout=4)
            if client.returncode or server.returncode:
                raise RuntimeError("iperf failed: " + error.decode()[:120])
            clientResult, serverResult = json.loads(text), json.loads(serverText)
            summary = (
                serverResult["end"]["streams"][0]["udp"]
                if udp
                else serverResult["end"]["sum_received"]
            )
            if udp:
                # Pinned iperf3 has zero receiver end.bytes; actual interval bytes
                # remain valid. Sum the receiver intervals, not sender estimates.
                intervals = [row["sum"] for row in serverResult["intervals"]]
                received = sum(row["bytes"] for row in intervals)
                duration = sum(row["seconds"] for row in intervals)
                summary = {
                    **summary,
                    "bytes": received,
                    "bits_per_second": received * 8 / duration,
                    "lost_percent": serverResult["end"]["sum"]["lost_percent"],
                }
            return {
                "mbps": summary["bits_per_second"] / 1e6,
                "bytes": summary["bytes"],
                "loss_percent": summary.get("lost_percent"),
                "sent_mbps": clientResult["end"]["sum" if udp else "sum_sent"]["bits_per_second"]
                / 1e6,
            }
        finally:
            for process in (client, server):
                if process and process.poll() is None:
                    process.kill()
                    process.wait()

    def counters():
        return {
            name: driver.of("dump-flows", name, f"cookie={COOKIE}/-1")
            for name in ("access1", "access2", "dist1", "dist2", "core")
        }

    try:
        baseline = traffic()
        checks["baseline_tcp"] = baseline
        if baseline["mbps"] < 10:
            raise RuntimeError("Baseline traffic below expected campus capacity")
        path = [["access1", "dist1", "core", "dist2", "access2"]]
        delayed = command("reroute", path)
        delayed["dispatch_expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=0.2)
        ).isoformat()
        driver.reconcile()
        # Sender passed its final check, then paused before atomic publication.
        time.sleep(0.3)
        safeWrite(commands / (delayed["execution_id"] + ".json"), delayed)
        expired = mailbox.handle(delayed)
        driver.reconcile()
        if expired["status"] != "failed" or not expired["verification"].get("no_mutation_verified"):
            raise RuntimeError("Delayed expired dispatch was not rejected with readback proof")
        checks["expired_publication_no_mutation"] = expired
        reroute = command("reroute", path)
        execute(reroute)
        mailbox.poll()
        second = Mailbox(driver, lab.runId, digest, commands, results)
        try:
            fcntl.flock(mailbox.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                second.handle(reroute)
                raise RuntimeError("Concurrent executor was not excluded")
            except BlockingIOError:
                checks["concurrent_executor_excluded"] = True
        finally:
            fcntl.flock(mailbox.lock, fcntl.LOCK_UN)
            second.close()
        checks["reroute_tcp"] = traffic()
        checks["reroute_flows"] = counters()
        import re

        for name, text in checks["reroute_flows"].items():
            counts = [int(n) for n in re.findall(r"n_packets=(\d+)", text)]
            if len(counts) != 2 or not all(n > 0 for n in counts):
                raise RuntimeError(f"Full forward/return path not exercised: {name}")
        beforeDuplicate = counters()
        (results / (reroute["execution_id"] + ".json")).unlink()
        mailbox.close()
        mailbox = Mailbox(driver, lab.runId, digest, commands, results)
        recovered = mailbox.handle({**reroute, "fence": 2})
        if recovered["status"] != "completed" or recovered["fence"] != 2:
            raise RuntimeError("Lost-result recovery failed")
        afterDuplicate = counters()
        for name in beforeDuplicate:
            beforeCounts = list(map(int, re.findall(r"n_packets=(\d+)", beforeDuplicate[name])))
            afterCounts = list(map(int, re.findall(r"n_packets=(\d+)", afterDuplicate[name])))
            beforeAge = list(map(float, re.findall(r"duration=([\d.]+)s", beforeDuplicate[name])))
            afterAge = list(map(float, re.findall(r"duration=([\d.]+)s", afterDuplicate[name])))
            if (
                len(beforeCounts) != len(afterCounts)
                or any(b < a for a, b in zip(beforeCounts, afterCounts))
                or any(b < a for a, b in zip(beforeAge, afterAge))
            ):
                raise RuntimeError("Duplicate reset owned counters or flow duration")
        checks["lost_result_restart_duplicate"] = True
        controllerArgs = lab.controller.args
        lab.controller.terminate()
        lab.controller.wait(timeout=5)
        lab.controller = subprocess.Popen(
            controllerArgs, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
        )
        readyBy = time.monotonic() + 45
        while not lab.ready(lab.controllerState(), hosts=False):
            if time.monotonic() > readyBy:
                raise RuntimeError("Controller restart discovery failed")
            time.sleep(0.3)
        driver.verify(mailbox.load()["records"][reroute["execution_id"]]["prepared"])
        checks["controller_restart_tcp"] = traffic()
        if checks["controller_restart_tcp"]["mbps"] < 10:
            raise RuntimeError("Controller restart lost policy forwarding")
        cancelled = mailbox.handle({**reroute, "fence": 3, "operation": "cancel"})
        if cancelled["status"] != "cancelled" or not cancelled["rollback"]["verified"]:
            raise RuntimeError("Late cancellation failed")
        checks["late_cancel"] = cancelled
        multipath = command(
            "multipath", [["access1", "dist1", "access2"], ["access1", "dist2", "access2"]]
        )
        execute(multipath)
        rejected = command("shape", rate=5)
        result = execute(rejected, "failed")
        if not result["verification"].get("no_mutation_verified"):
            raise RuntimeError("Second action rejection lacks no-mutation proof")
        checks["second_action_no_mutation"] = result
        preCancel = {
            **command("police", rate=5),
            "operation": "cancel",
            "deadline": "2000-01-01T00:00:00Z",
            "dispatch_expires_at": "2000-01-01T00:00:00Z",
        }
        result = mailbox.handle(preCancel)
        if result["status"] != "cancelled" or not result["verification"].get(
            "no_mutation_verified"
        ):
            raise RuntimeError("First-seen cancellation lacks no-mutation proof")
        checks["first_cancel_no_mutation"] = result
        checks["multipath_tcp"] = traffic(parallel=12)
        checks["group_stats"] = {
            s: driver.of("dump-group-stats", s) for s in ("access1", "access2")
        }
        for text in checks["group_stats"].values():
            buckets = re.findall(r"bucket\d+:packet_count=(\d+)", text)
            if len(buckets) != 2 or not all(int(n) > 0 for n in buckets):
                raise RuntimeError("Both SELECT buckets not exercised")
        execute(command("restore"))
        if (
            mailbox.handle(rejected)["status"] != "failed"
            or mailbox.handle({**preCancel, "operation": "execute"})["status"] != "cancelled"
        ):
            raise RuntimeError("Rejected or cancelled identity executed later")
        checks["restore_after_rejection"] = True
        execute(command("shape", rate=5, dscp=10))
        checks["shape_classified_udp"] = traffic(udp=True, dscp=10)
        checks["shape_unclassified_udp"] = traffic(udp=True)
        checks["shape_tc_stats"] = cli(["tc", "-s", "-j", "class", "show", "dev", "access2-eth3"])
        if (
            not 3.5 <= checks["shape_classified_udp"]["mbps"] <= 6
            or checks["shape_unclassified_udp"]["mbps"] < 12
        ):
            raise RuntimeError("DSCP shaping traffic effect incorrect")
        execute(command("restore", dscp=10))
        checks["shape_restored_udp"] = traffic(udp=True, dscp=10)
        execute(command("police", rate=5, dscp=12))
        checks["police_classified_udp"] = traffic(udp=True, dscp=12)
        checks["police_unclassified_udp"] = traffic(udp=True)
        checks["meter_stats"] = {s: driver.of("meter-stats", s) for s in ("access1", "access2")}
        if (
            not 3 <= checks["police_classified_udp"]["mbps"] <= 6
            or checks["police_unclassified_udp"]["mbps"] < 12
        ):
            raise RuntimeError("Meter traffic effect incorrect")
        execute(command("restore", dscp=12))
        checks["police_restored_udp"] = traffic(udp=True, dscp=12)

        for op in ("reroute", "multipath", "shape", "police"):
            cmd = command(
                op,
                path
                if op == "reroute"
                else multipath["plan"]["paths"]
                if op == "multipath"
                else None,
                rate=5 if op in ("shape", "police") else None,
            )
            calls = [0]

            def fail(calls=calls):
                calls[0] += 1
                if calls[0] == 3:
                    raise RuntimeError("Local verification injected partial operation failure")

            failed = execute(cmd, "failed", fail)
            if not failed["rollback"]["verified"]:
                raise RuntimeError("Injected failure compensation not verified")
            checks[op + "_partial_failure"] = failed

        cmd = command("reroute", path)
        calls = [0]

        def cancelMidway():
            calls[0] += 1
            if calls[0] == 3:
                safeWrite(
                    commands / (cmd["execution_id"] + ".json"),
                    {**cmd, "fence": 2, "operation": "cancel"},
                )

        checks["mid_action_cancel"] = execute(cmd, "cancelled", cancelMidway)
        cmd = command("reroute", path)
        cmd["deadline"] = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        calls = [0]

        def deadlineMidway():
            calls[0] += 1
            if calls[0] == 3:
                time.sleep(3)

        checks["mid_action_deadline"] = execute(cmd, "failed", deadlineMidway)
        if not checks["mid_action_deadline"]["rollback"]["verified"]:
            raise RuntimeError("Deadline compensation not verified")

        # Kill an independent executor process after its first actual mutation.
        cmd = command("reroute", path)
        time.sleep(3.05)
        cmd["dispatch_expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        safeWrite(commands / (cmd["execution_id"] + ".json"), cmd)
        pid = os.fork()
        if pid == 0:
            child = Mailbox(driver, lab.runId, digest, commands, results)
            calls = [0]

            def die():
                calls[0] += 1
                if calls[0] == 3:
                    os._exit(77)

            child.handle(cmd, die)
            os._exit(78)
        _, status = os.waitpid(pid, 0)
        if os.waitstatus_to_exitcode(status) != 77:
            raise RuntimeError("Crash injection boundary not reached")
        mailbox.close()
        mailbox = Mailbox(driver, lab.runId, digest, commands, results)
        recovered = mailbox.handle({**cmd, "fence": 2})
        if recovered["status"] != "failed" or not recovered["rollback"]["verified"]:
            raise RuntimeError("Crash recovery did not compensate")
        checks["executor_process_death"] = recovered
        active = command("reroute", path)
        execute(active)
        restore = command("restore")
        calls = [0]

        def failRestore():
            calls[0] += 1
            if calls[0] == 3:
                raise RuntimeError("Local partial restore failure")

        checks["restore_partial_failure"] = execute(restore, "failed", failRestore)
        if not checks["restore_partial_failure"]["rollback"]["verified"]:
            raise RuntimeError("Failed restore before-image not reinstated")
        driver.verify(mailbox.load()["records"][active["execution_id"]]["prepared"])
        checks["failed_restore_reinstated_tcp"] = traffic()
        restored = command("restore")
        execute(restored)
        late = mailbox.handle({**restored, "operation": "cancel", "fence": 2})
        if late["status"] != "cancelled" or not late["rollback"]["verified"]:
            raise RuntimeError("Late restore cancellation failed")
        checks["late_restore_cancel"] = late
        driver.verify(mailbox.load()["records"][active["execution_id"]]["prepared"])
        execute(command("restore"))
        checks["final_tcp"] = traffic()
        if checks["final_tcp"]["mbps"] < 10:
            raise RuntimeError("Final restored traffic failed")
        # Persist an old-run interrupted restore against the now-clean real lab.
        # Recovery must inspect all reserved IDs, never install its old policy.
        oldResults = directory / "old-run-results"
        oldResults.mkdir()
        oldCommands = directory / "old-run-commands"
        oldCommands.mkdir()
        oldBox = Mailbox(driver, lab.runId, digest, oldCommands, oldResults)
        try:
            prepared = mailbox.load()["records"][active["execution_id"]]["prepared"]
            oldCommand = {
                **command("restore"),
                "run_id": str(uuid.uuid4()),
                "binding_digest": "b" * 64,
            }
            oldRecord = {
                "command": oldCommand,
                "phase": "rolling_back",
                "prepared": prepared,
                "restores": str(uuid.uuid4()),
            }
            oldBox.save(
                {
                    "records": {oldCommand["execution_id"]: oldRecord},
                    "active": None,
                    "blocked": False,
                    "actions": [],
                }
            )
            oldBox.recover(oldBox.load())
            driver.reconcile()
            if oldBox.load()["blocked"]:
                raise RuntimeError("Fresh clean lab incorrectly blocked by old restore")
            checks["old_run_restore_absence_verified"] = True
            safeWrite(oldCommands / (oldCommand["execution_id"] + ".json"), oldCommand)
            recoveredProof = oldBox.load()["records"][oldCommand["execution_id"]]["result"]
            oldBox.poll()
            if oldBox.load()["records"][oldCommand["execution_id"]]["result"] != recoveredProof:
                raise RuntimeError("Old-run polling overwrote recovery proof")
        finally:
            oldBox.close()
        # Actual partial rollback followed by a local injected acknowledgment
        # failure must persist uncertainty and block unrelated new mutations.
        previous = active
        active = command("reroute", path)
        execute(active)
        result = mailbox.handle({**previous, "operation": "cancel", "fence": 2})
        if result["status"] != "cancelled" or not result["verification"].get("already_restored"):
            raise RuntimeError("Restored policy cancellation did not reconcile current policy")
        driver.verify(mailbox.load()["records"][active["execution_id"]]["prepared"])
        checks["cancel_restored_preserves_successor"] = result
        execute(command("restore"))
        checks["successor_restore_after_old_cancel"] = True
        active = command("reroute", path)
        execute(active)
        originalRollback = driver.rollback

        def failRollback(prepared, checkpoint=lambda: None):
            switch = prepared["flows"][0][0]
            driver.of("del-flows", switch, f"cookie={COOKIE}/-1,table=0")
            raise RuntimeError("Local injected rollback acknowledgment failure")

        driver.rollback = failRollback
        uncertain = mailbox.handle({**active, "operation": "cancel", "fence": 2})
        driver.rollback = originalRollback
        if uncertain["status"] != "uncertain":
            raise RuntimeError("Rollback failure must be uncertain")
        blocked = mailbox.handle(command("shape", rate=5))
        if blocked["status"] != "failed" or "uncertain" not in blocked["failure_reason"]:
            raise RuntimeError("Uncertainty did not block further changes")
        checks["uncertainty_blocks"] = uncertain
        # Explicit local harness cleanup, not a remote unblock or a journal reset.
        originalRollback(mailbox.load()["records"][active["execution_id"]]["prepared"])
        checks["uncertain_harness_cleanup_verified"] = True
        report["passed"] = True
    except Exception as error:
        report["failure"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            state = mailbox.load()
            if state["active"] and not state["blocked"]:
                active = state["records"][state["active"]]
                mailbox.handle(
                    {
                        **active["command"],
                        "operation": "cancel",
                        "fence": active["command"]["fence"] + 1,
                    }
                )
            report["journal_blocked"] = mailbox.load()["blocked"]
            report["journal_path"] = str(directory.relative_to(Path("/results")))
            report["record_count"] = len(mailbox.load()["records"])
        finally:
            mailbox.close()
            atomicJson(lab.output / "actions-verification.json", report)
    return report
