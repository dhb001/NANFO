"""Read-only ADR018 entrypoint, run only with the operator-pinned AI interpreter.

Only IDs are arguments. All paths and hashes come from protected deployment config.
Frozen source bytes are copied unchanged and the original CLI/loader is executed.
"""

import argparse
import contextlib
import ctypes
import ctypes.util
import errno
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import resource
import stat
import sys
import sysconfig
import tempfile
import time
import uuid

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.autonomy.artifact_io import ArtifactStore, EvidenceError, parse_json
from app.modules.autonomy.model_diagnostic_schemas import ModelDiagnosticRegistry

CONFIG_KEYS = ("NANFO_MODEL_REGISTRY", "NANFO_MODEL_REGISTRY_SHA256", "NANFO_MODEL_ROOT", "NANFO_MODEL_PYTHON")


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_registry():
    if not all(os.environ.get(key) for key in CONFIG_KEYS):
        raise EvidenceError("model_registry_unconfigured")
    path = Path(os.environ["NANFO_MODEL_REGISTRY"])
    root = Path(os.environ["NANFO_MODEL_ROOT"])
    pin = os.environ["NANFO_MODEL_REGISTRY_SHA256"]
    if not path.is_absolute() or not root.is_absolute() or not re.fullmatch(r"[a-f0-9]{64}", pin):
        raise EvidenceError("model_registry_configuration_invalid")
    if path.resolve().is_relative_to(root.resolve()):
        raise EvidenceError("registry_inside_producer_root")
    for component in (path, *path.parents):
        info = component.lstat()
        # A root-owned sticky /tmp is safe for a privately owned child directory.
        sticky_root = component != path and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
        if stat.S_ISLNK(info.st_mode) or (info.st_mode & 0o022 and not sticky_root):
            raise EvidenceError("model_registry_not_protected")
        if info.st_uid not in (0, os.geteuid()):
            raise EvidenceError("model_registry_owner_invalid")
    content = ArtifactStore(str(path.parent)).read(path.name, limit=256 * 1024, sha256=pin)
    return ModelDiagnosticRegistry.model_validate(parse_json(content)), pin, ArtifactStore(str(root))


def select_model(registry, network_id):
    return next((model for model in registry.models if network_id in model.network_ids), None)


def confine_filesystem(stage, scratch):
    """Landlock is inherited by native threads and cannot be relaxed by same-UID code.

    No grants for backend/producer roots, home, /proc/self/{root,fd,mem,environ},
    /run or mailboxes. ABI 5 includes REFER, TRUNCATE and device IOCTL mediation.
    Syscall numbers below are only supported on native Linux x86_64.
    """
    if sys.platform != "linux" or os.uname().machine != "x86_64" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise EvidenceError("diagnostic_landlock_architecture_unsupported")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 5:
        raise EvidenceError("diagnostic_landlock_abi_unavailable")

    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    read_file, read_dir = 1 << 2, 1 << 3
    # All ABI5 filesystem rights handled, including execute/device creation/ioctl.
    ruleset = Ruleset((1 << 16) - 1)
    fd = libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0)
    if fd < 0:
        raise EvidenceError("diagnostic_landlock_create_failed")
    try:
        paths = sysconfig.get_paths()
        readonly = {Path(paths[key]).resolve() for key in ("stdlib", "platstdlib", "purelib", "platlib")}
        readonly.add(stage.resolve())
        # Grant shared-library files, not /usr, /usr/lib or the interpreter's home.
        library_dirs = {Path(path).resolve() for path in ("/lib", "/lib64", "/usr/lib", "/usr/lib64")}
        multiarch = sysconfig.get_config_var("MULTIARCH")
        if multiarch and re.fullmatch(r"[a-zA-Z0-9_-]+", multiarch):
            library_dirs.update({Path("/lib", multiarch).resolve(), Path("/usr/lib", multiarch).resolve()})
        library_dirs.add((Path(sys.base_prefix) / "lib").resolve())
        for directory in library_dirs:
            if directory.is_dir():
                for path in directory.glob("*.so*"):
                    resolved = path.resolve()
                    if resolved.parent in library_dirs and resolved.is_file():
                        readonly.add(resolved)
        for name in ("/etc/ld.so.cache", "/dev/urandom", "/proc/cpuinfo", "/proc/meminfo"):
            path = Path(name)
            if path.exists():
                readonly.add(path)
        scratch = scratch.resolve()
        if not scratch.is_relative_to(stage.resolve()) or scratch == stage.resolve():
            raise EvidenceError("diagnostic_scratch_outside_stage")
        writable = read_file | read_dir | (1 << 1) | (1 << 4) | (1 << 5) | (1 << 7) | (1 << 8) | (1 << 12) | (1 << 13) | (1 << 14)
        for path in sorted(readonly | {scratch}):
            parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                access = writable if path == scratch else read_file | (read_dir if path.is_dir() else 0)
                rule = PathRule(access, parent)
                if libc.syscall(445, fd, 1, ctypes.byref(rule), 0) != 0:
                    raise EvidenceError("diagnostic_landlock_rule_failed")
            finally:
                os.close(parent)
        if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.syscall(446, fd, 0) != 0:
            raise EvidenceError("diagnostic_landlock_restrict_failed")
    finally:
        os.close(fd)
    return abi


def deny_control_access():
    """Linux seccomp applies to native extensions too, not just Python sockets."""
    library = ctypes.util.find_library("seccomp")
    if not library:
        raise EvidenceError("diagnostic_sandbox_unavailable")
    seccomp = ctypes.CDLL(library, use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    class Argument(ctypes.Structure):
        _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_uint),
                    ("datum_a", ctypes.c_uint64), ("datum_b", ctypes.c_uint64)]

    seccomp.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                              ctypes.c_uint, ctypes.POINTER(Argument)]
    ctx = seccomp.seccomp_init(0x7FFF0000)
    if not ctx:
        raise EvidenceError("diagnostic_sandbox_unavailable")
    try:
        for name in ("socket", "socketpair", "connect", "bind", "listen", "accept", "accept4",
                     "execve", "execveat", "fork", "vfork", "ptrace", "process_vm_readv", "process_vm_writev",
                     "kill", "tkill", "tgkill", "rt_sigqueueinfo", "rt_tgsigqueueinfo",
                     "pidfd_open", "pidfd_getfd", "pidfd_send_signal",
                     "io_uring_setup", "mount", "umount2", "pivot_root", "chroot", "setns", "unshare",
                     "fsopen", "fsmount", "move_mount", "open_tree", "mount_setattr",
                     "open_by_handle_at", "name_to_handle_at", "bpf", "perf_event_open", "userfaultfd",
                     "keyctl", "add_key", "request_key", "process_madvise",
                     "shmget", "shmat", "shmctl", "semget", "semop", "semtimedop", "semctl",
                     "msgget", "msgsnd", "msgrcv", "msgctl", "mq_open",
                     "chmod", "fchmod", "fchmodat", "fchmodat2", "chown", "fchown", "lchown", "fchownat",
                     "utime", "utimes", "futimesat", "utimensat", "setxattr", "lsetxattr", "fsetxattr",
                     "removexattr", "lremovexattr", "fremovexattr"):
            number = seccomp.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and seccomp.seccomp_rule_add(ctx, 0x00050000 | errno.EPERM, number, 0) != 0:
                raise EvidenceError("diagnostic_sandbox_unavailable")
        # clone3 has an indirect flags pointer: deny it with ENOSYS so pthreads
        # falls back to clone. Permit clone only for shared-VM native threads.
        number = seccomp.seccomp_syscall_resolve_name(b"clone3")
        if number >= 0 and seccomp.seccomp_rule_add(ctx, 0x00050000 | errno.ENOSYS, number, 0) != 0:
            raise EvidenceError("diagnostic_sandbox_unavailable")
        number = seccomp.seccomp_syscall_resolve_name(b"clone")
        for flag in (0x100, 0x800, 0x10000):  # CLONE_VM, CLONE_SIGHAND, CLONE_THREAD
            argument = Argument(0, 7, flag, 0)  # SCMP_CMP_MASKED_EQ: required bit absent
            if number < 0 or seccomp.seccomp_rule_add_array(ctx, 0x00050000 | errno.EPERM, number, 1, ctypes.byref(argument)) != 0:
                raise EvidenceError("diagnostic_sandbox_unavailable")
        for flag in (0x80, 0x20000, 0x2000000, 0x4000000, 0x8000000, 0x10000000, 0x20000000, 0x40000000):
            argument = Argument(0, 7, flag, flag)  # No namespace creation, even with thread flags.
            if seccomp.seccomp_rule_add_array(ctx, 0x00050000 | errno.EPERM, number, 1, ctypes.byref(argument)) != 0:
                raise EvidenceError("diagnostic_sandbox_unavailable")
        if seccomp.seccomp_load(ctx) != 0:
            raise EvidenceError("diagnostic_sandbox_unavailable")
    finally:
        seccomp.seccomp_release(ctx)


def run(network_id, model_id, checkpoint_id, history_reference):
    if os.geteuid() == 0:
        raise EvidenceError("diagnostic_root_forbidden")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    sys.dont_write_bytecode = True
    registry, pin, store = load_registry()
    model = select_model(registry, network_id)
    if model is None or (model.model_id, model.checkpoint_id) != (model_id, checkpoint_id):
        raise EvidenceError("model_not_registered")
    history = model.histories.get(history_reference)
    if history is None or network_id not in history.network_ids:
        raise EvidenceError("history_not_registered")
    checkpoint = store.referenced(model.checkpoint, limit=16 * 1024**2)
    measured = store.referenced(history.artifact)
    store.referenced(model.benchmark.evidence)
    sources = {}
    for name, digest in model.source_sha256.items():
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*\.py", name):
            raise EvidenceError("model_source_name_invalid")
        sources[name] = store.read(f"{model.source_directory}/{name}", limit=1024**2, sha256=digest,
                                   allow_empty=True)
    if not {"__init__.py", "artifacts.py", "cli.py"} <= sources.keys():
        raise EvidenceError("model_source_incomplete")
    # The parent owns cleanup: the confined child cannot delete read-only evidence.
    with tempfile.TemporaryDirectory(prefix="frozen-", delete=False) as directory:
        root = Path(directory)
        source = root / "source"
        source.mkdir(mode=0o700)
        for name, content in sources.items():
            (source / name).write_bytes(content)
        (root / "checkpoint.ptz").write_bytes(checkpoint)
        (root / "history.json").write_bytes(measured)
        scratch = root / "scratch"
        scratch.mkdir(mode=0o700)
        os.environ.update(HOME=str(scratch), TMPDIR=str(scratch))
        tempfile.tempdir = str(scratch)
        os.chdir(scratch)
        deny_control_access()
        confine_filesystem(root, scratch)
        alias = "_nanfo_diagnostic_frozen"
        spec = importlib.util.spec_from_file_location(alias, source / "__init__.py",
                                                      submodule_search_locations=[str(source)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[alias] = package
        spec.loader.exec_module(package)
        cli = importlib.import_module(f"{alias}.cli")
        artifacts = importlib.import_module(f"{alias}.artifacts")
        # Never replace clientSources/readBundle/torch.load or relax the original checks.
        if artifacts.clientSources() != model.source_sha256:
            raise EvidenceError("model_source_mismatch")
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = cli.main(["infer", "--checkpoint", str(root / "checkpoint.ptz"),
                             "--history", str(root / "history.json")])
        if code != 0:
            raise EvidenceError("frozen_checkpoint_or_history_invalid")
        result = parse_json(output.getvalue().encode())
        manifest, _ = artifacts.readBundle(root / "checkpoint.ptz")
        if manifest.environment_spec["version"] != 4 or manifest.contract["state_dim"] != 16:
            raise EvidenceError("model_contract_incompatible")
        return {key: result[key] for key in (
            "policy_sha256", "checkpoint_weights_sha256", "input_sha256", "contract_hash", "spec_hash",
            "action", "probabilities", "value", "inference_seconds", "artifact_validation_and_inference_seconds", "evidence",
        )} | {
            "model_id": model_id, "checkpoint_id": checkpoint_id, "history_reference": history_reference,
            "registry_sha256": pin, "source_sha256": canonical_hash(model.source_sha256),
            "history_sha256": history.artifact.sha256,
            "action_path": manifest.contract["action_map"][result["action"]],
            "benchmark_status": model.benchmark.status, "benchmark_scope": model.benchmark.scope,
            "benchmark_limitations": model.benchmark.limitations,
            "benchmark_evidence_sha256": model.benchmark.evidence.sha256,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network-id", type=uuid.UUID, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--checkpoint-id", required=True)
    parser.add_argument("--history-reference", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    try:
        result = run(args.network_id, args.model_id, args.checkpoint_id, args.history_reference)
        result["subprocess_seconds"] = time.monotonic() - started
        from app.modules.autonomy.model_diagnostic_schemas import DiagnosticResult
        print(DiagnosticResult.model_validate(result).model_dump_json())
        return 0
    except Exception:  # noqa: BLE001 - never emit source paths, raw history or loader traces
        print('{"error":"frozen_diagnostic_validation_failed"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
