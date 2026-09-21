"""ADR-010 v1 file transport and crash-conservative serialized state machine."""

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import time
import uuid
from datetime import datetime
from pathlib import Path

from emulation.actions import HOST_MAP, NAMES, PORTS
from emulation.measurements import atomicJson, utcNow

MAX_COMMAND = 8192
MAX_RECORDS = 32
MAX_TOMBSTONES = 32
HOLD_DOWN = 3
RATE_LIMIT = 30
PLAN_FIELDS = {
    "operation",
    "source_host",
    "destination_host",
    "paths",
    "weights",
    "rate_mbps",
    "dscp",
}
IDENTITY = ("version", "execution_id", "run_id", "binding_digest", "plan_hash")
COMMAND_FIELDS = {*IDENTITY, "fence", "deadline", "dispatch_expires_at", "operation", "plan"}


def planHash(plan):
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def utc(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("UTC deadline required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("UTC deadline required")
    return parsed.timestamp()


def uniqueObject(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def safeRead(path, limit=MAX_COMMAND):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError("Only bounded single-link regular JSON files allowed")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("JSON too large")
    return json.loads(
        data,
        object_pairs_hook=uniqueObject,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")),
    )


def safeWrite(path, value):
    if path.is_symlink():
        raise ValueError("Symlink publication refused")
    atomicJson(path, value)


def validateEnvelope(command, filename):
    if not isinstance(command, dict) or set(command) != COMMAND_FIELDS:
        raise ValueError("Exact command v1 fields required")
    if type(command["version"]) is not int or command["version"] != 1:
        raise ValueError("Unsupported command version")
    for key in ("execution_id", "run_id"):
        if not isinstance(command[key], str) or str(uuid.UUID(command[key])) != command[key]:
            raise ValueError("Canonical UUID required")
    if filename != command["execution_id"] + ".json":
        raise ValueError("Filename/execution identity mismatch")
    for key in ("binding_digest", "plan_hash"):
        if not isinstance(command[key], str) or not re.fullmatch("[0-9a-f]{64}", command[key]):
            raise ValueError("Lowercase SHA256 required")
    if type(command["fence"]) is not int or not 1 <= command["fence"] <= 2**63 - 1:
        raise ValueError("Bounded positive fence required")
    if command["operation"] not in ("execute", "cancel"):
        raise ValueError("Unknown transport operation")
    utc(command["deadline"])
    if utc(command["dispatch_expires_at"]) > utc(command["deadline"]):
        raise ValueError("Dispatch expiry exceeds action deadline")
    return command


def validatePlan(plan):
    if not isinstance(plan, dict) or set(plan) != PLAN_FIELDS:
        raise ValueError("Exact seven plan fields required")
    op = plan["operation"]
    if op not in ("reroute", "multipath", "shape", "police", "restore"):
        raise ValueError("Unsupported action (including VLAN/wireless)")
    for key in ("source_host", "destination_host"):
        if not isinstance(plan[key], str) or plan[key] not in HOST_MAP:
            raise ValueError("Unknown manifest host")
    if plan["source_host"] == plan["destination_host"]:
        raise ValueError("Distinct hosts required")
    dscp = plan["dscp"]
    if dscp is not None and (type(dscp) is not int or not 0 <= dscp <= 63):
        raise ValueError("DSCP must be null or integer 0..63")
    paths, weights, rate = (plan[k] for k in ("paths", "weights", "rate_mbps"))
    if not isinstance(paths, list) or not isinstance(weights, list):
        raise ValueError("Paths and weights must be arrays")
    if op in ("reroute", "multipath"):
        count = 1 if op == "reroute" else 2
        if len(paths) != count or (weights and len(weights) != count) or rate is not None:
            raise ValueError("Path count, weights or rate invalid for routing")
        if any(type(w) is not int or not 1 <= w <= 65535 for w in weights):
            raise ValueError("Weights must be integer 1..65535")
        src, dst = (NAMES[HOST_MAP[plan[k]]["dpid"]] for k in ("source_host", "destination_host"))
        for path in paths:
            if (
                not isinstance(path, list)
                or not 1 <= len(path) <= 5
                or any(not isinstance(n, str) or n not in NAMES.values() for n in path)
            ):
                raise ValueError("Bounded manifest switch path required")
            if len(set(path)) != len(path) or path[0] != src or path[-1] != dst:
                raise ValueError(
                    "Complete simple source-access to destination-access path required"
                )
            if any((a, b) not in PORTS for a, b in zip(path, path[1:])):
                raise ValueError("Path uses nonexistent link")
        if count == 2 and (paths[0] == paths[1] or set(paths[0][1:-1]) & set(paths[1][1:-1])):
            raise ValueError("Bounded SELECT supports distinct internally disjoint paths only")
    elif paths or weights:
        raise ValueError("Paths/weights not applicable to QoS/restore")
    if op in ("shape", "police"):
        if type(rate) not in (int, float) or not math.isfinite(rate) or not 1 <= rate <= 20:
            raise ValueError("Trusted QoS bounds are 1..20 Mbps")
    elif rate is not None:
        raise ValueError("Rate not applicable")
    return plan


class Interrupted(Exception):
    pass


class Mailbox:
    def __init__(self, driver, runId, digest, commands=Path("/commands"), results=Path("/results")):
        self.driver, self.runId, self.digest = driver, runId, digest
        self.commands, self.results = commands, results
        for directory in (commands, results):
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError("Dedicated real mailbox directories required")
        if not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("Operator EMULATION_BINDING_DIGEST required")
        self.journal = results / ".journal.json"
        self.lock = os.open(
            str(results / ".executor.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        self.seen = {}
        self.recovered = False
        self.control_generation = 0

    def close(self):
        os.close(self.lock)

    def load(self):
        if self.journal.exists() or self.journal.is_symlink():
            state = safeRead(self.journal, 1024 * 1024)
            if (
                set(state) != {"records", "active", "blocked", "actions"}
                or len(state["records"]) > MAX_RECORDS + MAX_TOMBSTONES
            ):
                raise ValueError("Invalid journal; operator reconciliation required")
            return state
        return {"records": {}, "active": None, "blocked": False, "actions": []}

    def save(self, state):
        safeWrite(self.journal, state)

    def result(self, command, status, verification=None, rollback=None, reason=None):
        return {
            **{k: command[k] for k in IDENTITY},
            "fence": command["fence"],
            "status": status,
            "verification": verification or {},
            "rollback": rollback,
            "failure_reason": reason,
            "completed_at": utcNow(),
        }

    def publish(self, result):
        safeWrite(self.results / (result["execution_id"] + ".json"), result)

    def finish(self, state, record, result):
        self.control_generation += 1
        record["result"], record["phase"] = result, "terminal"
        if result["status"] == "uncertain":
            state["blocked"] = True
        self.save(state)
        self.publish(result)
        return result

    def compensate(self, state, record, status, reason):
        record["phase"] = "rolling_back"
        self.save(state)
        try:
            oldRun = (
                record["command"]["run_id"] != self.runId
                or record["command"]["binding_digest"] != self.digest
            )
            if oldRun:
                record["recovered_obsolete"] = True
            actual = self.driver.reconcile() if oldRun else self.driver.rollback(record["prepared"])
            if record.get("restores") and not oldRun:
                # Undo a failed restore back to its own before-image: the active
                # policy, not the original baseline. This is journal recovery,
                # not a new authorization to dispatch a worker command.
                self.driver.apply(record["prepared"], lambda: None)
                actual = self.driver.verify(record["prepared"])
                state["active"] = record["restores"]
            elif oldRun:
                state["active"] = None
                record["recovered_obsolete"] = True
            record["after"] = actual
            if not record.get("restores") and state["active"] == record["command"]["execution_id"]:
                state["active"] = None
            rollback = {"verified": True, "readback_sha256": planHash(actual)}
        except Exception as error:
            status, rollback = "uncertain", {"verified": False}
            reason = f"{reason}; rollback {type(error).__name__}: {str(error)[:180]}"
        return self.finish(
            state, record, self.result(record["command"], status, rollback=rollback, reason=reason)
        )

    def recover(self, state):
        for record in state["records"].values():
            if record["phase"] != "terminal":
                # Never resume a partially applied action, even with a live lease.
                self.compensate(
                    state, record, "failed", "Interrupted executor; compensated without redispatch"
                )
        active = state["active"]
        if active:
            record = state["records"][active]
            try:
                if (
                    record["command"]["run_id"] != self.runId
                    or record["command"]["binding_digest"] != self.digest
                ):
                    self.driver.reconcile()
                    state["active"] = None
                    record["recovered_obsolete"] = True
                else:
                    self.driver.verify(record["prepared"])
            except Exception:
                state["blocked"] = True
            self.save(state)
        self.recovered = True

    def noMutation(self, state, command, status, reason, obsolete=False):
        record = state["records"].get(
            command["execution_id"], {"command": command, "phase": "terminal"}
        )
        record["command"] = command
        state["records"][command["execution_id"]] = record
        verification = {}
        try:
            if obsolete and not (
                record.get("recovered_obsolete")
                and record["phase"] == "terminal"
                and command["operation"] == "cancel"
                and state["active"] != command["execution_id"]
            ):
                raise ValueError("Exact recovered obsolete cancellation required")
            if (
                state["blocked"]
                or (not obsolete and command["run_id"] != self.runId)
                or (not obsolete and command["binding_digest"] != self.digest)
            ):
                raise ValueError("Cannot certify unreconciled run/binding")
            active = state["records"].get(state["active"])
            if active and (
                active["command"]["run_id"] != self.runId
                or active["command"]["binding_digest"] != self.digest
                or active["phase"] != "terminal"
                or active["result"]["status"] != "completed"
            ):
                raise ValueError("Current active policy is not reconciled")
            actual = self.driver.reconcile(active["prepared"] if active else None)
            record["after"] = actual
            verification = {
                "readback_verified": True,
                "readback_sha256": planHash(actual),
                "no_mutation_verified": True,
                "mutated": False,
                "deadline_expired": time.time() >= utc(command["deadline"]),
            }
            if record.get("restored_by"):
                verification["already_restored"] = True
            if obsolete:
                verification.update(recovered_obsolete=True, current_run_id=self.runId)
        except Exception as error:
            status = "uncertain"
            reason = f"{reason}; no-mutation reconciliation failed: {type(error).__name__}"
        return self.finish(state, record, self.result(command, status, verification, reason=reason))

    @staticmethod
    def sameIdentity(first, second):
        return all(
            first[k] == second[k] for k in (*IDENTITY, "plan", "deadline", "dispatch_expires_at")
        )

    def handle(self, command, checkpoint=None):
        """Local verifier may supply a fault hook; it is never part of JSON."""
        validateEnvelope(command, command["execution_id"] + ".json")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            state = self.load()
            if not self.recovered:
                self.recover(state)
            return self.execute(state, command, checkpoint)
        finally:
            fcntl.flock(self.lock, fcntl.LOCK_UN)

    def execute(self, state, command, hook):
        execution = command["execution_id"]
        record = state["records"].get(execution)
        try:
            validatePlan(command["plan"])
            if planHash(command["plan"]) != command["plan_hash"]:
                raise ValueError("Plan digest mismatch")
            if record and not self.sameIdentity(record["command"], command):
                raise ValueError("Execution identity is immutable")
            if record and command["fence"] < record["command"]["fence"]:
                raise ValueError("Stale fence")
            if record and record.get("recovered_obsolete") and record["phase"] == "terminal":
                if command["operation"] == "cancel":
                    record.setdefault("obsolete_result", record["result"])
                    return self.noMutation(
                        state,
                        command,
                        "cancelled",
                        "Obsolete execution absent; current run reconciled without mutation",
                        obsolete=True,
                    )
                record["command"]["fence"] = command["fence"]
                record["result"]["fence"] = command["fence"]
                return self.finish(state, record, record["result"])
            if command["run_id"] != self.runId or command["binding_digest"] != self.digest:
                raise ValueError("Stale run or operator binding mismatch")
            if state["blocked"]:
                raise ValueError("Lab uncertain; operator reconciliation required")
            if record:
                record["command"]["fence"] = command["fence"]
                if (
                    command["operation"] == "cancel"
                    and state["active"] != execution
                    and record.get("restored_by")
                ):
                    return self.noMutation(
                        state,
                        command,
                        "cancelled",
                        "Policy already restored; current state reconciled",
                    )
                if command["operation"] == "cancel" and state["active"] == execution:
                    # Late cancellation is compensation, never 'it did not run'.
                    return self.compensate(
                        state, record, "cancelled", "Late cancellation compensated"
                    )
                if (
                    command["operation"] == "cancel"
                    and record.get("restores")
                    and record["result"]["status"] == "completed"
                ):
                    if state["active"] is not None:
                        return self.finish(
                            state,
                            record,
                            self.result(
                                command,
                                "uncertain",
                                reason="Late restore cancellation conflicts with a subsequent policy",
                            ),
                        )
                    return self.compensate(
                        state,
                        record,
                        "cancelled",
                        "Late restore cancellation reinstated before-image",
                    )
                if state["active"] == execution:
                    try:
                        self.driver.verify(record["prepared"])
                    except Exception:
                        return self.finish(
                            state,
                            record,
                            self.result(
                                command,
                                "uncertain",
                                reason="Recorded completion no longer matches actual state",
                            ),
                        )
                record["result"]["fence"] = command["fence"]
                return self.finish(state, record, record["result"])
            if len(state["records"]) >= MAX_RECORDS:
                raise ValueError("32-execution capacity reached; no automatic cleanup")
            if command["operation"] == "cancel":
                return self.noMutation(state, command, "cancelled", "Cancelled before dispatch")
            now = time.time()
            if not now < utc(command["deadline"]) <= now + 300:
                raise ValueError("Expired deadline or exceeds 300 seconds")
            if not now < utc(command["dispatch_expires_at"]) <= now + 5:
                raise ValueError("Expired or overlong dispatch authorization")
            state["actions"] = [t for t in state["actions"] if now - t < 60]
            if state["actions"] and now - state["actions"][-1] < HOLD_DOWN:
                raise ValueError("Lab/selector 3-second hold-down")
            if len(state["actions"]) >= RATE_LIMIT:
                raise ValueError("Lab action rate exceeded")
            plan = command["plan"]
            active = state["records"].get(state["active"])
            if plan["operation"] == "restore":
                if not active or any(
                    active["command"]["plan"][k] != plan[k]
                    for k in ("source_host", "destination_host", "dscp")
                ):
                    raise ValueError("No matching active owned policy")
                prepared = active["prepared"]
                self.driver.verify(prepared)
            else:
                if active:
                    raise ValueError("One active policy per lab; restore before another action")
                driverPlan = {**plan, "weights": plan["weights"] or [1] * len(plan["paths"])}
                prepared = self.driver.prepare(driverPlan)
            restoreBefore = self.driver.capture() if plan["operation"] == "restore" else None
            accepted = time.time()
            if not accepted < utc(
                command["dispatch_expires_at"]
            ) <= accepted + 5 or accepted >= utc(command["deadline"]):
                raise ValueError("Dispatch authorization expired during discovery/readback")
            record = {
                "command": command,
                "phase": "prepared",
                "prepared": prepared,
                "restores": state["active"] if plan["operation"] == "restore" else None,
                "restore_before": restoreBefore,
                "dispatch_checked_at": accepted,
            }
            state["records"][execution] = record
            state["actions"].append(now)
            self.save(state)  # Durable before-image precedes the very first mutation.
        except Exception as error:
            result = self.result(command, "failed", reason=str(error)[:240])
            if not record and len(state["records"]) < MAX_RECORDS + MAX_TOMBSTONES:
                if (
                    not state["blocked"]
                    and command["run_id"] == self.runId
                    and command["binding_digest"] == self.digest
                ):
                    return self.noMutation(state, command, "failed", str(error)[:240])
                record = {"command": command, "phase": "terminal"}
                state["records"][execution] = record
                return self.finish(state, record, result)
            self.publish(result)
            return result

        def check():
            if hook:
                hook()
            path = self.commands / (execution + ".json")
            if path.exists() or path.is_symlink():
                latest = validateEnvelope(safeRead(path), path.name)
                if not self.sameIdentity(command, latest) or latest["fence"] < command["fence"]:
                    raise Interrupted("Mailbox identity/fence changed during action")
                if latest["operation"] == "cancel":
                    record["command"]["fence"] = latest["fence"]
                    raise Interrupted("Cancelled during action")
            if time.time() >= utc(command["deadline"]):
                raise Interrupted("Deadline elapsed during action")
            if getattr(self.driver.lab, "stopping", False):
                raise Interrupted("Lab stopping")

        try:
            check()
            record["phase"] = "applying"
            self.save(state)
            if command["plan"]["operation"] == "restore":
                actual = self.driver.rollback(prepared, check)
                state["active"] = None
            else:
                self.driver.apply(prepared, check)
                actual = self.driver.verify(prepared)
                state["active"] = execution
            check()
            probe = self.driver.probe(command["plan"])
            check()
            record["after"] = actual
            if record["restores"]:
                state["records"][record["restores"]]["restored_by"] = execution
            return self.finish(
                state,
                record,
                self.result(
                    command,
                    "completed",
                    {
                        "readback_verified": True,
                        "readback_sha256": planHash(actual),
                        "probe": probe,
                        "config_readback_and_reachability": True,
                        "traffic_effects_verified": False,
                    },
                    {"verified": True, "readback_sha256": planHash(actual)}
                    if record["restores"]
                    else None,
                ),
            )
        except Exception as error:
            status = (
                "cancelled"
                if isinstance(error, Interrupted) and "Cancelled" in str(error)
                else "failed"
            )
            return self.compensate(
                state, record, status, f"{type(error).__name__}: {str(error)[:200]}"
            )

    def poll(self, cancel_only=False):
        paths = []
        metadata = unknown = 0
        with os.scandir(self.commands) as entries:
            for entry in entries:
                if re.fullmatch(r"[0-9a-f-]{36}\.json", entry.name):
                    paths.append(Path(entry.path))
                elif re.fullmatch(r"\.?[0-9a-f-]{36}\.(lock|tmp)", entry.name):
                    metadata += 1
                else:
                    unknown += 1
                if len(paths) > MAX_RECORDS + MAX_TOMBSTONES or metadata > 128 or unknown > 8:
                    print(
                        "Mailbox capacity exceeded; polling paused without mutations or lab teardown",
                        flush=True,
                    )
                    return
        for path in sorted(paths):
            try:
                info = path.lstat()
                fingerprint = (info.st_ino, info.st_mtime_ns, info.st_size)
                if self.seen.get(path.name) == fingerprint and (self.results / path.name).exists():
                    continue
                command = validateEnvelope(safeRead(path), path.name)
                if cancel_only and command["operation"] != "cancel":
                    continue
                self.handle(command)
                self.seen[path.name] = fingerprint
            except (OSError, ValueError, TypeError, KeyError) as error:
                # Malformed envelopes have no trustworthy result identity.
                print(
                    f"Mailbox rejected {path.name}: {type(error).__name__}: {str(error)[:160]}",
                    flush=True,
                )
