"""Operator-owned ADR025 receiver. No inference imports and no second controller.

ADR-028 successor wrapper (new wrapper_sha256; fresh qualification before any claim):

* The controller lease lives only in memory under ``lease_lock``; ``authority.json`` is
  an audit copy that never grants authority.
* Only an authenticated state-changing request whose reply cannot be delivered may latch
  STOP; unauthenticated, idle, oversized or early-closing peers cannot.
* The connection boundary catches every Exception and answers a bounded error envelope;
  a request must arrive (half-closed) within REQUEST_READ_SECONDS.
* Failures persist exception class, a redacted message and traceback frame names, and
  are logged; nothing is silently suppressed.
* Operator failpoints are honoured only when started with ``--failpoints`` (fault
  campaigns); the journal records whether they were armed.
* An existing journal is never resumed: the original Mininet graph is not
  reconstructible after receiver death (operator recovery owns it).

The journal stays one atomically replaced ``journal.json`` rather than an append-only
JSONL WAL + snapshots: it is both the pre-mutation WAL and the exported evidence the
campaign verifier/auditor reads live and after the run, so a JSONL WAL would either
re-export the identical snapshot on every persist (no saving) or change that exported
artifact. It is bounded (<=64 receipts, <=MAX_FAILURES failures, one episode of frames).
"""

import argparse
import fcntl
import hmac
import logging
import os
import re
import signal
import socket
import threading
import time
import traceback
from pathlib import Path

try:
    from .experimental_lab_contract import (
        REQUEST_LIMIT,
        RESPONSE_LIMIT,
        STATE_CHANGING,
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
        REQUEST_LIMIT,
        RESPONSE_LIMIT,
        STATE_CHANGING,
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

LOG = logging.getLogger("nanfo.experimental_receiver")
MAX_CLIENTS = 4
REQUEST_READ_SECONDS = 2.0
OVERSIZE_DRAIN_BYTES = 64 * 1024
RESPONSE_SEND_SECONDS = 50
MAX_FAILURES = 128
BOOTSTRAP_PHASES = ("ready", "bootstrapping", "bootstrapped", "bound")
WATCHDOG_REASONS = frozenset({
    "stopped", "experiment_expired", "controller_disconnected", "current_actor_authority_unavailable",
    "authority_changed_during_read", "request_expired", "action_expired", "held_measurement_expired",
    "bootstrap_authority_changed_during_read", "bootstrap_not_admitted", "bootstrap_request_expired",
    "bootstrap_action_expired", "policy_changed"})
_HEX = re.compile(r"[0-9a-fA-F]{32,}")
_PATH = re.compile(r"(?:/[^\s/'\":,]+){2,}")


def redact(value, limit=160):
    """Bounded single-line message without long hex identifiers/tokens or file paths."""
    text = " ".join(str(value).split())
    return _PATH.sub("<path>", _HEX.sub("<hex>", text))[:limit]


def failure_record(context, exc):
    return {"context": context, "exception": type(exc).__name__, "message": redact(exc),
            "frames": [frame.name for frame in traceback.extract_tb(exc.__traceback__)][-16:],
            "observed_monotonic": time.monotonic(), "observed_wall": time.time()}


class Receiver:
    def __init__(self, directory, policy_path, policy_hash, token_path, experiment, *, failpoints=False):
        self.directory = Path(directory)
        self.policy_path, self.policy_hash = policy_path, policy_hash
        self.policy = load_policy(policy_path, policy_hash)
        require(self.policy["wrapper_sha256"] == wrapper_digest(), "wrapper_source_mismatch")
        self.token = protected_read(token_path).decode().strip()
        require(len(self.token) == 64, "invalid_receiver_token")
        self.failpoints = bool(failpoints)
        self.lock = threading.RLock()
        self.lease_lock = threading.Lock()
        self.stop_lock = threading.Lock()
        self.stop_cause = None
        self.protected_read_failure = None
        self.lease = None
        self.lease_fence = 0
        self.failures = []
        self.failures_dropped = 0
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
        # Never bind a fresh graph to an old journal and claim recovery.
        require(not self.journal_path.exists() and not self.journal_path.is_symlink(),
                "existing_receiver_journal_requires_operator_recovery")
        self.persist()
        LOG.info("receiver ready policy=%s failpoints=%s", policy_hash[:12], self.failpoints)

    def journal(self):
        with self.lease_lock:
            lease = None if self.lease is None else dict(self.lease)
        return {"version": VERSION, "policy_sha256": self.policy_hash,
            "phase": self.phase, "fence": self.fence, "stopped": self.stopped,
            "stop_cause": self.stop_cause,
            "protected_read_failure": self.protected_read_failure,
            "current": None if self.current is None else self.current.public(),
            "active_until": self.active_until, "receipts": self.receipts,
            "runtime": self.runtime.state(), "restoration": self.restoration,
            "binding": self.binding, "boundary_events": self.boundary_events,
            "frames": self.runtime.frames, "lease": lease, "failures": list(self.failures),
            "failures_dropped": self.failures_dropped, "failpoints_enabled": self.failpoints}

    def persist(self):
        for frame in self.runtime.frames:
            path = self.directory / ("frame-" + digest(frame) + ".json")
            if not path.exists():
                atomic_write(path, frame)
        atomic_write(self.journal_path, self.journal())

    def record_failure(self, context, exc):
        """Durable-on-next-persist, bounded, redacted failure evidence; always logged."""
        record = failure_record(context, exc)
        failures = self.__dict__.setdefault("failures", [])
        if len(failures) < MAX_FAILURES:
            failures.append(record)
        else:
            self.failures_dropped = getattr(self, "failures_dropped", 0) + 1
        LOG.error("receiver failure context=%s exception=%s message=%s frames=%s",
                  context, record["exception"], record["message"], ",".join(record["frames"]))
        return record

    def boundary(self, when, entry):
        """One-shot protected operator fault handshake, under the sole writer lock.

        Honoured only for fault campaigns started with --failpoints; never otherwise.
        """
        if not self.failpoints or self.runtime.restoring:
            return
        path = self.directory / "failpoint.json"
        if not path.exists():
            return
        point = self.failpoint(path)
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
        LOG.warning("failpoint reached operation=%s ordinal=%s effect=%s",
                    point["operation"], point["ordinal"], point["effect"])
        if point["effect"] == "stop":
            self.latch_stop("failpoint", identity)
        elif point["effect"] == "raise":
            raise RuntimeError("injected_partial_apply")
        else:
            self.pause_at_boundary(identity, point["timeout_seconds"])
        event["released_monotonic"] = time.monotonic()
        self.persist()

    def failpoint(self, path):
        point = decode(protected_read(path))
        require(set(point) == {"policy_sha256", "operation", "ordinal", "when", "effect", "timeout_seconds"}
                and point["policy_sha256"] == self.policy_hash
                and point["operation"] in ("bootstrap", "execute", "verify")
                and type(point["ordinal"]) is int and 1 <= point["ordinal"] <= 128
                and point["when"] in ("before", "after")
                and point["effect"] in ("pause", "raise", "stop")
                and type(point["timeout_seconds"]) in (int, float)
                and 0 < point["timeout_seconds"] <= 30, "invalid_failpoint")
        return point

    def pause_at_boundary(self, identity, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        while True:
            self.authority()
            release = self.directory / "release.json"
            if release.exists():
                value = decode(protected_read(release))
                if value == {"boundary_sha256": identity, "release": True}:
                    return
            require(time.monotonic() < deadline, "boundary_pause_expired")
            self.abort.wait(.02)

    def latch_stop(self, reason, request_id):
        with self.stop_lock:
            self.stopped = True
            self.abort.set()
            if self.stop_cause is None:
                self.stop_cause = {"request_id": request_id, "reason": reason,
                    "latched_monotonic": time.monotonic(), "latched_wall": time.time()}
                atomic_write(self.directory / "STOP", self.stop_cause)
                LOG.warning("STOP latched reason=%s request=%s", reason, request_id)

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
        require(not self.stopped and not (self.directory / "STOP").exists(), "stopped")
        require(load_policy(self.policy_path, self.policy_hash) == self.policy, "policy_changed")
        now = time.time()
        require(now < self.policy["expires_at"], "experiment_expired")
        if self.phase in BOOTSTRAP_PHASES:
            return self._bootstrap_authority()
        require(time.monotonic() - self.last_contact < self.policy["heartbeat_seconds"], "controller_disconnected")
        # The current controller lease is in-memory state granted by an authenticated
        # heartbeat under lease_lock; no file can grant or extend it.
        with self.lease_lock:
            grant = None if self.lease is None else dict(self.lease)
        stop_present = (self.directory / "STOP").exists()
        now = time.time()  # refresh after protected policy I/O
        require(not self.stopped and not self.abort.is_set()
                and not stop_present and now < self.policy["expires_at"], "authority_changed_during_read")
        require(grant is not None and grant["policy_sha256"] == self.policy_hash and grant["authorized"] is True
                and grant["fence"] >= self.fence
                and now < grant["expires_at"] <= now + self.policy["heartbeat_seconds"],
                "current_actor_authority_unavailable")
        if self.current is not None:
            require(now < self.current.expires_at, "request_expired")
        if self.active_until is not None:
            require(now < self.active_until, "action_expired")
        if self.phase == "holding" and self.last_frame is not None:
            require(now - self.last_frame["completed_at"] <= self.policy["max_observation_age_seconds"],
                    "held_measurement_expired")

    def _bootstrap_authority(self):
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
            LOG.info("original forwarding restored reason=%s", reason)
            return self.restoration
        except Exception:
            self.phase = "recovery_required"
            raise
        finally:
            self.persist()

    @staticmethod
    def watchdog_reason(exc):
        if isinstance(exc, ProtectedReadError):
            return "protected_read_failed"
        if isinstance(exc, ValueError) and str(exc) in WATCHDOG_REASONS:
            return str(exc)
        return "authority_unavailable"

    def watchdog(self):
        while not self.shutdown.wait(.1):
            if self.active_until is None:
                continue
            try:
                self.authority()
            except Exception as exc:
                # STOP is immediate and is seen by the per-mutation wrapper even
                # while a measurement owns the work lock. Only owner does recovery.
                self.latch_stop("watchdog:" + self.watchdog_reason(exc), "receiver")
                with self.lock:
                    if self.active_until is not None:
                        try:
                            self.restore("watchdog_authority_or_expiry")
                        except Exception as failure:
                            self.record_failure("watchdog_restore", failure)

    def transport_failure_latches(self, raw):
        """Only an authenticated state-changing request may latch STOP on a lost reply."""
        try:
            req = Request.parse(raw)
        except Exception:
            return False
        return (hmac.compare_digest(req.token, self.token) and req.policy_sha256 == self.policy_hash
                and req.operation in STATE_CHANGING)

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

    def reply(self, req, status, evidence):
        return {"version": VERSION, "request_id": req.request_id, "fence": req.fence,
                "policy_sha256": self.policy_hash, "status": status, "evidence": evidence}

    def _handle(self, raw):
        req = Request.parse(raw)
        require(hmac.compare_digest(req.token, self.token), "authentication_failed")
        require(req.policy_sha256 == self.policy_hash, "policy_mismatch")
        now = time.time()
        require(now < req.expires_at <= now + 120, "expired_or_unbounded_request")
        if req.operation == "status":
            return snapshot(self.reply(req, "ok", {
                "current_fence": max(self.fence, self.lease_fence), "phase": self.phase,
                "active_until": self.active_until, "restoration": self.restoration,
                "binding": self.binding}))
        if req.operation == "heartbeat":
            return self.heartbeat(req)
        if req.operation == "stop":
            # Independent ingress thread publishes STOP before waiting for owner.
            self.latch_stop("operator_or_controller", req.request_id)
            # Acknowledge latching promptly, not after a blocked measurement. The
            # sole writer unwinds and watchdog restores; recover reconciles completion.
            return self.reply(req, "ok", {"stop_latched": True,
                                          "restoration_pending": self.active_until is not None})
        with self.lock:
            return self.owned_operation(req)

    def heartbeat(self, req):
        with self.lease_lock:
            require(req.fence >= max(self.fence, self.lease_fence) and not self.stopped
                    and not (self.directory / "STOP").exists(), "heartbeat_denied")
            now = time.time()
            require(now < req.expires_at <= now + self.policy["heartbeat_seconds"], "heartbeat_too_long")
            self.lease = {"policy_sha256": self.policy_hash, "fence": req.fence + 1,
                          "expires_at": req.expires_at, "authorized": True}
            # Audit copy only: _authority() never reads it back.
            atomic_write(self.directory / "authority.json", {**self.lease, "audit_only": True})
            self.lease_fence = req.fence
            self.last_contact = time.monotonic()
            if self.phase == "bound":
                self.phase = "observed"
        return self.reply(req, "ok", {"heartbeat": True})

    def owned_operation(self, req):
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
        self.receipts[req.request_id] = {"request_sha256": identity,
                                         "response": self.reply(req, "uncertain", {})}
        self.persist()
        LOG.info("operation accepted operation=%s request=%s fence=%s", req.operation, req.request_id, req.fence)
        began = time.monotonic()
        frame_count = len(self.runtime.frames)
        try:
            evidence = self.operate(req)
            status = "ok"
        except Exception as exc:
            status, evidence = self.failed_operation(req, exc, frame_count)
        response = self.reply(req, status, {**evidence, "phase": self.phase, "stopped": self.stopped,
            "stop_cause": self.stop_cause, "protected_read_failure": self.protected_read_failure,
            "wrapper_sha256": wrapper_digest(), "action_paths": self.runtime.state(),
            "duration_seconds": time.monotonic() - began})
        self.receipts[req.request_id]["response"] = snapshot(response)
        self.current = None
        self.persist()
        LOG.info("operation finished operation=%s request=%s status=%s", req.operation, req.request_id, status)
        return snapshot(self.receipts[req.request_id]["response"])

    def failed_operation(self, req, exc, frame_count):
        failure = self.record_failure(req.operation, exc)
        status = "rejected"
        evidence = {"reason": redact(exc) if isinstance(exc, ValueError) else "receiver_operation_failed",
                    "failure": failure}
        if len(self.runtime.frames) > frame_count:
            evidence["failed_frame"] = snapshot(self.runtime.frames[-1])
        if self.runtime.baseline is not None and req.operation != "status":
            try:
                evidence["restoration"] = self.restore("operation_failure")
                if req.operation in ("restore", "recover"):
                    status = "ok"
            except Exception as restore_failure:
                evidence["restoration_failure"] = self.record_failure(
                    "restore_after_" + req.operation, restore_failure)
                status = "uncertain"
        return status, evidence

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
            return self.bind()
        self.authority()
        if req.operation == "bootstrap":
            return self.bootstrap(req)
        if req.operation == "observe":
            require(self.phase == "observed" and self.binding is not None, "bootstrap_binding_required")
            require(time.time() - self.last_frame["completed_at"] <= self.policy["max_observation_age_seconds"],
                    "bootstrap_frame_stale")
            return {**self.last_frame, "baseline": self.runtime.baseline, "binding": self.binding}
        if req.operation == "execute":
            return self.execute(req)
        return self.verify(req)

    def bind(self):
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

    def bootstrap(self, req):
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

    def execute(self, req):
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

    def verify(self, req):
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


def read_request(connection, seconds=None):
    """Bounded request read with a total deadline; idle peers release their slot.

    An oversized request keeps only REQUEST_LIMIT+1 bytes; up to OVERSIZE_DRAIN_BYTES
    more are discarded so the peer can still receive its bounded rejection.
    """
    deadline = time.monotonic() + (REQUEST_READ_SECONDS if seconds is None else seconds)
    raw, drained = bytearray(), 0

    def receive(size):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise socket.timeout("request_read_deadline")
        connection.settimeout(remaining)
        return connection.recv(size)

    while len(raw) <= REQUEST_LIMIT:
        part = receive(REQUEST_LIMIT + 1 - len(raw))
        if not part:
            return bytes(raw)
        raw.extend(part)
    while drained < OVERSIZE_DRAIN_BYTES:
        part = receive(min(65536, OVERSIZE_DRAIN_BYTES - drained))
        if not part:
            break
        drained += len(part)
    return bytes(raw)


def serve_client(receiver, connection, slots):
    latches = False
    try:
        with connection:
            raw = read_request(connection)
            latches = receiver.transport_failure_latches(raw)
            try:
                result = receiver.handle(raw)
                payload = canonical(result)
                require(len(payload) <= RESPONSE_LIMIT, "response_bound_exceeded")
            except Exception as exc:
                LOG.warning("request rejected exception=%s reason=%s", type(exc).__name__, redact(exc))
                payload = canonical({"error": "request_rejected"})
            connection.settimeout(RESPONSE_SEND_SECONDS)
            connection.sendall(payload)
    except Exception as exc:
        LOG.warning("receiver transport failure exception=%s reason=%s authenticated_state_change=%s",
                    type(exc).__name__, redact(exc), latches)
        if latches:
            # Receipt remains durable; a lost state-changing reply triggers recovery.
            receiver.latch_stop("response_transport_failed", "receiver")
    finally:
        slots.release()


def serve(receiver, socket_path):
    require(Path(socket_path).parent == receiver.directory, "socket_outside_receiver_directory")
    watchdog = threading.Thread(target=receiver.watchdog, daemon=True)
    watchdog.start()
    slots = threading.BoundedSemaphore(MAX_CLIENTS)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(socket_path)
        os.chmod(socket_path, 0o600)
        server.listen(MAX_CLIENTS)
        server.settimeout(.2)
        try:
            while not receiver.shutdown.is_set():
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                if not slots.acquire(blocking=False):
                    LOG.warning("receiver connection refused: all %s slots busy", MAX_CLIENTS)
                    connection.close()
                    continue
                threading.Thread(target=serve_client, args=(receiver, connection, slots), daemon=True).start()
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
    parser.add_argument("--failpoints", action="store_true",
                        help="fault campaigns only: honour protected failpoint.json handshakes")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
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
                            module.Experiment(lab, mode="matched"), failpoints=args.failpoints)
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: receiver.shutdown.set())
        serve(receiver, str(directory / "receiver.sock"))
    finally:
        lab.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
