"""ADR-028 tasks 11-13: passive observer/clock moved to the backend, fixed-argument helper."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.canonical import canonical_sha256
from app.modules.autonomy.artifact_io import EvidenceError
from app.modules.autonomy.experimental import native_qualification_clock, passive_observer
from scripts import nanfo_proc_timens as helper

ROOT = Path(__file__).resolve().parents[3]


def test_emulation_paths_are_host_only_aliases_of_the_backend_modules():
    import emulation.native_qualification_clock as clock_shim
    import emulation.passive_observer as observer_shim

    assert observer_shim is passive_observer
    assert clock_shim is native_qualification_clock
    result = subprocess.run([sys.executable, "-B", "-m", "emulation.passive_observer", "--help"],
                            capture_output=True, text=True, timeout=60, cwd=ROOT,
                            env=dict(os.environ, PYTHONPATH=f"{ROOT / 'backend'}:{ROOT}"))
    assert result.returncode == 0 and "--admission" in result.stdout


def test_app_code_no_longer_imports_scripts_and_canonical_hash_is_byte_identical():
    from scripts.frozen_model_diagnostic import canonical_hash

    for path in (ROOT / "backend/app/modules/autonomy/experimental").glob("*.py"):
        assert "from scripts" not in path.read_text() and "import scripts" not in path.read_text(), path
    assert passive_observer.canonical_hash is canonical_sha256
    for value in ({"b": [1, 2.5, None, True], "a": "\u00e9\u2603", "c": {"z": {}, "y": []}},
                  {"frames": [{"request": {"seed": 2**62}, "response": {"ok": True}}]}, [], "x"):
        assert canonical_hash(value) == canonical_sha256(value)
    with pytest.raises(ValueError):
        canonical_sha256({"x": float("nan")})


def test_privileged_helper_takes_no_arguments_and_one_integer_pid_on_stdin():
    out = io.StringIO()
    assert helper.main(["/proc/1/timens_offsets"], stdin=io.StringIO("1\n"), stdout=out) == 2
    for raw in ("", "0\n", "-1\n", "1 2\n", "../1\n", "abc\n", "99999999\n", "4194305\n", "1\n\n"):
        out = io.StringIO()
        assert helper.main([], stdin=io.StringIO(raw), stdout=out) == 1, raw
        assert json.loads(out.getvalue()) == {"error": "unavailable"}


@pytest.mark.skipif(not Path("/proc/self/timens_offsets").exists(), reason="kernel without time namespaces")
def test_privileged_helper_reports_only_the_fixed_time_namespace_fields():
    out = io.StringIO()
    assert helper.main([], stdin=io.StringIO(f"{os.getpid()}\n"), stdout=out) == 0
    value = json.loads(out.getvalue())
    assert value["pid"] == os.getpid()
    assert value["time_namespace"] == os.readlink("/proc/self/ns/time")
    assert set(value["timens_offsets"]) == {"monotonic", "boottime"}


def test_observer_invokes_the_fixed_helper_with_exact_argv_and_validates_output(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=json.dumps({"pid": 4242, "time_namespace": "time:[7]",
                                                  "timens_offsets": {"monotonic": [0, 0], "boottime": [0, 0]}}))

    monkeypatch.setattr(passive_observer.subprocess, "run", run)
    monkeypatch.delenv("NANFO_PASSIVE_PROC_SUDO", raising=False)
    with pytest.raises(PermissionError):
        passive_observer.privileged_proc_timens(4242)
    monkeypatch.setenv("NANFO_PASSIVE_PROC_SUDO", "1")
    namespace, offsets = passive_observer.privileged_proc_timens(4242)
    assert namespace == "time:[7]" and offsets == {"monotonic": (0, 0), "boottime": (0, 0)}
    argv, kwargs = calls[0]
    assert argv == ["sudo", "-n", passive_observer.PROC_TIMENS_HELPER]
    assert kwargs["input"] == "4242\n" and kwargs["check"] is True and kwargs["timeout"] == 2
    assert "*" not in passive_observer.SUDOERS_LINE and passive_observer.SUDOERS_LINE.endswith(' ""')
    assert "/usr/bin/cat" not in Path(passive_observer.__file__).read_text()
    for pid in (0, -1, True, "4242"):
        with pytest.raises(EvidenceError):
            passive_observer.privileged_proc_timens(pid)
    for bad in ({"pid": 1, "time_namespace": "time:[7]", "timens_offsets": {}},
                {"pid": 4242, "time_namespace": "time:[7]", "timens_offsets": {"monotonic": [0, "0"]}},
                {"pid": 4242, "time_namespace": "time:[7]", "timens_offsets": {}, "extra": 1}):
        monkeypatch.setattr(passive_observer.subprocess, "run",
                            lambda argv, bad=bad, **kwargs: SimpleNamespace(stdout=json.dumps(bad)))
        with pytest.raises(EvidenceError):
            passive_observer.privileged_proc_timens(4242)


def test_process_identity_uses_the_helper_only_after_permission_denial(monkeypatch):
    monkeypatch.setenv("NANFO_PASSIVE_PROC_SUDO", "1")
    real = os.readlink

    def readlink(path, *args, **kwargs):
        if path == "/proc/4242/ns/time":
            raise PermissionError(path)
        return real(path, *args, **kwargs)

    stat = "4242 (lab server) S " + " ".join(["0"] * 18) + " 777 0"
    monkeypatch.setattr(passive_observer.os, "readlink", readlink)
    monkeypatch.setattr(passive_observer.Path, "read_text", lambda self: stat)
    monkeypatch.setattr(passive_observer, "privileged_proc_timens", lambda pid: ("time:[9]", {}))
    assert passive_observer.process_identity(4242) == (777, "time:[9]")
