"""Operator-owned ADR025 receiver. No inference imports and no second controller."""

import argparse
import contextlib
import fcntl
import hmac
import os
import re
import signal
import socket
import threading
import time
from pathlib import Path

try:
    from .experimental_lab_contract import (
        RESPONSE_LIMIT,
        VERSION,
        ProtectedReadError,
        Request,
        atomic_write,
        canonical,
        decode,
        digest,
        load_policy,
        protected_read,
        require,
        snapshot,
        wrapper_digest,
    )
    from .experimental_lab_runtime import GuardedRuntime, load_original
except ImportError:
    from experimental_lab_contract import (
        RESPONSE_LIMIT,
        VERSION,
        ProtectedReadError,
        Request,
        atomic_write,
        canonical,
        decode,
        digest,
        load_policy,
        protected_read,
        require,
        snapshot,
        wrapper_digest,
    )
    from experimental_lab_runtime import GuardedRuntime, load_original


class Receiver:
    def __init__(self, directory, policy_path, policy_hash, token_path, experiment):
        self.directory = Path(directory)
        self.policy_path, self.policy_hash = policy_path, policy_hash
        self.policy = load_policy(policy_path, policy_hash)
        require(self.policy["wrapper_sha256"] == wrapper_digest(), "wrapper_source_mismatch")
        self.token = protected_read(token_path).decode().strip()
        require(len(self.token) == 64, "invalid_receiver_token")
        self.lock = threading.RLock()
        self.lease_lock = threading.Lock()
        self.stop_lock = threading.Lock()
        self.stop_cause = None
        self.protected_read_failure = None
        self.lease_fence = 0
        self.shutdown = threading.Event()
        self.stopped = False
        self.fence = 0
        self.current = None
        self.receipts = {}
        self.active_until = None
        self.last_contact = time.monotonic()
        self.last_frame = None
        self.restoration = None
        self.binding = None
        self.bootstrap_request_id = None
        self.boundary_events = []
        self.abort = threading.Event()
        self.phase = "ready"
        self.journal_path = self.directory / "journal.json"
        self.runtime = GuardedRuntime(experiment, self.authority, self.persist, self.boundary,
                                      self.dispatch_authority)
        self.runtime.seed, self.runtime.scenario = self.policy["seed"], self.policy["scenario"]
        self.claim = os.open(str(self.directory / "receiver.lock"),
                             os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        fcntl.flock(self.claim, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if self.journal_path.exists():
            prior = decode(protected_read(self.journal_path, 16 * 1024 * 1024), 16 * 1024 * 1024)
            require(prior["policy_sha256"] == policy_hash, "journal_policy_mismatch")
            self.fence, self.receipts = prior["fence"], prior["receipts"]
            self.stopped = prior["stopped"]
            self.stop_cause = prior.get("stop_cause")
            self.protected_read_failure = prior.get("protected_read_failure")
            # Original Mininet object is not reconstructible after receiver death.
            # Never bind a fresh graph to an old journal and claim recovery.
            require(prior["phase"] in ("ready", "restored") and not prior["runtime"]["owned"],
                    "receiver_restart_requires_surviving_owner_or_operator_recovery")
        self.persist()

    def persist(self):
        for frame in self.runtime.frames:
            path = self.directory / ("frame-" + digest(frame) + ".json")
            if not path.exists():
                atomic_write(path, frame)
        atomic_write(self.journal_path, {"version": VERSION, "policy_sha256": self.policy_hash,
            "phase": self.phase, "fence": self.fence, "stopped": self.stopped,
            "stop_cause": self.stop_cause,
            "protected_read_failure": self.protected_read_failure,
            "current": None if self.current is None else self.current.public(),
            "active_until": self.active_until, "receipts": self.receipts,
            "runtime": self.runtime.state(), "restoration": self.restoration,
            "binding": self.binding, "boundary_events": self.boundary_events,
            "frames": self.runtime.frames})

    def boundary(self, when, entry):
        """One-shot protected operator fault handshake, under the sole writer lock."""
        path = self.directory / "failpoint.json"
        if not path.exists() or self.runtime.restoring:
            return
        point = decode(protected_read(path))
        require(set(point) == {"policy_sha256", "operation", "ordinal", "when", "effect", "timeout_seconds"}
                and point["policy_sha256"] == self.policy_hash
                and point["operation"] in ("bootstrap", "execute", "verify")
                and type(point["ordinal"]) is int and 1 <= point["ordinal"] <= 128
                and point["when"] in ("before", "after")
                and point["effect"] in ("pause", "raise", "stop")
                and type(point["timeout_seconds"]) in (int, float)
                and 0 < point["timeout_seconds"] <= 30, "invalid_failpoint")
        if self.current is None or self.current.operation != point["operation"]:
            return
        ordinal = self.runtime.calls["mutation_attempted"] - self.operation_start
        if point["ordinal"] != ordinal or when != point["when"]:
            return
        identity = digest(point)
        if any(event["id"] == identity for event in self.boundary_events):
            return
        event = {"id": identity, "point": point, "entry": dict(entry),
                 "reached_monotonic": time.monotonic(), "released_monotonic": None}
        self.boundary_events.append(event)
        self.persist()
        atomic_write(self.directory / "boundary.json", event)
        if point["effect"] == "stop":
            self.latch_stop("failpoint", identity)
        elif point["effect"] == "raise":
            raise RuntimeError("injected_partial_apply")
        else:
            deadline = time.monotonic() + point["timeout_seconds"]
            while True:
                self.authority()
                release = self.directory / "release.json"
                if release.exists():
                    value = decode(protected_read(release))
                    if value == {"boundary_sha256": identity, "release": True}:
                        break
                require(time.monotonic() < deadline, "boundary_pause_expired")
                self.abort.wait(.02)
        event["released_monotonic"] = time.monotonic()
        self.persist()

    def latch_stop(self, reason, request_id):
        with self.stop_lock:
            self.stopped = True
            self.abort.set()
            if self.stop_cause is None:
                self.stop_cause = {"request_id": request_id, "reason": reason,
                    "latched_monotonic": time.monotonic(), "latched_wall": time.time()}
                atomic_write(self.directory / "STOP", self.stop_cause)

    def authority(self):
        try:
            return self._authority()
        except ProtectedReadError as exc:
            with self.stop_lock:
                if self.protected_read_failure is None:
                    self.protected_read_failure = {**exc.diagnostic,
                        "observed_monotonic": time.monotonic(), "observed_wall": time.time()}
            raise

    def _authority(self):
        # A protected file is the receiver's current external authority lease.
        # Controller owning Identity must refresh it after checking current actor.
        require(not self.stopped and not (self.directory / "STOP").exists(), "stopped")
        require(load_policy(self.policy_path, self.policy_hash) == self.policy, "policy_changed")
        now = time.time()
        require(now < self.policy["expires_at"], "experiment_expired")
        if self.phase in ("ready", "bootstrapping", "bootstrapped", "bound"):
            admission = decode(protected_read(self.directory / "bootstrap-admission.json"))
            stop_present = (self.directory / "STOP").exists()
            now = time.time()
            require(not self.stopped and not self.abort.is_set() and not stop_present
                    and now < self.policy["expires_at"], "bootstrap_authority_changed_during_read")
            require(set(admission) == {"policy_sha256", "request_id", "expires_at", "authorized"}
                    and admission["policy_sha256"] == self.policy_hash
                    and admission["request_id"] == (self.bootstrap_request_id or self.current.request_id)
                    and admission["authorized"] is True
                    and now < admission["expires_at"] <= self.policy["expires_at"], "bootstrap_not_admitted")
            require(self.current is None or now < self.current.expires_at, "bootstrap_request_expired")
            require(self.active_until is None or now < self.active_until, "bootstrap_action_expired")
            return
        require(time.monotonic() - self.last_contact < self.policy["heartbeat_seconds"], "controller_disconnected")
        grant = decode(protected_read(self.directory / "authority.json"))
        stop_present = (self.directory / "STOP").exists()
        now = time.time()  # refresh after protected policy/lease I/O
        require(not self.stopped and not self.abort.is_set()
                and not stop_present and now < self.policy["expires_at"], "authority_changed_during_read")
        require(set(grant) == {"policy_sha256", "fence", "expires_at", "authorized"}
                and grant["policy_sha256"] == self.policy_hash and grant["authorized"] is True
                and type(grant["fence"]) is int and grant["fence"] >= self.fence
                and type(grant["expires_at"]) in (int, float)
                and now < grant["expires_at"] <= now + self.policy["heartbeat_seconds"],
                "current_actor_authority_unavailable")
        if self.current is not None:
            require(now < self.current.expires_at, "request_expired")
        if self.active_until is not None:
            require(now < self.active_until, "action_expired")
        if self.phase == "holding" and self.last_frame is not None:
            require(now - self.last_frame["completed_at"] <= self.policy["max_observation_age_seconds"],
                    "held_measurement_expired")

    def dispatch_authority(self, entry):
        """Sole writer's final add checkpoint; readers/watchdog never issue grants."""
        self.authority()

    def restore(self, reason):
        self.phase = "restoring"
        self.persist()
        try:
            self.restoration = {"reason": reason, **self.runtime.restore(
                timeout_seconds=self.policy["heartbeat_seconds"])}
            self.phase = "restored"
            self.active_until = None
            return self.restoration
        except Exception:
            self.phase = "recovery_required"
            raise
        finally:
            self.persist()

    def watchdog(self):
        while not self.shutdown.wait(.1):
            if self.active_until is None:
                continue
            try:
                self.authority()
            except (ValueError, OSError, RuntimeError) as exc:
                # STOP is immediate and is seen by the per-mutation wrapper even
                # while a measurement owns the work lock. Only owner does recovery.
                allowed = {"stopped", "experiment_expired", "controller_disconnected",
                    "current_actor_authority_unavailable", "authority_changed_during_read",
                    "request_expired", "action_expired", "held_measurement_expired",
                    "bootstrap_authority_changed_during_read", "bootstrap_not_admitted",
                    "bootstrap_request_expired", "bootstrap_action_expired", "policy_changed"}
                reason = ("protected_read_failed" if isinstance(exc, ProtectedReadError) else
                    str(exc) if isinstance(exc, ValueError) and str(exc) in allowed else "authority_unavailable")
                self.latch_stop("watchdog:" + reason, "receiver")
                with self.lock:
                    if self.active_until is not None:
                        with contextlib.suppress(Exception):
                            self.restore("watchdog_authority_or_expiry")

    def handle(self, raw):
        try:
            return snapshot(self._handle(raw))
        except ValueError:
            # An authenticated heartbeat denial is an operational outcome, not a
            # malformed unbound reply that masks the original measurement failure.
            req = Request.parse(raw)
            if (req.operation != "heartbeat" or not hmac.compare_digest(req.token, self.token)
                    or req.policy_sha256 != self.policy_hash):
                raise
            return snapshot({"version": VERSION, "request_id": req.request_id, "fence": req.fence,
                "policy_sha256": self.policy_hash, "status": "rejected",
                "evidence": {"reason": "heartbeat_denied", "stopped": self.stopped,
                             "protected_read_failure": self.protected_read_failure,
                             "stop_cause": self.stop_cause}})

    def _handle(self, raw):
        req = Request.parse(raw)
        require(hmac.compare_digest(req.token, self.token), "authentication_failed")
        require(req.policy_sha256 == self.policy_hash, "policy_mismatch")
        now = time.time()
        require(now < req.expires_at <= now + 120, "expired_or_unbounded_request")
        if req.operation == "status":
            return snapshot({"version": VERSION, "request_id": req.request_id, "fence": req.fence,
                    "policy_sha256": self.policy_hash, "status": "ok", "evidence": {
                         "current_fence": max(self.fence, self.lease_fence), "phase": self.phase,
                        "active_until": self.active_until, "restoration": self.restoration,
                         "binding": self.binding}})
        if req.operation == "heartbeat":
            with self.lease_lock:
                require(req.fence >= max(self.fence, self.lease_fence) and not self.stopped
                        and not (self.directory / "STOP").exists(), "heartbeat_denied")
                now = time.time()
                require(now < req.expires_at <= now + self.policy["heartbeat_seconds"], "heartbeat_too_long")
                atomic_write(self.directory / "authority.json", {
                    "policy_sha256": self.policy_hash, "fence": req.fence + 1,
                    "expires_at": req.expires_at, "authorized": True})
                self.lease_fence = req.fence
                self.last_contact = time.monotonic()
                if self.phase == "bound":
                    self.phase = "observed"
            return {"version": VERSION, "request_id": req.request_id, "fence": req.fence,
                    "policy_sha256": self.policy_hash, "status": "ok", "evidence": {"heartbeat": True}}
        if req.operation == "stop":
            # Independent ingress thread publishes STOP before waiting for owner.
            self.latch_stop("operator_or_controller", req.request_id)
            # Acknowledge latching promptly, not after a blocked measurement. The
            # sole writer unwinds and watchdog restores; recover reconciles completion.
            return {"version": VERSION, "request_id": req.request_id, "fence": req.fence,
                    "policy_sha256": self.policy_hash, "status": "ok",
                    "evidence": {"stop_latched": True, "restoration_pending": self.active_until is not None}}
        with self.lock:
            identity = digest(req.public())
            if req.request_id in self.receipts:
                old = self.receipts[req.request_id]
                require(old["request_sha256"] == identity, "request_id_reused")
                return snapshot(old["response"])
            require(req.fence > self.fence, "stale_fence")
            require(len(self.receipts) < 64, "request_budget_exhausted")
            self.fence, self.current = req.fence, req
            self.operation_start = self.runtime.calls["mutation_attempted"]
            self.last_contact = time.monotonic()
            self.receipts[req.request_id] = {"request_sha256": identity, "response": {
                "version": VERSION, "request_id": req.request_id, "fence": req.fence,
                "policy_sha256": self.policy_hash, "status": "uncertain", "evidence": {}}}
            self.persist()
            began = time.monotonic()
            frame_count = len(self.runtime.frames)
            try:
                evidence = self.operate(req)
                status = "ok"
            except Exception as exc:
                status, evidence = "rejected", {"reason": str(exc)[:160] if isinstance(exc, ValueError)
                                                else "receiver_operation_failed"}
                if len(self.runtime.frames) > frame_count:
                    evidence["failed_frame"] = snapshot(self.runtime.frames[-1])
                if self.runtime.baseline is not None and req.operation not in ("status",):
                    try:
                        evidence["restoration"] = self.restore("operation_failure")
                        if req.operation in ("restore", "recover"):
                            status = "ok"
                    except Exception:
                        status = "uncertain"
            response = {"version": VERSION, "request_id": req.request_id, "fence": req.fence,
                "policy_sha256": self.policy_hash, "status": status,
                "evidence": {**evidence, "phase": self.phase, "stopped": self.stopped,
                    "stop_cause": self.stop_cause,
                    "protected_read_failure": self.protected_read_failure,
                    "wrapper_sha256": wrapper_digest(), "action_paths": self.runtime.state(),
                    "duration_seconds": time.monotonic() - began}}
            self.receipts[req.request_id]["response"] = snapshot(response)
            self.current = None
            self.persist()
            return snapshot(self.receipts[req.request_id]["response"])

    def operate(self, req):
        if req.operation == "status":
            return {"active_until": self.active_until, "restoration": self.restoration}
        if req.operation in ("restore", "recover", "stop"):
            if self.phase == "restored":
                return {"restoration": self.restoration}
            if self.runtime.baseline is None:
                return {"no_owned_baseline": True}
            return {"restoration": self.restore(req.operation)}
        if req.operation == "bind":
            require(self.phase == "bootstrapped" and self.binding is None, "bind_requires_bootstrap")
            self.authority()
            binding = decode(protected_read(self.directory / "controller-binding.json"))
            require(set(binding) == {"receiver_policy_sha256", "controller_policy_sha256", "run_id", "baseline_sha256"}
                    and binding["receiver_policy_sha256"] == self.policy_hash
                    and binding["run_id"] == self.runtime.experiment.episode
                    and binding["baseline_sha256"] == digest(self.runtime.baseline)
                    and isinstance(binding["controller_policy_sha256"], str)
                    and re.fullmatch(r"[a-f0-9]{64}", binding["controller_policy_sha256"]),
                    "invalid_controller_binding")
            self.binding = binding
            self.phase = "bound"
            return {"binding": binding}
        self.authority()
        if req.operation == "bootstrap":
            require(self.phase == "ready" and self.runtime.experiment.episode is None,
                    "bootstrap_already_started")
            self.phase = "bootstrapping"
            self.bootstrap_request_id = req.request_id
            self.active_until = self.policy["expires_at"]
            self.runtime.capture_baseline()
            self.persist()
            result = self.runtime.frame()
            self.last_frame = result
            self.phase = "bootstrapped"
            return {**result, "episode_id": self.runtime.experiment.episode,
                    "baseline": self.runtime.baseline, "baseline_sha256": digest(self.runtime.baseline)}
        if req.operation == "observe":
            require(self.phase == "observed" and self.binding is not None, "bootstrap_binding_required")
            require(time.time() - self.last_frame["completed_at"] <= self.policy["max_observation_age_seconds"],
                    "bootstrap_frame_stale")
            return {**self.last_frame, "baseline": self.runtime.baseline, "binding": self.binding}
        if req.operation == "execute":
            require(self.phase == "observed", "execute_requires_fresh_baseline")
            require(time.time() - self.last_frame["completed_at"] <= self.policy["max_observation_age_seconds"],
                    "observation_stale")
            require(self.policy["min_dwell_seconds"] <= req.duration_seconds <= self.policy["max_duration_seconds"]
                    and req.duration_seconds > 0, "duration_not_admitted")
            self.phase = "executing"
            self.active_until = min(time.time() + req.duration_seconds, req.expires_at, self.policy["expires_at"])
            self.persist()
            result = self.runtime.frame(req.action)
            self.authority()
            require(self.runtime.thresholds(result, self.policy), "measured_verification_failed")
            self.phase = "holding"
            self.last_frame = result
            return {**result, "active_until": self.active_until}
        require(req.operation == "verify" and self.phase == "holding", "verify_requires_held_action")
        if self.runtime.experiment.index < 3:
            result = self.runtime.frame(self.runtime.routing.action)
        else:
            # Preserve measurement time; repeated hold checks never freshen a frame.
            result = {**self.last_frame, "readback": self.runtime.routing.readback()}
            require(time.time() - result["completed_at"] <= self.policy["max_observation_age_seconds"],
                    "hold_measurement_stale")
        self.authority()
        require(self.runtime.thresholds(result, self.policy), "hold_measurement_failed")
        self.last_frame = result
        return {**result, "active_until": self.active_until}


def serve(receiver, socket_path):
    require(Path(socket_path).parent == receiver.directory, "socket_outside_receiver_directory")
    watchdog = threading.Thread(target=receiver.watchdog, daemon=True)
    watchdog.start()
    slots = threading.BoundedSemaphore(4)

    def client(connection):
        try:
            with connection:
                connection.settimeout(50)
                raw = bytearray()
                while len(raw) <= 8192:
                    part = connection.recv(8193 - len(raw))
                    if not part:
                        break
                    raw.extend(part)
                try:
                    result = receiver.handle(bytes(raw))
                except (ValueError, OSError, TypeError, KeyError):
                    result = {"error": "request_rejected"}
                payload = canonical(result)
                require(len(payload) <= RESPONSE_LIMIT, "response_bound_exceeded")
                connection.sendall(payload)
        except (OSError, ValueError):
            # Receipt remains durable; lost connection triggers receiver recovery.
            receiver.latch_stop("response_transport_failed", "receiver")
        finally:
            slots.release()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(socket_path)
        os.chmod(socket_path, 0o600)
        server.listen(4)
        server.settimeout(.2)
        try:
            while not receiver.shutdown.is_set():
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                if not slots.acquire(blocking=False):
                    connection.close()
                    continue
                threading.Thread(target=client, args=(connection,), daemon=True).start()
        finally:
            receiver.stopped = True
            with receiver.lock:
                if receiver.runtime.baseline is not None:
                    receiver.restore("receiver_shutdown")
            Path(socket_path).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("directory", "policy", "policy-sha256", "token", "source-directory"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--static-probe", action="store_true")
    args = parser.parse_args(argv)
    os.umask(0o077)
    policy = load_policy(args.policy, args.policy_sha256)
    require(policy["wrapper_sha256"] == wrapper_digest(), "wrapper_source_mismatch")
    module = load_original(args.source_directory)
    if args.static_probe:
        print(canonical({"source_sha256": policy["source_sha256"], "wrapper_sha256": wrapper_digest(),
                         "spec_sha256": module.environmentSpec("matched")[1], "lab_started": False}).decode())
        return 0
    require(time.time() < policy["expires_at"], "policy_expired")
    directory = Path(args.directory)
    require(directory.is_absolute() and directory.is_dir(), "private_directory_required")
    # Lab launch itself requires separately protected parent admission, not inference.
    admission = decode(protected_read(directory / "campaign-admission.json"))
    require(admission == {"policy_sha256": args.policy_sha256, "admitted": True,
                          "container_id": policy["container_id"]}, "campaign_not_admitted")
    require(not (directory / "journal.json").exists(), "existing_receiver_journal_requires_operator_recovery")
    lab = module.OspfLab(directory)
    try:
        lab.start()
        receiver = Receiver(directory, args.policy, args.policy_sha256, args.token,
                            module.Experiment(lab, mode="matched"))
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: receiver.shutdown.set())
        serve(receiver, str(directory / "receiver.sock"))
    finally:
        lab.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
