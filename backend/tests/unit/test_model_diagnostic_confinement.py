"""Actual Linux syscall proof, in a child so pytest itself stays unconfined."""

import json
import os
from pathlib import Path
import subprocess


def test_same_uid_filesystem_and_control_syscalls_are_confined(tmp_path):
    backend = Path(__file__).resolve().parents[2]
    interpreter = backend.parent / "ai-engine/.venv/bin/python"
    stage = tmp_path / "stage"
    stage.mkdir()
    scratch = stage / "scratch"
    scratch.mkdir()
    checkpoint = stage / "checkpoint.ptz"
    checkpoint.write_bytes(b"staged evidence")
    canary = tmp_path / "backend-mailbox"
    canary.write_bytes(b"same uid private control file")
    canary.chmod(0o600)
    (scratch / "escape").symlink_to(canary)
    # Attempt through a pre-existing hardlink as well as a symlink into the sandbox.
    os.link(checkpoint, tmp_path / "checkpoint-outside")
    program = r'''
import ctypes, errno, json, os, sys, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.frozen_model_diagnostic import confine_filesystem, deny_control_access
stage, scratch, canary = map(Path, sys.argv[2:])
assert canary.stat().st_uid == os.geteuid()
assert canary.read_bytes() == b"same uid private control file"
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
os.chdir(scratch)
deny_control_access()
abi = confine_filesystem(stage, scratch)
denied = []
def reject(name, number, *args, allowed=(errno.EACCES, errno.EPERM)):
    ctypes.set_errno(0)
    result = libc.syscall(number, *args)
    assert result == -1 and ctypes.get_errno() in allowed, (name, result, ctypes.get_errno())
    denied.append(name)
def path(value):
    return ctypes.c_char_p(os.fsencode(value))
for target in (canary, scratch / "escape", stage.parent / "checkpoint-outside",
               Path(sys.argv[1]) / "scripts/frozen_model_diagnostic.py",
               Path('/proc/self/environ'), Path('/proc/self/mem'),
               Path('/proc/self/root') / str(canary).lstrip('/')):
    reject('read:' + target.name, 257, -100, path(target), os.O_RDONLY, 0)
reject('mailbox_write', 257, -100, path(canary), os.O_WRONLY | os.O_TRUNC, 0)
reject('mailbox_create', 257, -100, path(canary.parent / 'command'), os.O_WRONLY | os.O_CREAT, 0o600)
reject('staged_write', 257, -100, path(stage / 'checkpoint.ptz'), os.O_WRONLY, 0)
reject('staged_truncate', 76, path(stage / 'checkpoint.ptz'), 0)
reject('unlink_control', 87, path(canary))
reject('chmod_control', 90, path(canary), 0o777)
reject('rename_control', 82, path(canary), path(scratch / 'stolen'))
reject('hardlink_control', 86, path(canary), path(scratch / 'hardlink'), allowed=(errno.EACCES, errno.EPERM, errno.EXDEV))
reject('socket_unix', 41, 1, 1, 0)
reject('socket_inet', 41, 2, 1, 0)
reject('execve', 59, path('/usr/bin/true'), 0, 0)
reject('fork', 57)
reject('vfork', 58)
reject('clone_process', 56, 17, 0, 0, 0, 0)
reject('clone3', 435, 0, 0, allowed=(errno.ENOSYS,))
reject('unshare', 272, 0)
reject('io_uring', 425, 1, 0)
reject('pidfd_open', 434, os.getppid(), 0)
reject('signal_parent', 62, os.getppid(), 0)
reject('sysv_shm', 29, 0, 4096, 0o1600)
assert (stage / 'checkpoint.ptz').read_bytes() == b'staged evidence'
(scratch / 'allowed').write_bytes(b'private scratch')
assert (scratch / 'allowed').read_bytes() == b'private scratch'
completed = []
thread = threading.Thread(target=lambda: completed.append(True))
thread.start()
thread.join()
assert completed == [True]
print(json.dumps({'landlock_abi': abi, 'denied': denied, 'scratch_write': True, 'stage_read': True, 'native_thread': True}))
'''
    result = subprocess.run([str(interpreter), "-I", "-B", "-c", program, str(backend), str(stage), str(scratch), str(canary)],
        env={"LANG": "C.UTF-8", "OMP_NUM_THREADS": "1"}, capture_output=True, text=True, timeout=30, check=True)
    evidence = json.loads(result.stdout)
    assert evidence["landlock_abi"] >= 5
    assert len(evidence["denied"]) >= 25
    assert evidence["scratch_write"] and evidence["stage_read"] and evidence["native_thread"]
    assert canary.read_bytes() == b"same uid private control file"
    assert canary.stat().st_mode & 0o777 == 0o600
    assert checkpoint.read_bytes() == b"staged evidence"


def test_missing_landlock_fails_closed(monkeypatch):
    import ctypes
    from types import SimpleNamespace

    import pytest

    from scripts.frozen_model_diagnostic import confine_filesystem

    def syscall(*args):
        return -1

    def prctl(*args):
        raise AssertionError("must not reach restrict when ABI unavailable")

    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: SimpleNamespace(syscall=syscall, prctl=prctl))
    with pytest.raises(ValueError, match="landlock_abi_unavailable"):
        confine_filesystem(Path("/missing"), Path("/missing/scratch"))
