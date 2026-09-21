"""Private feed fixtures; no lab launch, actual collection, or live qualification."""

import copy
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from emulation.passive_observer import (
    Admission,
    ClockAnchor,
    NewFrameFeed,
    atomic_publish,
    check_authority,
    load_admission,
    observe_feed,
    process_identity,
    snapshot_from_frame,
    validate_candidate,
)
from tests.live_provider_support import ROOT, provision


@pytest.fixture
def source(tmp_path):
    registry, network, workspace, _ = provision(tmp_path)
    installation = registry.load()
    path = ROOT / "artifacts/adr014-holdout-001/test-ppo/evidence.jsonl"
    with path.open() as stream:
        row = next(json.loads(line) for line in stream if json.loads(line).get("kind") == "ipc"
                   and json.loads(line)["request"]["command"] == "reset")
    evidence = row["response"]["data"]["evidence"]
    start = evidence["post_control_interval"]["start"]
    end = max(evidence["drain_end"],
              *(r["finished_monotonic_seconds"] for r in evidence["udp_received"]),
              *(r["after"]["monotonic_seconds"] for r in evidence["counter_windows"].values()))
    anchor = ClockAnchor(start - 1, datetime.now(UTC) - timedelta(seconds=10))
    received = ClockAnchor(end + .1, anchor.at(end + .1))
    ticks, namespace = process_identity(os.getpid())
    feed = tmp_path / "feed.jsonl"
    feed.write_bytes(b"")
    admission = Admission(version="nanfo.passive-feed-admission/v1", network_id=network,
        workspace_id=workspace, registry_sha256=installation.sha256, feed_path=str(feed),
        session_sha256="a" * 64,
        server_pid=os.getpid(), server_start_ticks=ticks,
        boot_id=uuid.UUID(Path("/proc/sys/kernel/random/boot_id").read_text().strip()),
        time_namespace=namespace, expires_at=datetime.now(UTC) + timedelta(minutes=5),
        max_clock_drift_seconds=.1, max_delivery_seconds=5,
        authorization="observe-existing-measured-feed-only")
    return registry, installation, row, admission, anchor, received


def test_new_feed_skips_existing_and_partial_frames(tmp_path):
    path = tmp_path / "feed"
    path.write_bytes(b'old-complete\nold-partial')
    feed = NewFrameFeed(path)
    try:
        assert feed.poll() == []
        with path.open("ab") as stream:
            stream.write(b'-remainder\nnew-one\nnew-')
        assert [raw for raw, _ in feed.poll()] == [b"new-one"]
        with path.open("ab") as stream:
            stream.write(b'two\n')
        assert [raw for raw, _ in feed.poll()] == [b"new-two"]
    finally:
        feed.close()


@pytest.mark.parametrize("kind", ["train", "evaluation"])
def test_only_exact_operator_pinned_evaluation_feed(tmp_path, kind):
    session = json.dumps({"kind": "session", "summary": {"kind": kind, "mode": "matched",
        "generalization": False, "window_seconds": 2., "episode_steps": 4}}).encode()
    path = tmp_path / "feed"
    path.write_bytes(session + b"\n")
    feed = NewFrameFeed(path)
    try:
        digest = hashlib.sha256(session).hexdigest()
        if kind == "train":
            with pytest.raises(ValueError, match="not_training"):
                feed.validate_session(digest)
        else:
            feed.validate_session(digest)
        with pytest.raises(ValueError, match="hash_mismatch"):
            feed.validate_session("0" * 64)
    finally:
        feed.close()


@pytest.mark.parametrize("change", ["truncate", "replace", "symlink", "permission", "oversize"])
def test_feed_invalidates_changed_source(tmp_path, change):
    path = tmp_path / "feed"
    path.write_bytes(b"original\n")
    feed = NewFrameFeed(path)
    try:
        if change == "truncate":
            path.write_bytes(b"")
        elif change == "replace":
            other = tmp_path / "new"
            other.write_bytes(b"different\n")
            other.replace(path)
        elif change == "symlink":
            target = tmp_path / "other"
            path.rename(target)
            path.symlink_to(target)
        elif change == "permission":
            path.chmod(0o666)
        else:
            with path.open("ab") as stream:
                stream.write(b"x" * (2 * 1024**2 + 1))
        with pytest.raises(ValueError):
            for _ in range(40):
                feed.poll()
    finally:
        feed.close()


def test_original_frame_preserved_and_clock_derived(source):
    _, installation, row, admission, anchor, received = source
    snapshot, end = snapshot_from_frame(json.dumps(row).encode(), admission, installation,
                                       anchor, received, anchor.monotonic)
    assert snapshot.history["frames"] == [{"request": row["request"], "response": row["response"]}]
    assert snapshot.observed_at == anchor.at(end)
    assert snapshot.run_id == uuid.UUID(row["response"]["data"]["episode_id"])
    assert snapshot.observed_at != received.wall


@pytest.mark.parametrize("change", ["backlog", "replay", "delayed", "future", "v5", "image", "terminal", "truncated", "failed", "vector"])
def test_rejects_old_incompatible_or_unavailable_measurement(source, change):
    _, installation, original, admission, anchor, received = source
    row = copy.deepcopy(original)
    data = row["response"]["data"]
    end = data["evidence"]["post_control_interval"]["end"]
    last_end = anchor.monotonic
    if change == "backlog":
        anchor = ClockAnchor(end + 1, anchor.wall)
    elif change == "replay":
        last_end = end
    elif change == "delayed":
        received = ClockAnchor(received.monotonic + 20, received.wall + timedelta(seconds=20))
    elif change == "future":
        received = ClockAnchor(end - 1, received.wall)
    elif change == "v5":
        data["evidence"]["environment_spec"]["version"] = 5
    elif change == "image":
        data["evidence"]["provenance"]["lab_image_id"] = "sha256:" + "0" * 64
    elif change in ("terminal", "truncated"):
        data["terminated" if change == "terminal" else "truncated"] = True
    elif change == "failed":
        row["response"]["ok"] = False
    else:
        row["response"]["data"] = {"vector": [0] * 16}
    with pytest.raises((ValueError, KeyError)):
        snapshot_from_frame(json.dumps(row).encode(), admission, installation, anchor, received, last_end)


@pytest.mark.parametrize("change", ["wall", "pid", "namespace", "boot", "expiry"])
def test_clock_and_process_authority(source, change):
    _, _, _, admission, _, _ = source
    anchor = ClockAnchor.capture()
    check_authority(admission, anchor, anchor)
    now = anchor
    if change == "wall":
        now = ClockAnchor(anchor.monotonic, anchor.wall + timedelta(seconds=1))
    elif change == "pid":
        admission.server_start_ticks += 1
    elif change == "namespace":
        admission.time_namespace = "time:[1]"
    elif change == "boot":
        admission.boot_id = uuid.uuid4()
    else:
        admission.expires_at = anchor.wall
    with pytest.raises(ValueError):
        check_authority(admission, anchor, now)


@pytest.mark.parametrize("remote", ["monotonic 0 0\nboottime 0 0\n", "monotonic 1 0\nboottime 0 0\n", ""])
def test_docker_time_namespace_requires_exact_kernel_offsets(source, monkeypatch, remote):
    from emulation import passive_observer as module
    _, _, _, admission, _, _ = source
    anchor = ClockAnchor.capture()
    ticks = admission.server_start_ticks
    admission.time_namespace = "time:[42]"
    monkeypatch.setattr(module, "process_identity", lambda _: (ticks, "time:[42]"))
    original_read = Path.read_text
    def read(path, *args, **kwargs):
        if str(path) == "/proc/self/timens_offsets":
            return "monotonic 0 0\nboottime 0 0\n"
        if str(path) == f"/proc/{admission.server_pid}/timens_offsets":
            return remote
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    if remote == "monotonic 0 0\nboottime 0 0\n":
        check_authority(admission, anchor, anchor)
    else:
        with pytest.raises(ValueError, match="offsets_differ"):
            check_authority(admission, anchor, anchor)


def test_admission_protected_hash_and_atomic_permissions(source, tmp_path):
    *_, admission, _, _ = source
    path = tmp_path / "admission.json"
    content = admission.model_dump_json().encode()
    atomic_publish(path, content)
    digest = hashlib.sha256(content).hexdigest()
    assert load_admission(path, digest) == admission
    assert path.stat().st_mode & 0o777 == 0o600
    path.write_bytes(content + b" ")
    with pytest.raises(ValueError, match="hash_mismatch"):
        load_admission(path, digest)


async def test_confined_candidate_validates_original_nonterminal_frame(source):
    registry, installation, row, admission, anchor, received = source
    # Test clock only: evidence timestamps and actual request/response stay unchanged.
    # This is frozen validator compatibility, not a fresh live measurement claim.
    snapshot, _ = snapshot_from_frame(json.dumps(row).encode(), admission, installation,
                                      anchor, received, anchor.monotonic)
    await validate_candidate(registry, installation, snapshot)
    snapshot.history["frames"][0]["response"]["data"]["observation"]["goodput_mbps"] += 1
    from scripts.frozen_model_diagnostic import canonical_hash
    snapshot.history_sha256 = canonical_hash(snapshot.history)
    with pytest.raises(ValueError):
        await validate_candidate(registry, installation, snapshot)


async def test_idle_bridge_never_publishes_existing_history_or_dispatches(source, tmp_path, monkeypatch):
    registry, _, row, admission, _, _ = source
    for key, value in registry.configuration().environment().items():
        monkeypatch.setenv(key, value)
    session = json.dumps({"kind": "session", "summary": {"kind": "evaluation", "mode": "matched",
        "generalization": False, "window_seconds": 2., "episode_steps": 4}}).encode()
    admission.session_sha256 = hashlib.sha256(session).hexdigest()
    Path(admission.feed_path).write_bytes(session + b"\n" + json.dumps(row).encode() + b"\n")
    admission_path = tmp_path / "admission.json"
    content = admission.model_dump_json().encode()
    atomic_publish(admission_path, content)
    result = await observe_feed(admission_path, hashlib.sha256(content).hexdigest(), duration_seconds=1)
    assert result == {"published": 0, "actuation": False, "training": False}
    snapshot = json.loads((Path(registry.settings.observation_root) / "snapshot.json").read_bytes())
    assert snapshot["version"] == "nanfo.passive-feed-unavailable/v1"


async def test_bridge_validates_before_atomic_publish_and_invalidates_on_disconnect(source, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from emulation import passive_observer as module
    registry, _, row, admission, anchor, received = source
    for key, value in registry.configuration().environment().items():
        monkeypatch.setenv(key, value)
    session = json.dumps({"kind": "session", "summary": {"kind": "evaluation", "mode": "matched",
        "generalization": False, "window_seconds": 2., "episode_steps": 4}}).encode()
    admission.session_sha256 = hashlib.sha256(session).hexdigest()
    Path(admission.feed_path).write_bytes(session + b"\n")
    admission_path = tmp_path / "admission.json"
    content = admission.model_dump_json().encode()
    atomic_publish(admission_path, content)
    target = Path(registry.settings.observation_root) / "snapshot.json"
    calls = []
    def capture():
        calls.append(1)
        return anchor if len(calls) == 1 else received
    monkeypatch.setattr(ClockAnchor, "capture", capture)
    monkeypatch.setattr(module.time, "monotonic", lambda: received.monotonic)
    validated = []
    async def validate(*args):
        assert json.loads(target.read_bytes())["version"] == "nanfo.passive-feed-unavailable/v1"
        validated.append(args[-1].history)
    monkeypatch.setattr(module, "validate_candidate", validate)
    polls = []
    def poll(_):
        if not polls:
            polls.append(1)
            return [(json.dumps(row).encode(), 1000)]
        published = json.loads(target.read_bytes())
        assert published["history"] == validated[0]
        assert published["observed_at"] == anchor.at(row["response"]["data"]["evidence"]["post_control_interval"]["end"]).isoformat().replace("+00:00", "Z")
        raise ValueError("private-fixture-disconnected")
    monkeypatch.setattr(NewFrameFeed, "poll", poll)
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    with pytest.raises(ValueError, match="disconnected"):
        await observe_feed(admission_path, hashlib.sha256(content).hexdigest(), duration_seconds=60)
    assert json.loads(target.read_bytes())["version"] == "nanfo.passive-feed-unavailable/v1"
    receipts = list(target.parent.glob("receipt-*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_bytes())
    assert receipt["actuation"] is False and receipt["feed_end_offset"] == 1000
    assert receipt["admission_sha256"] == hashlib.sha256(content).hexdigest()
