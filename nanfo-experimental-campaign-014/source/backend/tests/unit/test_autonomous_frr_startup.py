"""Startup gates and pinned namespace descriptor behavior without setns."""

import os
from types import SimpleNamespace

import pytest

from emulation.autonomous_namespace import AttachedFRRNetwork, process_identity
from scripts.autonomous_frr_receiver import ReceiverConfig, load_config, publish_new


def test_namespace_attachment_checks_pid_start_and_inode_before_any_command(tmp_path):
    pid = os.getpid()
    ticks, inode = process_identity(pid)
    binding = SimpleNamespace(resource_id="test", run_id="run", namespaces={
        "access1": SimpleNamespace(pid=pid, start_ticks=ticks, netns_inode=inode)})
    attached = AttachedFRRNetwork(binding, lock_directory=tmp_path)
    try:
        assert attached.ownership("test", "run")
        with pytest.raises(BlockingIOError):
            AttachedFRRNetwork(binding, lock_directory=tmp_path)
        with pytest.raises(ValueError, match="command_not_allowed"):
            attached.command("access1", ["sh", "-c", "true"])
        binding.namespaces["access1"].start_ticks += 1
        assert not attached.ownership("test", "run")
        with pytest.raises(ValueError, match="ownership_lost"):
            attached.command("access1", ["ip", "-j", "rule", "show"])
    finally:
        attached.close()


def test_evidence_publisher_never_overwrites_and_loader_requires_explicit_pin(tmp_path):
    path = tmp_path / "evidence.json"
    digest = publish_new(path, {"measurement": "unit-only"})
    assert len(digest) == 64
    with pytest.raises(FileExistsError):
        publish_new(path, {"changed": True})
    with pytest.raises(ValueError):
        load_config(path, "0" * 64)
    with pytest.raises(ValueError):
        ReceiverConfig.model_validate({"execution_mode": "production"})


@pytest.mark.parametrize("failure", ["actor_revoked", "certificate_expired", "recovery_lease_lost"])
def test_native_transport_final_check_after_namespace_reads_before_subprocess(tmp_path, monkeypatch, failure):
    from unittest.mock import Mock
    pid = os.getpid()
    ticks, inode = process_identity(pid)
    binding = SimpleNamespace(resource_id="test", run_id="run", namespaces={
        "access1": SimpleNamespace(pid=pid, start_ticks=ticks, netns_inode=inode)})
    attached = AttachedFRRNetwork(binding, lock_directory=tmp_path)
    subprocess = Mock()
    monkeypatch.setattr("emulation.autonomous_namespace.subprocess.run", subprocess)
    allowed = True
    def namespace_read(*_):
        nonlocal allowed
        allowed = False
        return ticks, inode
    monkeypatch.setattr("emulation.autonomous_namespace.process_identity", namespace_read)
    def final_check():
        if not allowed:
            raise ValueError(failure)
    try:
        with pytest.raises(ValueError, match=failure):
            attached.mutate("access1", ["ip", "route", "del" if failure == "recovery_lease_lost" else "add"], final_check)
        subprocess.assert_not_called()
    finally:
        attached.close()


def test_native_transport_no_reads_after_final_check(tmp_path, monkeypatch):
    pid = os.getpid()
    ticks, inode = process_identity(pid)
    binding = SimpleNamespace(resource_id="test", run_id="run", namespaces={
        "access1": SimpleNamespace(pid=pid, start_ticks=ticks, netns_inode=inode)})
    attached = AttachedFRRNetwork(binding, lock_directory=tmp_path)
    events = []
    def namespace_read(*_):
        events.append("namespace_read")
        return ticks, inode
    def final_check():
        events.append("checkpoint")
    def run(*args, **kwargs):
        assert events[-1] == "checkpoint"
        events.append("subprocess")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    monkeypatch.setattr("emulation.autonomous_namespace.process_identity", namespace_read)
    monkeypatch.setattr("emulation.autonomous_namespace.subprocess.run", run)
    try:
        attached.mutate("access1", ["ip", "rule", "add"], final_check)
        assert events == ["namespace_read", "checkpoint", "subprocess"]
    finally:
        attached.close()
