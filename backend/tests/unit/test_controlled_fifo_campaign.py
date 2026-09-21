"""Actual unprivileged acquisition, independent arithmetic and trust refusal."""

import copy
import json
import time

import pytest

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, EvidenceError
from app.modules.simulation.controlled_fifo_campaign import ControlledPlan, SealedFIFO, acquire, prepare
from app.modules.simulation.controlled_fifo_verification import blocked_rf_result, evaluate, replay
from scripts.controlled_fifo_validation import main


@pytest.fixture
def campaign(tmp_path):
    protocol_root, capture_root = tmp_path / "protocol", tmp_path / "capture"
    prepared = prepare(protocol_root, network_id="local", run_id="run")
    ref = ArtifactRef(**prepared["protocol"])
    receipt = time.time_ns()
    captured = acquire(ArtifactStore(str(protocol_root)), ref, registered_at_unix_ns=receipt, output=capture_root)
    return protocol_root, capture_root, ref, receipt, captured


def test_real_sealed_fifo_campaign_and_no_receiver_installation(campaign):
    proot, croot, pref, receipt, captured = campaign
    result = evaluate(ArtifactStore(str(proot)), ArtifactStore(str(croot)), ArtifactRef(**captured["manifest"]),
                      registered_protocol_sha256=pref.sha256, registered_at_unix_ns=receipt)
    assert result["conditional_mathematical_bound_passed"]
    assert len(result["rows"]) == 8
    assert all(r["q_next_upper_bytes"] == 2048 and r["drift_upper_bytes_squared"] == 0 for r in result["rows"])
    assert all(0 <= r["q_actual_next_bytes"] <= 2048 for r in result["rows"])
    assert not result["receiver_installable"] and not result["physical_qualified"]
    assert result["trusted_installation"] is None
    assert not result["independent_attestation_accepted"]
    with pytest.raises(EvidenceError, match="receipt_mismatch"):
        evaluate(ArtifactStore(str(proot)), ArtifactStore(str(croot)), ArtifactRef(**captured["manifest"]),
                 registered_protocol_sha256="0" * 64, registered_at_unix_ns=receipt)


def test_no_enqueue_and_scheduler_stall_bound():
    queue = SealedFIFO([b"a"*4, b"b"*4], 8)
    assert not hasattr(queue, "enqueue")
    assert queue.dequeue(10, 20) == b"aaaa"
    assert queue.dequeue(29, 1) is None  # Faster action cannot remove an old outstanding pacing obligation.
    assert queue.dequeue(30, 1) == b"bbbb"
    assert queue.queue_bytes == 0
    stalled = SealedFIFO([b"x"*8], 8)
    assert stalled.queue_bytes == 8  # Any scheduling stall preserves q<=q0 without service credit.
    with pytest.raises(EvidenceError):
        SealedFIFO([b"x"*9], 8)


def test_replay_rejects_unenforced_or_changed_plan_and_raw(campaign):
    proot, croot, _, _, _ = campaign
    plan = ControlledPlan.model_validate_json((proot / "protocol.json").read_bytes())
    original = json.loads((croot / "train-fast-fast.json").read_bytes())
    mutations = [
        lambda w: w.update(arrivals_during_epoch_bytes=1),
        lambda w: w.update(service_lower_bytes_per_second=1),
        lambda w: w.update(runtime="isolated-linux-frr-host-route/v1"),
        lambda w: w["plan"].update(queue_id="kernel-egress"),
        lambda w: w.update(queue_after_bytes=w["queue_after_bytes"]+1),
        lambda w: w["prefill"][0].update(sha256="0"*64),
        lambda w: w.update(socket_closed_monotonic_ns=w["start_monotonic_ns"]+1),
    ]
    for mutate in mutations:
        changed = copy.deepcopy(original)
        mutate(changed)
        with pytest.raises(EvidenceError):
            replay(plan, changed)
    changed = copy.deepcopy(original)
    dequeues = [e for e in changed["events"] if e["kind"] == "dequeue"]
    dequeues[1]["monotonic_ns"] = dequeues[0]["monotonic_ns"]
    with pytest.raises(EvidenceError):
        replay(plan, changed)


def test_missing_rf_explicit_blocked_manifest(tmp_path, capsys):
    result = blocked_rf_result()
    assert result["measurement_count"] == 0 and result["raw_sources"] == []
    assert result["status"] == "blocked" and result["protocol"] is None
    path = tmp_path / "rf.json"
    assert main(["rf-blocked", "--output", str(path)]) == 2
    assert json.loads(path.read_bytes()) == result
    assert main(["rf-blocked", "--output", str(path)]) == 2  # Exclusive output, no overwrite.
    capsys.readouterr()
