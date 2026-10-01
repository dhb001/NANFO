"""ADR-028 checkpoint safety: one bounded read, external pin before parsing, weights-only load."""

import hashlib
import os

import pytest
import torch

from nanfo_routing import artifacts, cli
from nanfo_routing.artifacts import (
    inspectCheckpoint,
    loadCheckpoint,
    loadCheckpointIdentity,
    saveCheckpoint,
)
from nanfo_routing.ppo import PPO


@pytest.fixture
def checkpoint(tmp_path):
    path = tmp_path / "fixture.ptz"
    saveCheckpoint(
        path,
        PPO(),
        provenance="offline-fixture-not-trained-model",
        trainingSeeds=[],
        episodes=0,
        evidenceHash="0" * 64,
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_identity_is_the_loaded_bytes_from_a_single_read(checkpoint, monkeypatch):
    path, digest = checkpoint
    reads, loads = [], []
    original, load = artifacts.readCheckpoint, torch.load

    def counted(value):
        reads.append(value)
        return original(value)

    def restricted(source, **kwargs):
        loads.append(kwargs)
        return load(source, **kwargs)

    monkeypatch.setattr(artifacts, "readCheckpoint", counted)
    monkeypatch.setattr(artifacts.torch, "load", restricted)
    agent, manifest, identity = loadCheckpointIdentity(
        path, expectedSha256=digest, requireMeasured=False
    )
    assert identity == {"checkpoint_sha256": digest, "manifest": manifest.model_dump(mode="json")}
    assert inspectCheckpoint(path, expectedSha256=digest) == identity
    assert len(reads) == 2 and all(kwargs["weights_only"] is True for kwargs in loads)
    assert not agent.model.training


def test_pin_is_checked_before_any_parsing(checkpoint, tmp_path):
    path, digest = checkpoint
    with pytest.raises(ValueError, match="pinned SHA-256"):
        loadCheckpoint(path, requireMeasured=False, expectedSha256="0" * 64)
    for pin in ("A" * 64, "0" * 63, 7):
        with pytest.raises(ValueError, match="invalid checkpoint pin"):
            loadCheckpoint(path, requireMeasured=False, expectedSha256=pin)
    garbage = tmp_path / "garbage.ptz"
    garbage.write_bytes(b"not a zip archive")
    with pytest.raises(ValueError, match="pinned SHA-256"):
        inspectCheckpoint(garbage, expectedSha256=digest)
    exact = hashlib.sha256(garbage.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="invalid checkpoint archive"):
        inspectCheckpoint(garbage, expectedSha256=exact)


def test_symlinks_fifos_and_oversize_are_refused_without_blocking(
    checkpoint, tmp_path, monkeypatch
):
    path, _ = checkpoint
    link = tmp_path / "link.ptz"
    link.symlink_to(path)
    with pytest.raises(OSError):
        inspectCheckpoint(link)
    fifo = tmp_path / "fifo.ptz"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="regular file"):
        inspectCheckpoint(fifo)
    monkeypatch.setattr(artifacts, "MAX_CHECKPOINT", 64)
    with pytest.raises(ValueError, match="exceeds bound"):
        inspectCheckpoint(path)


def test_cli_pins_inspect_and_infer_and_rejects_conflicting_selection_pin(
    checkpoint, tmp_path, capsys
):
    path, digest = checkpoint
    assert cli.main(["inspect", "--checkpoint", str(path), "--checkpoint-sha256", digest]) == 0
    capsys.readouterr()
    history = tmp_path / "history.json"
    history.write_text("{}")
    for command in ("inspect", "infer"):
        extra = ["--history", str(history)] if command == "infer" else []
        argv = [command, "--checkpoint", str(path), "--checkpoint-sha256", "1" * 64, *extra]
        assert cli.main(argv) == 1
        assert "pinned SHA-256" in capsys.readouterr().err
    selection = {"checkpoint": {"checkpoint_sha256": digest}}
    assert cli.checkpointPin(None, selection) == digest
    assert cli.checkpointPin(digest, selection) == digest
    assert cli.checkpointPin(digest) == digest and cli.checkpointPin(None) is None
    with pytest.raises(ValueError, match="differs from the selected checkpoint"):
        cli.checkpointPin("1" * 64, selection)
