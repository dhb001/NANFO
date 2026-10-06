"""ADR-010 typed plan and operator mailbox boundary. No switch protocol code."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import stat
import time
import uuid
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.modules.identity.service import AuthService
from app.modules.network.emulation import load_binding
from app.modules.network.service import NetworkService
from app.modules.telemetry.emulation import (
    SnapshotReader,
    StrictSchema,
    UTCTime,
    read_bounded_file,
    reject_duplicate_keys,
    validate_json,
)

HostName = Literal["h1", "h2", "h3", "h4"]
SwitchName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]{0,31}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Operation = Literal["reroute", "multipath", "shape", "police", "restore"]


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class LabPlan(StrictSchema):
    operation: Operation
    source_host: HostName
    destination_host: HostName
    paths: Annotated[list[Annotated[list[SwitchName], Field(min_length=1, max_length=64)]], Field(max_length=2)]
    weights: Annotated[list[Annotated[int, Field(gt=0, le=65535)]], Field(max_length=2)]
    rate_mbps: Annotated[float, Field(gt=0, le=1e9, allow_inf_nan=False)] | None
    dscp: Annotated[int, Field(ge=0, le=63)] | None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.source_host == self.destination_host:
            raise ValueError("distinct source and destination required")
        count = 2 if self.operation == "multipath" else 1 if self.operation == "reroute" else 0
        if len(self.paths) != count or len(self.weights) != count:
            raise ValueError("operation requires complete paths and matching weights")
        if any(len(set(path)) != len(path) for path in self.paths):
            raise ValueError("paths must be simple")
        if count == 2 and self.paths[0] == self.paths[1]:
            raise ValueError("multipath requires distinct paths")
        if count == 2 and set(self.paths[0][1:-1]) & set(self.paths[1][1:-1]):
            raise ValueError("multipath requires internally disjoint paths")
        if (self.operation in {"shape", "police"}) != (self.rate_mbps is not None):
            raise ValueError("rate required only for shape/police")
        if self.rate_mbps is not None and not 1 <= self.rate_mbps <= 20:
            raise ValueError("lab QoS supports 1..20 Mbps")
        if self.operation != "multipath" and any(weight != 1 for weight in self.weights):
            raise ValueError("weights supported only for multipath")
        return self


class LabScope(StrictSchema):
    source_host: HostName
    destination_host: HostName


class LabConstraints(StrictSchema):
    operation: Operation | None = None
    paths: Annotated[list[Annotated[list[SwitchName], Field(min_length=1, max_length=64)]], Field(max_length=2)] = Field(default_factory=list)
    weights: Annotated[list[Annotated[int, Field(gt=0, le=65535)]], Field(max_length=2)] | None = None
    rate_mbps: Annotated[float, Field(gt=0, le=1e9, allow_inf_nan=False)] | None = None
    dscp: Annotated[int, Field(ge=0, le=63)] | None = None


class LabIntent(StrictSchema):
    action: Literal["reroute_path", "throttle_qos"]
    scope: LabScope
    constraints: LabConstraints

    def normalize(self) -> LabPlan:
        operation = self.constraints.operation or ("reroute" if self.action == "reroute_path" else "shape")
        allowed = {"reroute", "multipath", "restore"} if self.action == "reroute_path" else {"shape", "police", "restore"}
        if operation not in allowed:
            raise ValueError("action and operation mismatch")
        values = self.constraints.model_dump()
        values.update(operation=operation, **self.scope.model_dump())
        if values["weights"] is None:
            values["weights"] = [1] * len(values["paths"])
        return LabPlan.model_validate(values)


class PendingLabCommand(StrictSchema):
    """Accepted plan metadata; not a publishable lab authorization."""
    version: Literal[1]
    execution_id: uuid.UUID
    run_id: uuid.UUID
    binding_digest: Digest
    plan_hash: Digest
    fence: Annotated[int, Field(gt=0)]
    deadline: UTCTime
    operation: Literal["execute", "cancel"]
    plan: LabPlan

    @model_validator(mode="after")
    def hash_matches(self) -> Self:
        if digest(self.plan.model_dump(mode="json")) != self.plan_hash:
            raise ValueError("plan hash mismatch")
        return self


class LabCommand(PendingLabCommand):
    dispatch_expires_at: UTCTime

    @model_validator(mode="after")
    def bounded_dispatch(self) -> Self:
        if self.dispatch_expires_at > self.deadline:
            raise ValueError("dispatch authorization cannot exceed action deadline")
        return self

    def assert_new_dispatch(self, now: datetime) -> None:
        """Receiver contract: check only before preparing a NEW journal action."""
        remaining = (self.dispatch_expires_at - now).total_seconds()
        if not 0 < remaining <= 5 or now >= self.deadline:
            raise ValueError("new dispatch authorization expired or exceeds five seconds")


class LabResult(StrictSchema):
    version: Literal[1]
    execution_id: uuid.UUID
    run_id: uuid.UUID
    binding_digest: Digest
    plan_hash: Digest
    fence: Annotated[int, Field(gt=0)]
    status: Literal["completed", "failed", "cancelled", "uncertain"]
    verification: dict
    rollback: dict | None
    failure_reason: Annotated[str, Field(max_length=4096)] | None
    completed_at: UTCTime

    def matches(self, command: LabCommand) -> bool:
        return all(getattr(self, key) == getattr(command, key) for key in (
            "version", "execution_id", "run_id", "binding_digest", "plan_hash", "fence",
        ))


async def prepare_plan(*, settings, db, redis, workspace_id, network_id, actor_id, payload):
    """Revalidate current durable authority and trusted observations, not session claims."""
    if settings.EXECUTION_MODE != "emulation" or not settings.EMULATION_CONTROL_ENABLED:
        raise ValueError("emulation control disabled")
    if not all((settings.EMULATION_BINDING_PATH, settings.EMULATION_SNAPSHOT_PATH,
                settings.EMULATION_COMMANDS_PATH, settings.EMULATION_RESULTS_PATH)):
        raise ValueError("operator paths required")
    # Only this checked-in pure-data manifest is trusted, never a request-supplied file.
    from emulation.topology import manifest

    expected = manifest()
    binding = await load_binding(Path(settings.EMULATION_BINDING_PATH), snapshot_path=Path(settings.EMULATION_SNAPSHOT_PATH))
    if binding.workspace_id != workspace_id or binding.network_id != network_id:
        raise ValueError("binding scope mismatch")
    if (binding.topology_id != expected["topology_id"]
            or set(binding.switches) != {s["dpid"] for s in expected["switches"]}
            or set(binding.hosts) != {h["name"] for h in expected["hosts"]}
            or binding.port_capacities_mbps != expected["port_capacities_mbps"]):
        raise ValueError("binding differs from trusted manifest")
    for actor in {str(actor_id), str(binding.actor_user_id)}:
        profile = await AuthService(db, redis).get_profile(actor)
        if not {"write:config", "execute:rollback"}.issubset(profile.permissions):
            raise ValueError("actor lacks current execution capabilities")
        await NetworkService(db, redis).assert_network_workspace_access(
            network_id=network_id, requested_workspace_id=workspace_id, actor_user_id=actor, require_write=True,
        )
    for device_id in (*binding.switches.values(), *binding.hosts.values()):
        device_network, device_workspace = await NetworkService(db, redis).assert_device_workspace_access(
            device_id=device_id, requested_workspace_id=workspace_id, actor_user_id=str(binding.actor_user_id),
        )
        if device_network != network_id or device_workspace != workspace_id:
            raise ValueError("binding inventory scope mismatch")
    reader = SnapshotReader(Path(settings.EMULATION_SNAPSHOT_PATH), max_bytes=settings.EMULATION_SNAPSHOT_MAX_BYTES,
                            max_age_seconds=settings.EMULATION_SNAPSHOT_MAX_AGE_SECONDS,
                            future_skew_seconds=settings.EMULATION_SNAPSHOT_FUTURE_SKEW_SECONDS)
    snapshot = await reader.read()
    plan = LabIntent.model_validate(payload).normalize()
    switches = {s["name"]: s for s in expected["switches"]}
    hosts = {h["name"]: h for h in expected["hosts"]}
    if (snapshot.topology_id != binding.topology_id
            or {s.name: s.dpid for s in snapshot.switches} != {s["name"]: s["dpid"] for s in expected["switches"]}
            or {h.name: h.model_dump(mode="json") for h in snapshot.hosts} != hosts):
        raise ValueError("snapshot identity differs from trusted manifest")
    trusted_links = set()
    capacities = []
    for link in expected["links"]:
        (a, ap), (b, bp) = link["a"], link["b"]
        if a in switches and b in switches:
            trusted_links.add((switches[a]["dpid"], ap, switches[b]["dpid"], bp))
            trusted_links.add((switches[b]["dpid"], bp, switches[a]["dpid"], ap))
    observed = {(link.src_dpid, link.src_port, link.dst_dpid, link.dst_port) for link in snapshot.links}
    if not observed.issubset(trusted_links):
        raise ValueError("untrusted observed link")
    source, destination = hosts[plan.source_host], hosts[plan.destination_host]
    for path in plan.paths:
        if any(node not in switches for node in path):
            raise ValueError("unknown path switch")
        if (switches[path[0]]["dpid"] != source["dpid"] or switches[path[-1]]["dpid"] != destination["dpid"]
                or switches[path[0]]["role"] != "access" or switches[path[-1]]["role"] != "access"
                or any(switches[node]["role"] not in {"distribution", "core"} for node in path[1:-1])):
            raise ValueError("path endpoints or roles invalid")
        for a, b in pairwise(path):
            links = [link for link in observed if link[0] == switches[a]["dpid"] and link[2] == switches[b]["dpid"]
                     and (link[2], link[3], link[0], link[1]) in observed]
            if len(links) != 1:
                raise ValueError("path requires unambiguous bidirectional observed links")
            src, port, dst, peer_port = links[0]
            capacities.extend((binding.port_capacities_mbps[f"{src}:{port}"],
                               binding.port_capacities_mbps[f"{dst}:{peer_port}"]))
    capacities.extend(binding.port_capacities_mbps[f"{h['dpid']}:{h['port_no']}"] for h in (source, destination))
    if plan.operation in {"shape", "police"}:
        # QoS follows baseline forwarding rather than a supplied path; bound by
        # every trusted fabric link and require the complete bidirectional graph.
        if observed != trusted_links:
            raise ValueError("QoS requires complete observed fabric")
        capacities.extend(binding.port_capacities_mbps.values())
    if plan.rate_mbps is not None and plan.rate_mbps > min(capacities):
        raise ValueError("rate exceeds trusted path capacity")
    # ADR-010's bounded driver discovers SELECT/meter/queue support before any
    # mutation; schema validation does not claim those device features are present.
    return plan, binding, snapshot


class Mailbox:
    def __init__(self, settings):
        self.commands = Path(settings.EMULATION_COMMANDS_PATH)
        self.results = Path(settings.EMULATION_RESULTS_PATH)
        self.max_bytes = settings.EMULATION_CONTROL_MAX_BYTES
        paths = [self.commands, self.results, Path(settings.EMULATION_SNAPSHOT_PATH).parent,
                 Path(settings.EMULATION_BINDING_PATH).parent]
        if any(not path.is_absolute() for path in paths):
            raise ValueError("operator paths must be absolute")
        for index, path in enumerate(paths[:2]):
            if any(path == other or path.is_relative_to(other) or other.is_relative_to(path)
                   for other in paths[index + 1:]):
                raise ValueError("mailboxes must be separate from telemetry and binding")

    @staticmethod
    def open_directory(path: Path) -> int:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in path.parts[1:]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    def write(self, command: LabCommand, *, can_publish=lambda: True) -> None:
        if not isinstance(command, LabCommand):
            raise TypeError("pending plan is not a dispatch authorization")
        # Lab-only contract, imported on use so importing the API never loads the emulation package.
        from emulation.lab_contracts import canonical as canonical_envelope
        from emulation.lab_contracts import load_command_key, sign_command, verify_command

        # ADR-028 C15: HMAC-SHA256 over the canonical envelope; no protected key, no publication.
        key = load_command_key()
        data = canonical_envelope(sign_command(key, command.model_dump(mode="json")))
        if len(data) > self.max_bytes:
            raise ValueError("command too large")
        directory = self.open_directory(self.commands)
        name = f"{command.execution_id}.json"
        temporary = f".{uuid.uuid4()}.tmp"
        lock = None
        try:
            # Never unlink this inode: every process must serialize the complete
            # check/replace on the same lock, including delayed to_thread calls.
            lock = os.open(f".{command.execution_id}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                           0o600, dir_fd=directory)
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("mailbox lock must be a single-link regular file")
            while True:
                if not can_publish():
                    raise ValueError("mailbox publication authority expired")
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(.01)
            try:
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("command must be a regular file")
                raw = read_bounded_file(self.commands / name, self.max_bytes)
                envelope = verify_command(key, json.loads(raw, object_pairs_hook=reject_duplicate_keys))
                existing = validate_json(LabCommand, canonical_envelope(envelope))
                previous, proposed = existing.model_dump(mode="json"), command.model_dump(mode="json")
                previous.pop("operation")
                proposed.pop("operation")
                if previous != proposed:
                    raise ValueError("command identity is immutable")
                if existing.operation == "cancel" and command.operation == "execute":
                    raise ValueError("cancellation cannot revert to execute")
            except FileNotFoundError:
                pass
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if not can_publish():
                raise ValueError("mailbox publication authority expired")
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            if lock is not None:
                os.close(lock)
            os.close(directory)

    async def read(self, execution_id: uuid.UUID) -> LabResult | None:
        try:
            data = await asyncio.to_thread(read_bounded_file, self.results / f"{execution_id}.json", self.max_bytes)
        except FileNotFoundError:
            return None
        return validate_json(LabResult, data)


def verified_completion(verification: dict) -> bool:
    readback = verification.get("readback_sha256")
    probe = verification.get("probe", {})
    return (verification.get("readback_verified") is True and isinstance(readback, str)
            and verification.get("config_readback_and_reachability") is True
            and verification.get("traffic_effects_verified") is False
            and len(readback) == 64 and all(c in "0123456789abcdef" for c in readback)
            and isinstance(probe, dict) and type(probe.get("sent")) is int
            and probe["sent"] > 0 and probe.get("received") == probe["sent"])


def verified_rollback(rollback: dict | None) -> bool:
    if not isinstance(rollback, dict):
        return False
    readback = rollback.get("readback_sha256")
    return (rollback.get("verified") is True and isinstance(readback, str)
            and len(readback) == 64 and all(c in "0123456789abcdef" for c in readback))


def verified_no_mutation(verification: dict) -> bool:
    readback = verification.get("readback_sha256")
    return (verification.get("no_mutation_verified") is True
            and verification.get("mutated") is False
            and type(verification.get("deadline_expired")) is bool
            and verification.get("readback_verified") is True and isinstance(readback, str)
            and len(readback) == 64 and all(c in "0123456789abcdef" for c in readback))
