"""Concrete controller port wiring and authenticated receiver handoff tests."""

import asyncio
import copy
import time
import threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.modules.autonomy.experimental.adapter import ExperimentalLabAdapter
from emulation.experimental_lab_contract import VERSION, decode


def test_campaign_watchdog_does_not_issue_or_consume_pending_writer_grant(tmp_path, monkeypatch):
    """Real campaign subclass + frozen matched commands, independent reader race."""
    import os

    from emulation import experimental_lab_contract as contract
    from emulation.tests.test_experimental_lab import ContractTests
    from scripts.verify_experimental_lab import campaign_receiver_class

    tmp_path.chmod(0o700)
    receiver, rules, routes, _ = ContractTests().receiver(tmp_path, campaign_receiver_class())
    req = ContractTests().wire(receiver, "bootstrap")
    receiver.current = contract.Request.parse(contract.canonical(req))
    receiver.phase = "bootstrapping"
    receiver.bootstrap_request_id = req["request_id"]
    receiver.active_until = time.time() + 60
    contract.atomic_write(tmp_path / "bootstrap-admission.json", {
        "policy_sha256": receiver.policy_hash, "request_id": req["request_id"],
        "expires_at": time.time() + 60, "authorized": True})
    original_write = contract.atomic_write
    requested, reader_checked = threading.Event(), threading.Event()
    requests, failures = [], []

    def record_request(path, value):
        original_write(path, value)
        if Path(path).name == "checkpoint-request.json":
            requests.append(copy.deepcopy(value))
            if len(requests) == 1:
                requested.set()
            else:
                original_write(tmp_path / "checkpoint-response.json", {"id": value["id"], "authorized": True})

    original_authority = receiver.authority

    def check_only():
        original_authority()
        if threading.current_thread().name == "test-watchdog":
            reader_checked.set()

    monkeypatch.setattr(contract, "atomic_write", record_request)
    monkeypatch.setattr(receiver, "authority", check_only)

    def write():
        try:
            with receiver.lock:
                receiver.runtime.routing.change(0)
        except Exception as exc:
            failures.append(exc)

    writer = threading.Thread(target=write)
    watcher = threading.Thread(target=receiver.watchdog, name="test-watchdog")
    writer.start()
    try:
        assert requested.wait(2)
        watcher.start()
        assert reader_checked.wait(2)
        assert len(requests) == 1
        assert receiver.checkpoint_events == []
        original_write(tmp_path / "checkpoint-response.json", {"id": requests[0]["id"], "authorized": True})
        writer.join(4)
        assert not writer.is_alive() and not failures
        assert len(requests) == len(receiver.checkpoint_events) == 12
        assert len({event["id"] for event in receiver.checkpoint_events}) == 12
        assert len(rules) == len(routes) == 6
        receiver.runtime.restore()
        assert not rules and not routes
    finally:
        receiver.shutdown.set()
        writer.join(6)
        if watcher.ident is not None:
            watcher.join(2)
        os.close(receiver.claim)


@pytest.mark.asyncio
async def test_guarded_transport_refreshes_authority_during_original_io():
    adapter = ExperimentalLabAdapter.__new__(ExperimentalLabAdapter)
    adapter.policy_hash = "a" * 64
    adapter.token = "b" * 64
    adapter.fence = 0
    adapter.synced = False
    adapter.receiver_policy = {"heartbeat_seconds": 5}
    requests = []

    async def transport(payload):
        request = decode(payload)
        requests.append(request)
        if request["operation"] == "execute":
            await asyncio.sleep(.45)
        return {"version": VERSION, "request_id": request["request_id"], "fence": request["fence"],
                "policy_sha256": request["policy_sha256"], "status": "ok",
                "evidence": {"current_fence": 7} if request["operation"] == "status" else {"actual": True}}

    adapter.transport = transport
    checkpoint = AsyncMock()
    result = await adapter._guarded("execute", checkpoint, action=1, duration=10)
    assert result == {"actual": True}
    assert checkpoint.await_count >= 3
    assert sum(row["operation"] == "execute" for row in requests) == 1
    assert all(row["fence"] > 7 for row in requests[1:])


@pytest.mark.asyncio
async def test_revocation_interrupts_inflight_execute_with_stop_not_replay():
    adapter = ExperimentalLabAdapter.__new__(ExperimentalLabAdapter)
    adapter.policy_hash, adapter.token = "a" * 64, "b" * 64
    adapter.fence, adapter.synced = 0, True
    adapter.receiver_policy = {"heartbeat_seconds": 5}
    operations = []

    async def transport(payload):
        request = decode(payload)
        operations.append(request["operation"])
        if request["operation"] == "execute":
            await asyncio.sleep(5)
        return {**{key: request[key] for key in ("version", "request_id", "fence", "policy_sha256")},
                "status": "ok", "evidence": {}}

    adapter.transport = transport
    checkpoint = AsyncMock(side_effect=[None, ValueError("revoked")])
    with pytest.raises(ValueError, match="revoked"):
        await adapter._guarded("execute", checkpoint, action=1, duration=10)
    assert operations == ["heartbeat", "execute", "stop"]


def test_original_frame_clock_not_freshened_on_hold_readback():
    old = time.time() - 10
    evidence = {"clock_wall": old, "clock_monotonic": 100,
                "frame": {"response": {"data": {"evidence": {
                    "post_control_interval": {"start": 94, "end": 96}}}}}}
    end, start = ExperimentalLabAdapter._times(evidence)
    assert end.timestamp() == pytest.approx(old - 4, abs=1e-6, rel=0)
    assert start.timestamp() == pytest.approx(old - 6, abs=1e-6, rel=0)


@pytest.mark.asyncio
async def test_real_adapter_observe_prepare_recover_raw_hashes_and_episode(tmp_path):
    """Complete preserved frame, actual core contracts; transport is offline only."""
    import json
    from uuid import UUID, uuid4

    from app.modules.autonomy.experimental.ports import Ports
    from app.modules.autonomy.experimental.schemas import ActionCommand, contract_digest, utcnow
    from emulation.experimental_lab_contract import IMAGE, MODEL, SOURCE
    from tests.experimental_lab_support import case

    source = Path(__file__).resolve().parents[3] / "ai-engine/artifacts/adr024-qualified-001/live/path0/snapshot-0.json"
    snapshot = json.loads(source.read_bytes())
    raw = copy.deepcopy(snapshot["history"]["frames"][0])
    data = raw["response"]["data"]
    c = case()
    route = c.policy.routes[0].model_copy(update={"path": ("access1", "dist1", "access2"),
                                                "device_ids": ("access1", "dist1", "access2")})
    runtime = c.policy.runtime.model_copy(update={"container_id": "c" * 64,
        "image_sha256": IMAGE.removeprefix("sha256:"), "source_sha256": SOURCE})
    policy = c.policy.model_copy(update={"run_id": uuid4(), "measurement_run_id": UUID(data["episode_id"]),
        "runtime": runtime, "checkpoint_sha256": MODEL, "routes": (route,)})
    receiver_policy = {"controller_policy_sha256": None, "image_id": IMAGE, "source_sha256": SOURCE,
        "model_sha256": MODEL, "wrapper_sha256": runtime.wrapper_sha256, "container_id": runtime.container_id,
        "heartbeat_seconds": 5}
    token = tmp_path / "token"
    token.write_text("b" * 64)
    token.chmod(0o600)
    baseline = {"tables": {"access1:19110": {"rules": [], "routes": []}},
                "paths": {"h1->h3": {"nodes": ["h1", "access1", "dist1", "access2", "h3"]}}}
    binding = {"controller_policy_sha256": contract_digest(policy), "receiver_policy_sha256": "a" * 64,
               "run_id": data["episode_id"], "baseline_sha256": contract_digest(baseline)}
    operations = []

    async def transport(payload):
        req = decode(payload)
        operations.append(req["operation"])
        ev = {}
        if req["operation"] == "status":
            ev = {"current_fence": 0, "binding": binding}
        elif req["operation"] == "observe":
            # Offline clock alignment for this test fixture only; raw frame untouched.
            ev = {"frame": raw, "clock_wall": time.time() - .1,
                  "clock_monotonic": data["evidence"]["post_control_interval"]["end"],
                  "baseline": baseline, "binding": binding}
        elif req["operation"] == "recover":
            ev = {"restoration": {"baseline": baseline, "baseline_sha256": contract_digest(baseline),
                  "readback": baseline, "owned_empty": True, "original_forwarding_verified": True}}
        return {**{key: req[key] for key in ("version", "request_id", "fence", "policy_sha256")},
                "status": "ok", "evidence": ev}

    adapter = ExperimentalLabAdapter(policy=policy, receiver_policy=receiver_policy,
        receiver_policy_sha256="a" * 64, token_path=token, transport=transport)
    checkpoint = AsyncMock()
    Ports(adapter, c.ports.model, c.ports.simulator, adapter).bind_checkpoint(checkpoint)
    try:
        frame = await adapter.observe()
        assert frame.snapshot.history["frames"][0] == raw
        assert frame.snapshot.run_id == UUID(data["episode_id"]) != policy.run_id
        now = utcnow()
        command = ActionCommand(request_id=uuid4(), run_id=policy.run_id, resource_id=runtime.resource_id,
            fence=1, network_id=policy.network_id, workspace_id=policy.workspace_id, runtime=runtime,
            route=route, policy_sha256=contract_digest(policy), frame_sha256=contract_digest(frame),
            inference_sha256="a" * 64, simulation_sha256="a" * 64, created_at=now,
            expires_at=now + timedelta(seconds=10))
        prepared = await adapter.prepare(command)
        assert prepared.baseline == baseline
        restored = await adapter.recover(prepared, checkpoint)
        assert restored.status == "restored"
        assert "bootstrap" not in operations and "execute" not in operations
        # A new adapter process has no baseline cache: durable PreparedAction plus
        # receiver binding/fence and original readback suffice, no execute replay.
        restarted = ExperimentalLabAdapter(policy=policy, receiver_policy=receiver_policy,
            receiver_policy_sha256="a" * 64, token_path=token, transport=transport)
        again = await restarted.recover(prepared, checkpoint)
        assert again.status == "restored"
        assert operations[-2:] == ["status", "recover"]
    finally:
        await adapter.close()
