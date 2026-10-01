"""Strict ADR-010 plan, mailbox, actual-evidence and authority regression gates."""

import copy
import json
import multiprocessing
import os
import stat
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.modules.intent.lab import (
    LabCommand,
    LabIntent,
    Mailbox,
    PendingLabCommand,
    digest,
    prepare_plan,
    verified_completion,
    verified_no_mutation,
    verified_rollback,
)
from app.modules.intent.schemas import ExecuteIntentRequest
from app.modules.network.emulation import EmulationBinding
from app.modules.telemetry.emulation import EmulationSnapshot


def payload(operation="reroute"):
    return {"action": "reroute_path" if operation in {"reroute", "multipath", "restore"} else "throttle_qos",
            "scope": {"source_host": "h1", "destination_host": "h3"},
            "constraints": {"operation": operation, "paths": [["access1", "dist1", "access2"]]
                if operation == "reroute" else [["access1", "dist1", "access2"], ["access1", "dist2", "access2"]]
                if operation == "multipath" else [], "rate_mbps": 10 if operation in {"shape", "police"} else None}}


def command():
    plan = LabIntent.model_validate(payload()).normalize()
    return LabCommand(version=1, execution_id=uuid.uuid4(), run_id=uuid.uuid4(), binding_digest="a" * 64,
                      plan_hash=digest(plan.model_dump(mode="json")), fence=1,
                      dispatch_expires_at=datetime.now(UTC) + timedelta(seconds=4),
                      deadline=datetime.now(UTC) + timedelta(seconds=120), operation="execute", plan=plan)


@pytest.mark.parametrize("operation", ["reroute", "multipath", "shape", "police", "restore"])
def test_normalized_plan_matches_exact_lab_contract(operation):
    from emulation.mailbox import planHash, validatePlan

    plan = LabIntent.model_validate(payload(operation)).normalize().model_dump(mode="json")
    assert set(plan) == {"operation", "source_host", "destination_host", "paths", "weights", "rate_mbps", "dscp"}
    assert validatePlan(plan) == plan
    assert planHash(plan) == digest(plan)


def test_dispatch_envelope_matches_lab_receiver():
    from emulation.mailbox import COMMAND_FIELDS, validateEnvelope

    if "dispatch_expires_at" not in COMMAND_FIELDS:
        pytest.skip("Lab agent must implement required dispatch_expires_at before deployment/live verification")
    cmd = command()
    assert validateEnvelope(cmd.model_dump(mode="json"), f"{cmd.execution_id}.json")


@pytest.mark.parametrize(("section", "key", "value"), [
    (None, "action", "isolate_vlan"), (None, "shell", "anything"),
    ("scope", "source_host", "h9"), ("scope", "destination_host", "h1"),
    ("constraints", "dscp", True), ("constraints", "dscp", 64),
    ("constraints", "weights", [True]), ("constraints", "weights", [0]),
    ("constraints", "paths", [["access1", "dist1", "access1", "access2"]]),
    ("constraints", "rate_mbps", float("nan")), ("constraints", "interface", "eth0"),
])
def test_plan_rejects_unknown_and_unsafe_parameters(section, key, value):
    data = payload()
    (data if section is None else data[section])[key] = value
    with pytest.raises(ValueError):
        LabIntent.model_validate(data).normalize()


@pytest.mark.parametrize("value", [1, "true", None, [], {}])
def test_manual_approval_and_cancel_are_explicit_booleans(value):
    for field in ("manual_approval", "cancel"):
        with pytest.raises(ValidationError):
            ExecuteIntentRequest(workspace_id=uuid.uuid4(), intent_id=uuid.uuid4(), **{field: value})


LAB_KEY = b"c15-test-key-" + b"0123456789abcdef" * 3


@pytest.fixture
def mailbox_settings(tmp_path, monkeypatch):
    for name in ("commands", "results", "telemetry", "binding"):
        (tmp_path / name).mkdir()
    # ADR-028 C15: the execution worker's protected mailbox HMAC key (0400, owner-only).
    key = tmp_path / "lab_command_key"
    key.write_bytes(LAB_KEY)
    key.chmod(0o400)
    monkeypatch.setenv("NANFO_LAB_COMMAND_KEY_FILE", str(key))
    return SimpleNamespace(**{**{key: value for key, value in get_settings().model_dump().items()
                               if key.startswith("EMULATION_")}, "EXECUTION_MODE": "emulation",
        "EMULATION_CONTROL_ENABLED": True,
        "EMULATION_COMMANDS_PATH": str(tmp_path / "commands"), "EMULATION_RESULTS_PATH": str(tmp_path / "results"),
        "EMULATION_SNAPSHOT_PATH": str(tmp_path / "telemetry" / "snapshot.json"),
        "EMULATION_BINDING_PATH": str(tmp_path / "binding" / "binding.json")})


async def test_mailbox_is_atomic_bounded_immutable_and_symlink_refusing(mailbox_settings, tmp_path):
    from emulation.lab_contracts import verify_command

    mailbox = Mailbox(mailbox_settings)
    cmd = command()
    mailbox.write(cmd)
    path = mailbox.commands / f"{cmd.execution_id}.json"
    assert verify_command(LAB_KEY, json.loads(path.read_bytes())) == cmd.model_dump(mode="json")
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert list(mailbox.commands.glob("*.json")) == [path]
    mailbox.write(cmd)
    with pytest.raises(ValueError, match="immutable"):
        mailbox.write(cmd.model_copy(update={"fence": 2}))
    mailbox.write(cmd.model_copy(update={"operation": "cancel"}))
    with pytest.raises(ValueError, match="cannot revert"):
        mailbox.write(cmd)
    path.unlink()
    path.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError):
        mailbox.write(cmd)
    result = mailbox.results / f"{cmd.execution_id}.json"
    result.symlink_to(path)
    with pytest.raises(OSError):
        await mailbox.read(cmd.execution_id)


def test_real_evidence_required():
    good = {"readback_verified": True, "readback_sha256": "a" * 64, "probe": {"sent": 3, "received": 3},
            "config_readback_and_reachability": True, "traffic_effects_verified": False}
    assert verified_completion(good)
    for bad in ({}, {"status": "verified"}, {**good, "probe": {}}, {**good, "readback_sha256": "no"},
                {**good, "traffic_effects_verified": True}, {**good, "config_readback_and_reachability": False}):
        assert not verified_completion(bad)
    assert not verified_rollback({"verified": True})
    assert verified_rollback({"verified": True, "readback_sha256": "f" * 64})


@pytest.fixture
def prepared_lab(monkeypatch, mailbox_settings):
    from emulation.topology import manifest

    expected = manifest()
    workspace_id, network_id, actor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    binding = EmulationBinding.model_validate_json(json.dumps({"version": 1, "topology_id": expected["topology_id"],
        "workspace_id": str(workspace_id), "network_id": str(network_id), "actor_user_id": str(uuid.uuid4()),
        "switches": {s["dpid"]: str(uuid.uuid4()) for s in expected["switches"]},
        "hosts": {h["name"]: str(uuid.uuid4()) for h in expected["hosts"]},
        "port_capacities_mbps": expected["port_capacities_mbps"]}))
    names = {s["name"]: s["dpid"] for s in expected["switches"]}
    now = datetime.now(UTC).isoformat()
    snapshot = EmulationSnapshot.model_validate_json(json.dumps({"version": 1, "topology_id": expected["topology_id"],
        "run_id": str(uuid.uuid4()), "sequence": 1, "observed_at": now,
        "switches": [{"name": s["name"], "dpid": s["dpid"], "observed_at": now, "ports": [], "flows": []}
                     for s in expected["switches"]], "hosts": expected["hosts"], "queues": [], "probes": [],
        "links": [{"src_dpid": names[a], "src_port": ap, "dst_dpid": names[b], "dst_port": bp}
                  for link in expected["links"] for (a, ap), (b, bp) in ((link["a"], link["b"]), (link["b"], link["a"]))
                  if a in names and b in names]}))
    monkeypatch.setattr("app.modules.intent.lab.load_binding", AsyncMock(return_value=binding))
    monkeypatch.setattr("app.modules.intent.lab.SnapshotReader.read", AsyncMock(return_value=snapshot))
    profile = AsyncMock(return_value=SimpleNamespace(permissions=["write:config", "execute:rollback"]))
    monkeypatch.setattr("app.modules.intent.lab.AuthService.get_profile", profile)
    access = AsyncMock()
    monkeypatch.setattr("app.modules.intent.lab.NetworkService.assert_network_workspace_access", access)
    monkeypatch.setattr("app.modules.intent.lab.NetworkService.assert_device_workspace_access",
                        AsyncMock(return_value=(network_id, workspace_id)))
    return SimpleNamespace(binding=binding, snapshot=snapshot, profile=profile, access=access, args={
        "settings": mailbox_settings, "db": None, "redis": None, "workspace_id": workspace_id,
        "network_id": network_id, "actor_id": str(actor_id), "payload": payload()})


async def test_prepare_checks_request_and_binding_actor(prepared_lab):
    lab = prepared_lab
    plan, binding, snapshot = await prepare_plan(**lab.args)
    assert plan.operation == "reroute" and snapshot is lab.snapshot and binding is lab.binding
    assert {call.args[0] for call in lab.profile.await_args_list} == {
        lab.args["actor_id"], str(lab.binding.actor_user_id)}
    assert all(call.kwargs["require_write"] for call in lab.access.await_args_list)
    lab.profile.return_value.permissions = ["write:config"]
    with pytest.raises(ValueError, match="capabilities"):
        await prepare_plan(**lab.args)


@pytest.mark.parametrize("fault", ["scope", "capacity", "host", "link", "role", "mode"])
async def test_prepare_rejects_untrusted_context(prepared_lab, fault):
    lab = prepared_lab
    if fault == "scope":
        lab.args["workspace_id"] = uuid.uuid4()
    elif fault == "capacity":
        lab.binding.port_capacities_mbps[next(iter(lab.binding.port_capacities_mbps))] = 999
    elif fault == "host":
        lab.snapshot.hosts[0].port_no = 999
    elif fault == "link":
        lab.snapshot.links.clear()
    elif fault == "role":
        lab.args["payload"] = copy.deepcopy(lab.args["payload"])
        lab.args["payload"]["constraints"]["paths"] = [["dist1", "access2"]]
    else:
        lab.args["settings"].EXECUTION_MODE = "production"
    with pytest.raises(ValueError):
        await prepare_plan(**lab.args)


def test_mailbox_cross_process_check_replace_serialization(mailbox_settings, monkeypatch):
    """Pause execute between check and replace; successor cancel must wait."""
    context = multiprocessing.get_context("fork")
    checked, release, cancelling, cancelled = (context.Event() for _ in range(4))
    cmd = command()
    replace = os.replace

    def paused_replace(*args, **kwargs):
        checked.set()
        assert release.wait(5)
        replace(*args, **kwargs)

    def execute():
        os.replace = paused_replace
        Mailbox(mailbox_settings).write(cmd)

    def cancel():
        cancelling.set()
        Mailbox(mailbox_settings).write(cmd.model_copy(update={"operation": "cancel"}))
        cancelled.set()

    first = context.Process(target=execute)
    second = context.Process(target=cancel)
    first.start()
    try:
        assert checked.wait(5)
        second.start()
        assert cancelling.wait(5)
        assert not cancelled.wait(.2)
        release.set()
        first.join(5)
        second.join(5)
        assert first.exitcode == second.exitcode == 0
        path = Mailbox(mailbox_settings).commands / f"{cmd.execution_id}.json"
        assert json.loads(path.read_bytes())["operation"] == "cancel"
        with pytest.raises(ValueError, match="cannot revert"):
            Mailbox(mailbox_settings).write(cmd)
    finally:
        release.set()
        for process in (first, second):
            if process.is_alive():
                process.kill()
                process.join()


def test_delayed_thread_publication_checks_expired_authority(mailbox_settings, monkeypatch):
    cmd = command()
    expired = threading.Event()
    fsync = os.fsync

    def expire(fd):
        fsync(fd)
        expired.set()

    monkeypatch.setattr(os, "fsync", expire)
    with pytest.raises(ValueError, match="expired"):
        Mailbox(mailbox_settings).write(cmd, can_publish=lambda: not expired.is_set())
    assert not list(Mailbox(mailbox_settings).commands.glob("*.json"))


def test_mailbox_lock_symlink_refused(mailbox_settings, tmp_path):
    cmd = command()
    lock = Mailbox(mailbox_settings).commands / f".{cmd.execution_id}.lock"
    lock.symlink_to(tmp_path / "unrelated")
    with pytest.raises(OSError):
        Mailbox(mailbox_settings).write(cmd)
    assert not (tmp_path / "unrelated").exists()


@pytest.mark.parametrize(("field", "value"), [
    ("mutated", True), ("mutated", 0), ("deadline_expired", None), ("deadline_expired", 0),
    ("no_mutation_verified", 1), ("readback_verified", False),
])
def test_no_mutation_proof_rejects_inconsistent_or_coerced_fields(field, value):
    proof = {"mutated": False, "deadline_expired": True, "no_mutation_verified": True,
             "readback_verified": True, "readback_sha256": "a" * 64}
    assert verified_no_mutation(proof)
    proof[field] = value
    assert not verified_no_mutation(proof)


def test_pending_metadata_is_never_publishable(mailbox_settings):
    data = command().model_dump()
    data.pop("dispatch_expires_at")
    pending = PendingLabCommand.model_validate(data)
    with pytest.raises(TypeError, match="not a dispatch"):
        Mailbox(mailbox_settings).write(pending)
    with pytest.raises(ValidationError):
        LabCommand.model_validate(data)


@pytest.mark.parametrize("seconds", [-1, 0, 5.01, 60])
def test_receiver_contract_rejects_expired_or_overlong_new_dispatch(seconds):
    now = datetime.now(UTC)
    cmd = command().model_copy(update={"dispatch_expires_at": now + timedelta(seconds=seconds)})
    with pytest.raises(ValueError, match="authorization"):
        cmd.assert_new_dispatch(now)


def test_pause_after_final_sender_check_exposes_expired_not_renewed_authorization(mailbox_settings, monkeypatch):
    """Exact last-check/rename pause; receiver contract, not flock, rejects it."""
    cmd = command().model_copy(update={"dispatch_expires_at": datetime.now(UTC) + timedelta(seconds=.15)})
    replace = os.replace
    entered, released = threading.Event(), threading.Event()
    failures = []

    def paused_replace(*args, **kwargs):
        entered.set()
        assert released.wait(3)
        replace(*args, **kwargs)

    def sender():
        try:
            Mailbox(mailbox_settings).write(cmd)
        except Exception as exc:  # noqa: BLE001 - propagate thread assertion to the test
            failures.append(exc)

    monkeypatch.setattr(os, "replace", paused_replace)
    thread = threading.Thread(target=sender)
    thread.start()
    try:
        assert entered.wait(3)
        time.sleep(.2)
    finally:
        released.set()
        thread.join(3)
    assert not thread.is_alive() and not failures
    from emulation.lab_contracts import verify_command

    wire = json.loads((Mailbox(mailbox_settings).commands / f"{cmd.execution_id}.json").read_bytes())
    published = LabCommand.model_validate_json(json.dumps(verify_command(LAB_KEY, wire)))
    assert published.dispatch_expires_at == cmd.dispatch_expires_at
    assert published.deadline > datetime.now(UTC)
    with pytest.raises(ValueError, match="expired"):
        published.assert_new_dispatch(datetime.now(UTC))
    # Cancellation still carries the same expired authorization, for compensation.
    Mailbox(mailbox_settings).write(published.model_copy(update={"operation": "cancel"}))


def test_c15_written_envelope_is_canonical_and_authenticated_by_the_lab_reader(mailbox_settings):
    """The backend writer and the lab reader share one MAC contract (emulation.lab_contracts)."""
    from unittest.mock import Mock

    from emulation.lab_contracts import canonical
    from emulation.mailbox import Mailbox as LabMailbox

    writer = Mailbox(mailbox_settings)
    cmd = command()
    writer.write(cmd)
    path = writer.commands / f"{cmd.execution_id}.json"
    raw = path.read_bytes()
    envelope = json.loads(raw)
    assert set(envelope) == {*cmd.model_dump(mode="json"), "hmac_sha256"}
    assert raw == canonical(envelope)
    reader = LabMailbox(Mock(), str(cmd.run_id), cmd.binding_digest, writer.commands, writer.results,
                        command_key=LAB_KEY)
    try:
        assert reader.readCommand(path) == cmd.model_dump(mode="json")
        wrong = LabMailbox(Mock(), str(cmd.run_id), cmd.binding_digest, writer.commands, writer.results,
                           command_key=b"w" * 32)
        with pytest.raises(ValueError, match="command_mac_invalid"):
            wrong.readCommand(path)
        wrong.close()
    finally:
        reader.close()


def test_c15_writer_fails_closed_without_a_protected_key(mailbox_settings, monkeypatch, tmp_path):
    cmd = command()
    monkeypatch.delenv("NANFO_LAB_COMMAND_KEY_FILE")
    with pytest.raises(ValueError, match="lab_command_key_unconfigured"):
        Mailbox(mailbox_settings).write(cmd)
    loose = tmp_path / "loose_key"
    loose.write_bytes(LAB_KEY)
    loose.chmod(0o640)
    monkeypatch.setenv("NANFO_LAB_COMMAND_KEY_FILE", str(loose))
    with pytest.raises(ValueError, match="unprotected"):
        Mailbox(mailbox_settings).write(cmd)
    short = tmp_path / "short_key"
    short.write_bytes(b"k" * 31)
    short.chmod(0o400)
    monkeypatch.setenv("NANFO_LAB_COMMAND_KEY_FILE", str(short))
    with pytest.raises(ValueError):
        Mailbox(mailbox_settings).write(cmd)
    assert not list(Mailbox(mailbox_settings).commands.iterdir())


@pytest.mark.parametrize("forged", ["unsigned", "wrong_mac", "wrong_key"])
def test_c15_writer_never_overwrites_an_unauthenticated_existing_command(mailbox_settings, forged):
    from emulation.lab_contracts import sign_command

    mailbox = Mailbox(mailbox_settings)
    cmd = command()
    body = cmd.model_dump(mode="json")
    value = {"unsigned": body, "wrong_mac": {**body, "hmac_sha256": "0" * 64},
             "wrong_key": sign_command(b"x" * 32, body)}[forged]
    path = mailbox.commands / f"{cmd.execution_id}.json"
    path.write_bytes(json.dumps(value).encode())
    before = path.read_bytes()
    with pytest.raises(ValueError, match="command_mac"):
        mailbox.write(cmd.model_copy(update={"operation": "cancel"}))
    assert path.read_bytes() == before
