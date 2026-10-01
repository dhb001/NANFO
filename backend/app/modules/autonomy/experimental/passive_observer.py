"""Operator-only ADR023 tap of newly appended measured IPC evidence.

Run with the backend interpreter: PYTHONPATH=backend:. python -m
app.modules.autonomy.experimental.passive_observer --admission FILE --sha256 HASH
(``python -m emulation.passive_observer`` remains a host-only compatibility shim).
This process never connects to the experiment socket, generates traffic, or owns
device controls. ADR-028: moved out of the stdlib-only lab package; root-owned
``/proc/<pid>`` time-namespace identity is read only through the fixed-argument
helper ``PROC_TIMENS_HELPER`` (see backend/scripts/nanfo_proc_timens.py).
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import signal
import stat
import subprocess
import tempfile
import time
import uuid
from builtins import ExceptionGroup
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field

from app.core.canonical import canonical_sha256 as canonical_hash
from app.modules.autonomy.artifact_io import ArtifactStore, EvidenceError, parse_json
from app.modules.autonomy.live_schemas import PassiveSnapshot
from app.modules.autonomy.model_provider import FrozenModelProvider, confined_runtime
from app.modules.autonomy.registry import LiveRegistry, protected_path
from app.modules.autonomy.schemas import SHA256, Contract, Observation

MAX_LINE = 2 * 1024**2
# Root-installed fixed-argument helper; the only privileged read (NANFO_PASSIVE_PROC_SUDO=1).
PROC_TIMENS_HELPER = "/usr/local/libexec/nanfo-proc-timens"
# Exact sudoers entry (no wildcards; "" forbids every argument; the PID arrives on stdin):
SUDOERS_LINE = "nanfo-operator ALL=(root) NOPASSWD: " + PROC_TIMENS_HELPER + ' ""'


def privileged_proc_timens(pid):
    """Read another process's time namespace identity and offsets via the fixed helper."""
    if type(pid) is not int or pid < 1:
        raise EvidenceError("passive_server_pid_invalid")
    if os.environ.get("NANFO_PASSIVE_PROC_SUDO") != "1":
        raise PermissionError("passive_proc_privilege_not_enabled")
    result = subprocess.run(["sudo", "-n", PROC_TIMENS_HELPER], input=f"{pid}\n", check=True,
                            capture_output=True, text=True, timeout=2)
    value = json.loads(result.stdout)
    offsets = value.get("timens_offsets")
    if (set(value) != {"pid", "time_namespace", "timens_offsets"} or value["pid"] != pid
            or not isinstance(value["time_namespace"], str) or not isinstance(offsets, dict)
            or any(type(item) is not list or len(item) != 2 or any(type(n) is not int for n in item)
                   for item in offsets.values())):
        raise EvidenceError("passive_proc_helper_output_invalid")
    return value["time_namespace"], {name: tuple(item) for name, item in offsets.items()}


class Admission(Contract):
    version: Literal["nanfo.passive-feed-admission/v1"]
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    registry_sha256: SHA256
    feed_path: str = Field(min_length=1, max_length=512)
    session_sha256: SHA256
    # Host-visible PID of the admitted lab measurement server, NOT the log reader.
    server_pid: int = Field(strict=True, gt=0)
    server_start_ticks: int = Field(strict=True, gt=0)
    boot_id: uuid.UUID
    time_namespace: str = Field(pattern=r"^time:\[[0-9]+\]$")
    expires_at: AwareDatetime
    max_clock_drift_seconds: float = Field(gt=0, le=.25)
    max_delivery_seconds: float = Field(gt=0, le=10)
    authorization: Literal["observe-existing-measured-feed-only"]


@dataclass(frozen=True)
class ClockAnchor:
    monotonic: float
    wall: datetime

    @classmethod
    def capture(cls):
        before = time.monotonic()
        wall = datetime.now(timezone.utc)
        after = time.monotonic()
        if after - before > .05:
            raise EvidenceError("passive_clock_capture_delayed")
        return cls((before + after) / 2, wall)

    def at(self, monotonic):
        return self.wall + timedelta(seconds=monotonic - self.monotonic)


def process_identity(pid):
    # proc stat's comm may contain spaces/parentheses; fields after final ')' start
    # at field3. starttime is field22. Read-only identity; never signal the process.
    raw = Path(f"/proc/{pid}/stat").read_text()
    fields = raw[raw.rfind(")") + 2:].split()
    if fields[0] in ("Z", "X"):
        raise EvidenceError("passive_server_not_running")
    path = f"/proc/{pid}/ns/time"
    try:
        namespace = os.readlink(path)
    except PermissionError:
        if os.environ.get("NANFO_PASSIVE_PROC_SUDO") != "1":
            raise
        # Explicit operator-only read privilege for a root-owned lab server: a fixed
        # helper with no arguments (PID on stdin), no shell or device/control capability.
        namespace = privileged_proc_timens(int(pid))[0]
    return int(fields[19]), namespace


def load_admission(path, digest):
    path = Path(path)
    if not path.is_absolute():
        raise EvidenceError("passive_admission_path_not_absolute")
    protected_path(path)
    return Admission.model_validate(parse_json(ArtifactStore(str(path.parent)).read(
        path.name, sha256=digest, limit=64 * 1024)))


def check_authority(admission, anchor, now):
    if now.wall >= admission.expires_at:
        raise EvidenceError("passive_admission_expired")
    if abs((now.wall - anchor.at(now.monotonic)).total_seconds()) > admission.max_clock_drift_seconds:
        raise EvidenceError("passive_wall_clock_discontinuity")
    boot = uuid.UUID(Path("/proc/sys/kernel/random/boot_id").read_text().strip())
    start, namespace = process_identity(admission.server_pid)
    if (boot != admission.boot_id or start != admission.server_start_ticks
            or namespace != admission.time_namespace):
        raise EvidenceError("passive_clock_or_server_identity_changed")
    if namespace != os.readlink("/proc/self/ns/time"):
        # Docker may create a distinct time namespace with identical zero offsets.
        # Compare actual kernel offsets, never assume a namespace implies same clock.
        def offsets(pid):
            path = f"/proc/{pid}/timens_offsets"
            try:
                content = Path(path).read_text()
            except PermissionError:
                if os.environ.get("NANFO_PASSIVE_PROC_SUDO") != "1" or pid == "self":
                    raise
                return privileged_proc_timens(int(pid))[1]
            return {name: (int(seconds), int(nanos)) for name, seconds, nanos in
                    (line.split() for line in content.splitlines())}
        local, remote = offsets("self"), offsets(admission.server_pid)
        if not local or local != remote or set(local) != {"monotonic", "boottime"}:
            raise EvidenceError("passive_clock_namespace_offsets_differ")


class NewFrameFeed:
    """Single fixed protected append-only file; starts at EOF, never replays history."""

    def __init__(self, path):
        path = Path(path)
        if not path.is_absolute():
            raise EvidenceError("passive_feed_path_not_absolute")
        protected_path(path)
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(self.fd)
        if not stat.S_ISREG(info.st_mode):
            self.close()
            raise EvidenceError("passive_feed_not_regular")
        self.identity = info.st_dev, info.st_ino
        self.offset = info.st_size
        self.pending = bytearray()
        self.discard_partial = bool(info.st_size and os.pread(self.fd, 1, info.st_size - 1) != b"\n")
        os.lseek(self.fd, self.offset, os.SEEK_SET)

    def close(self):
        os.close(self.fd)

    def validate_session(self, digest):
        header = os.pread(self.fd, MAX_LINE + 1, 0).partition(b"\n")[0]
        if len(header) > MAX_LINE or hashlib.sha256(header).hexdigest() != digest:
            raise EvidenceError("passive_feed_session_hash_mismatch")
        session = parse_json(header)
        summary = session.get("summary", {})
        if (session.get("kind") != "session" or summary.get("kind") != "evaluation"
                or summary.get("mode") != "matched" or summary.get("generalization") is not False
                or summary.get("window_seconds") != 2.0 or summary.get("episode_steps") != 4):
            raise EvidenceError("passive_feed_requires_admitted_evaluation_not_training")

    def poll(self):
        protected_path(self.path)
        info = self.path.lstat()
        if ((info.st_dev, info.st_ino) != self.identity or info.st_size < self.offset
                or not stat.S_ISREG(info.st_mode)):
            raise EvidenceError("passive_feed_replaced_or_truncated")
        chunk = os.read(self.fd, 65536)
        self.offset += len(chunk)
        self.pending.extend(chunk)
        lines = []
        while b"\n" in self.pending:
            raw, _, rest = self.pending.partition(b"\n")
            self.pending = bytearray(rest)
            if len(raw) > MAX_LINE:
                raise EvidenceError("passive_feed_line_too_large")
            if self.discard_partial:
                self.discard_partial = False
                continue
            lines.append((bytes(raw), self.offset - len(self.pending)))
        if len(self.pending) > MAX_LINE:
            raise EvidenceError("passive_feed_line_too_large")
        return lines


def snapshot_from_frame(raw, admission, installation, anchor, received, last_end):
    """Preserve actual request/response; clocks derive solely from live attachment."""
    row = parse_json(raw)
    if not isinstance(row, dict) or row.get("kind") != "ipc":
        return None
    if set(row) != {"kind", "request", "response", "elapsed_seconds"}:
        raise EvidenceError("passive_feed_ipc_schema_invalid")
    request, response = row["request"], row["response"]
    if request.get("command") == "close":
        raise EvidenceError("passive_feed_closed")
    if response.get("ok") is not True or request.get("command") not in ("reset", "step"):
        raise EvidenceError("passive_feed_measurement_failed")
    data = response["data"]
    evidence = data["evidence"]
    manifest = installation.manifest
    if (evidence["environment_spec"] != manifest["environment_spec"]
            or evidence["provenance"] != manifest["lab_provenance"]
            or evidence["spec_hash"] != installation.model.spec_sha256
            or data["mode"] != "matched" or data["scenario"] not in ("path0", "path1")
            or request["window_seconds"] != 2.0 or request["episode_steps"] != 4):
        raise EvidenceError("passive_feed_model_incompatible")
    # A completed last-step frame describes policy already removed by the server.
    # It is valid historical evidence but not a current recommendation input.
    if data["terminated"] or data["truncated"] or evidence.get("cleanup_verified"):
        raise EvidenceError("passive_feed_terminal_or_cleanup_frame")
    start, end = (evidence["post_control_interval"][key] for key in ("start", "end"))
    completed = max(evidence["drain_end"],
                    *(item["finished_monotonic_seconds"] for item in evidence["udp_received"]),
                    *(item["after"]["monotonic_seconds"] for item in evidence["counter_windows"].values()))
    if (not anchor.monotonic <= start < end <= completed <= received.monotonic
            or end <= last_end or received.monotonic - completed > admission.max_delivery_seconds
            or received.monotonic - end > installation.model.max_observation_age_seconds):
        raise EvidenceError("passive_feed_stale_replayed_or_foreign_clock")
    if not 2 <= end - start <= 4.01:
        raise EvidenceError("passive_feed_window_invalid")
    history = {"version": 3, "frames": [{"request": request, "response": response}]}
    snapshot = PassiveSnapshot(version="nanfo.passive-measured-v4.v1",
        network_id=admission.network_id, workspace_id=admission.workspace_id,
        snapshot_id=uuid.uuid4(), run_id=data["episode_id"], observed_at=anchor.at(end),
        window_started_at=anchor.at(start), published_at=received.wall,
        source="operator-attested-measured-lab", contract_sha256=installation.model.contract_sha256,
        spec_sha256=installation.model.spec_sha256, history=history, history_sha256=canonical_hash(history))
    return snapshot, end


def atomic_publish(path, content):
    path = Path(path)
    protected_path(path.parent)
    if path.exists() or path.is_symlink():
        protected_path(path)
    fd, name = tempfile.mkstemp(prefix=".passive-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


async def validate_candidate(registry, installation, snapshot):
    """Original full validator/encoder/loader in confined AI process, before publish."""
    settings = registry.configuration()
    scope = next(s for s in installation.model.scopes if s.network_id == snapshot.network_id
                 and s.workspace_id == snapshot.workspace_id)
    with tempfile.TemporaryDirectory(prefix="nanfo-passive-validation-") as directory:
        target = Path(directory) / scope.snapshot_path
        if target.is_absolute() and not target.is_relative_to(Path(directory)):
            raise EvidenceError("passive_snapshot_path_invalid")
        if ".." in Path(scope.snapshot_path).parts:
            raise EvidenceError("passive_snapshot_path_invalid")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        content = snapshot.model_dump_json().encode()
        atomic_publish(target, content)
        temporary_registry = LiveRegistry(replace(settings, observation_root=directory))
        observation = Observation(network_id=snapshot.network_id, workspace_id=snapshot.workspace_id,
            provider_id="passive-feed", contract=snapshot.version, observed_at=snapshot.observed_at,
            collected_at=snapshot.published_at, age_seconds=0, fresh=True, compatible=True)
        result = await confined_runtime(temporary_registry, "infer", observation=observation,
                                        snapshot_hash=hashlib.sha256(content).hexdigest())
        FrozenModelProvider._validate_result(result, installation, "infer")
        if result.history_sha256 != snapshot.history_sha256:
            raise EvidenceError("passive_validated_history_mismatch")


async def observe_feed(admission_path, admission_hash, *, duration_seconds):
    if not 1 <= duration_seconds <= 3600:
        raise EvidenceError("passive_duration_invalid")
    admission = load_admission(admission_path, admission_hash)
    registry = LiveRegistry.from_environment()
    installation = await asyncio.to_thread(registry.load)
    if installation.sha256 != admission.registry_sha256:
        raise EvidenceError("passive_registry_admission_mismatch")
    scope = next((s for s in installation.model.scopes if s.network_id == admission.network_id
                  and s.workspace_id == admission.workspace_id), None)
    if scope is None:
        raise EvidenceError("passive_scope_unregistered")
    relative = Path(scope.snapshot_path)
    if relative.is_absolute() or ".." in relative.parts or relative.name in ("", "."):
        raise EvidenceError("passive_snapshot_path_invalid")
    target = Path(registry.configuration().observation_root) / relative
    protected_path(target.parent)
    lock_fd = os.open(target.with_suffix(target.suffix + ".producer.lock"),
                      os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    feed = None
    acquired = False
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        atomic_publish(target, b'{"version":"nanfo.passive-feed-unavailable/v1","reason":"awaiting_new_frame"}')
        feed = NewFrameFeed(admission.feed_path)
        feed.validate_session(admission.session_sha256)
        anchor = ClockAnchor.capture()
        check_authority(admission, anchor, anchor)
        atomic_publish(target.with_suffix(target.suffix + ".attached.json"), json.dumps({
            "admission_sha256": admission_hash, "feed_device": feed.identity[0],
            "feed_inode": feed.identity[1], "feed_offset": feed.offset,
            "anchor_monotonic": anchor.monotonic, "anchor_wall": anchor.wall.isoformat(),
        }).encode())
        deadline = anchor.monotonic + duration_seconds
        last_end = anchor.monotonic
        published = 0
        while time.monotonic() < deadline:
            received = ClockAnchor.capture()
            check_authority(admission, anchor, received)
            if load_admission(admission_path, admission_hash) != admission:
                raise EvidenceError("passive_admission_changed")
            feed.validate_session(admission.session_sha256)
            for raw, offset in feed.poll():
                received = ClockAnchor.capture()
                check_authority(admission, anchor, received)
                candidate = snapshot_from_frame(raw, admission, installation, anchor, received, last_end)
                if candidate is None:
                    continue
                snapshot, end = candidate
                if published >= 256:
                    raise EvidenceError("passive_publication_budget_exhausted")
                await validate_candidate(registry, installation, snapshot)
                now = ClockAnchor.capture()
                check_authority(admission, anchor, now)
                current = await asyncio.to_thread(registry.load)
                if current.sha256 != installation.sha256 or load_admission(admission_path, admission_hash) != admission:
                    raise EvidenceError("passive_installation_changed_during_validation")
                if now.monotonic >= deadline or (now.wall - snapshot.observed_at).total_seconds() > installation.model.max_observation_age_seconds:
                    raise EvidenceError("passive_frame_expired_during_validation")
                snapshot.published_at = now.wall
                content = snapshot.model_dump_json().encode()
                receipt = dict(version="nanfo.passive-feed-receipt/v1", admission_sha256=admission_hash,
                    registry_sha256=installation.sha256, snapshot_sha256=hashlib.sha256(content).hexdigest(),
                    history_sha256=snapshot.history_sha256, raw_line_sha256=hashlib.sha256(raw).hexdigest(),
                    feed_device=feed.identity[0], feed_inode=feed.identity[1], feed_end_offset=offset,
                    anchor_monotonic=anchor.monotonic, anchor_wall=anchor.wall.isoformat(),
                    received_monotonic=received.monotonic, received_wall=received.wall.isoformat(),
                    server_pid=admission.server_pid, server_start_ticks=admission.server_start_ticks,
                    boot_id=str(admission.boot_id), time_namespace=admission.time_namespace,
                    validation="original-frozen-measurement-and-inference", actuation=False)
                # Immutable receipt is written first. A crash leaves an orphan receipt,
                # never a snapshot claiming validation that has not completed.
                receipt_path = target.parent / ("receipt-" + str(snapshot.snapshot_id) + ".json")
                atomic_publish(receipt_path, json.dumps(receipt, allow_nan=False).encode())
                atomic_publish(target, content)
                last_end = end
                published += 1
            await asyncio.sleep(.1)
        return {"published": published, "actuation": False, "training": False}
    finally:
        try:
            if acquired:
                # Invalidate current recommendations on disconnect/cleanup/expiry/error.
                # This deliberately cannot parse as a PassiveSnapshot.
                atomic_publish(target, b'{"version":"nanfo.passive-feed-unavailable/v1","reason":"producer_stopped"}')
        finally:
            if feed is not None:
                feed.close()
            os.close(lock_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--duration-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    async def run():
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, task.cancel)
        try:
            return await observe_feed(args.admission, args.sha256,
                                      duration_seconds=args.duration_seconds)
        finally:
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(signum)
    try:
        print(json.dumps(asyncio.run(run())))
        return 0
    except asyncio.CancelledError:
        print('{"status":"passive_feed_stopped","actuation":false,"training":false}')
        return 130
    except (ValueError, OSError, KeyError, TypeError, TimeoutError, ExceptionGroup) as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, EvidenceError) else "passive_feed_rejected",
                          "actuation": False, "training": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
