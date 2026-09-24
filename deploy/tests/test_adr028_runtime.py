"""ADR-028 Deploy-Runtime regressions: supervised retention, per-role secrets, images.

Source/unit level only: no Docker daemon, Compose CLI, stores or long-lived servers.
"""

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from deploy import entrypoint, manage, supervise, volume_init

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
BACKEND_IMAGE = "${NANFO_BACKEND_IMAGE:?Initialize configuration}"
LONG_RUNNING_WORKERS = {
    "network-outbox-worker", "simulation-worker", "report-worker", "alert-worker",
    "execution-worker", "autonomy-worker", "stream-retention", "telemetry-retention",
}


def compose(name="compose.yaml"):
    return yaml.safe_load((DEPLOY / name).read_text())


def mounts(service):
    return [value if isinstance(value, str) else f"{value['source']}:{value['target']}" for value in service.get("volumes", [])]


# --- Task 1: supervised retention services, explicit APP_ENV / role, heartbeat ---

def test_every_backend_service_states_app_env_and_least_privilege_role():
    services = compose()["services"]
    backend = {name: svc for name, svc in services.items() if svc.get("image") == BACKEND_IMAGE}
    assert LONG_RUNNING_WORKERS | {"api", "maintenance", "initialize", "volume-init"} <= set(backend)
    for name, service in backend.items():
        environment = service["environment"]
        assert environment["APP_ENV"] == "production", name
        expected = "api" if name in {"api", "initialize", "secret-rotation"} else "worker"
        assert environment["NANFO_SERVICE_ROLE"] == expected, name


def test_secret_volumes_are_split_by_role():
    services = compose()["services"]
    for name, service in services.items():
        role = service.get("environment", {}).get("NANFO_SERVICE_ROLE")
        secret_mounts = [m for m in mounts(service) if m.split(":")[1:2] == ["/run/secrets"]]
        if name in {"initialize", "secret-rotation"}:
            assert secret_mounts == ["init_secrets:/run/secrets:ro"]
        elif role == "api":
            assert secret_mounts == ["runtime_secrets_api:/run/secrets:ro"]
        elif role == "worker" and name != "volume-init":
            assert secret_mounts == ["runtime_secrets_worker:/run/secrets:ro"], name
        assert not any(m.startswith("runtime_secrets:") for m in mounts(service))
    assert "runtime_secrets" not in compose()["volumes"]
    assert {"runtime_secrets_api", "runtime_secrets_worker", "execution_secrets", "lab_secrets",
            "stream_archive"} <= set(compose()["volumes"])
    # Only the execution worker (and the lab overlay) receive the mailbox HMAC key (C15).
    holders = {name for name, svc in services.items() if any("execution_secrets:" in m for m in mounts(svc))}
    assert holders == {"execution-worker", "volume-init"}
    execution = services["execution-worker"]["environment"]
    assert execution["NANFO_LAB_COMMAND_KEY_FILE"] == "/run/nanfo-lab-key/lab_command_key"
    assert execution["NANFO_UMASK"] == "027"
    assert all("NANFO_UMASK" not in svc.get("environment", {}) for name, svc in services.items() if name != "execution-worker")


def test_heartbeat_setting_matches_the_name_the_backend_reads():
    text = (DEPLOY / "compose.yaml").read_text()
    assert "NANFO_WORKER_HEARTBEAT_PATH" not in text
    assert "NANFO_WORKER_HEARTBEAT_PATH" not in (DEPLOY / "README.md").read_text()
    assert compose()["x-environment"]["WORKER_HEARTBEAT_PATH"] == "/run/nanfo/heartbeat.json"
    health = (ROOT / "backend/app/core/runtime_health.py").read_text()
    assert "settings.WORKER_HEARTBEAT_PATH" in health and "NANFO_WORKER_HEARTBEAT_PATH" not in health


@pytest.mark.parametrize("name,child,volume", [
    ("stream-retention", ["python", "-m", "scripts.stream_retention", "schedule"],
     "stream_archive:/var/lib/nanfo/stream-archive"),
    ("telemetry-retention", ["python", "scripts/telemetry_retention.py", "apply", "--loop",
                             "--archive-root", "/var/lib/nanfo/telemetry-archive"],
     "telemetry_archive:/var/lib/nanfo/telemetry-archive"),
])
def test_supervised_retention_services_are_hardened_core_services(name, child, volume):
    service = compose()["services"][name]
    assert name in manage.SERVICES and name in manage.APPLICATION
    assert "profiles" not in service
    assert service["command"] == ["python", "/opt/nanfo/deploy/supervise.py", "run", "--loop", name, "--", *child]
    assert service["healthcheck"]["test"] == ["CMD", "python", "/opt/nanfo/deploy/supervise.py", "check", "--loop", name]
    assert service["restart"] == "unless-stopped" and service["init"] is True
    assert service["user"] == "10001:10001" and service["read_only"] is True
    assert service["cap_drop"] == ["ALL"] and not service.get("cap_add")
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["pids_limit"] and service["mem_limit"] and service["cpus"]
    assert mounts(service) == ["runtime_secrets_worker:/run/secrets:ro", volume]
    environment = service["environment"]
    if name == "stream-retention":
        assert environment["NANFO_STREAM_ARCHIVE_ROOT"] == "/var/lib/nanfo/stream-archive"
        for suffix in ("INTERVAL_SECONDS", "MAX_ENTRIES", "MIN_AGE_SECONDS", "DLQ_MIN_AGE_SECONDS",
                       "MIN_FREE_BYTES", "MAX_REFUSALS"):
            assert f"NANFO_STREAM_RETENTION_{suffix}" in environment
    else:
        assert environment["NANFO_TELEMETRY_RETENTION_DSN_FROM_SECRETS"] == "true"
        assert "TELEMETRY_RETENTION_DSN" not in environment
        assert "NANFO_TELEMETRY_RETENTION_INTERVAL_SECONDS" in environment
        assert "NANFO_TELEMETRY_RETENTION_MIN_AGE_DAYS" in environment


def test_archive_volumes_are_private_to_the_service_uid():
    assert volume_init.LAYOUT["stream_archive"] == (10001, 10001, 0o700)
    assert volume_init.LAYOUT["telemetry_archive"] == (10001, 10001, 0o700)
    assert "stream_archive" in manage.VOLUMES
    services = compose()["services"]
    assert "stream_archive:/volumes/stream_archive" in services["volume-init"]["volumes"]
    writers = {name for name, svc in services.items() if any(m.startswith("stream_archive:/var") for m in mounts(svc))}
    assert writers == {"stream-retention"}


def test_every_long_running_service_restarts_on_nonzero_exit():
    for name, service in compose()["services"].items():
        if "profiles" in service or name == "volume-init":
            assert service.get("restart", "no") == "no" or name == "volume-init"
        else:
            assert service["restart"] == "unless-stopped", name


def test_owner_progress_markers_still_exist():
    # Tripwire: the supervisor's progress detection is coupled to these owner outputs.
    worker = (ROOT / "backend/app/modules/telemetry/retention_worker.py").read_text()
    assert f'"{supervise.TELEMETRY_PASS_COMPLETED}"' in worker
    schedule = (ROOT / "backend/scripts/stream_retention.py").read_text()
    assert "mode='schedule'" in schedule and "'status': 'refused' if refused else 'ok'" in schedule


def child(code):
    return [sys.executable, "-c", code]


def test_supervisor_relays_output_and_refreshes_heartbeat_only_on_completed_cycles(tmp_path):
    environ = {"WORKER_HEARTBEAT_PATH": str(tmp_path / "heartbeat.json")}
    output = []

    class Sink:
        def write(self, value):
            output.append(value)

        def flush(self):
            pass

    writes = []
    original = supervise.write_heartbeat

    def record(path, pid, **kwargs):
        writes.append(pid)
        original(path, pid, **kwargs)

    supervise.write_heartbeat = record
    try:
        code = supervise.run("stream-retention", child(
            "import json; print(json.dumps({'mode':'schedule','status':'refused'}));"
            "print('noise'); print(json.dumps({'mode':'schedule','status':'ok'}))"
        ), environ=environ, stdout=Sink())
    finally:
        supervise.write_heartbeat = original
    assert code == 0
    assert b"".join(output).count(b"\n") == 3
    # One start record plus exactly one completed cycle.
    assert len(writes) == 2 and len(set(writes)) == 1
    record = json.loads((tmp_path / "heartbeat.json.stream-retention").read_text())
    assert set(record) == {"pid", "start", "progress"} and record["pid"] == writes[0]


@pytest.mark.parametrize("code,expected", [("raise SystemExit(3)", 3), ("import os,signal; os.kill(os.getpid(), signal.SIGKILL)", 137)])
def test_supervisor_returns_child_status_so_restart_policy_applies(tmp_path, code, expected):
    environ = {"WORKER_HEARTBEAT_PATH": str(tmp_path / "heartbeat.json")}
    assert supervise.run("stream-retention", child(code), environ=environ, stdout=open(os.devnull, "wb")) == expected


def test_supervisor_refuses_bad_configuration_before_spawning(tmp_path):
    with pytest.raises(ValueError):
        supervise.run("stream-retention", child("pass"), environ={"WORKER_HEARTBEAT_PATH": "relative"})
    with pytest.raises(KeyError):
        supervise.run("telemetry-retention", child("pass"), environ={"WORKER_HEARTBEAT_PATH": str(tmp_path / "h")})


def test_supervisor_forwards_sigterm_and_exits_with_child_status(tmp_path):
    script = tmp_path / "child.py"
    script.write_text(
        "import signal, sys, time\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n"
        "sys.exit(9)\n"
    )
    environment = {**os.environ, "WORKER_HEARTBEAT_PATH": str(tmp_path / "hb"), "PYTHONPATH": str(ROOT)}
    process = subprocess.Popen(
        [sys.executable, str(DEPLOY / "supervise.py"), "run", "--loop", "stream-retention", "--", sys.executable, str(script)],
        stdout=subprocess.PIPE, env=environment,
    )
    try:
        assert process.stdout.readline() == b"ready\n"
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def heartbeat(path, pid, progress):
    path.write_text(json.dumps({"pid": pid, "start": supervise.process_start(pid), "progress": progress}))


@pytest.mark.parametrize("loop,environ,limit", [
    ("stream-retention", {}, 300 + 30 + 900),
    ("stream-retention", {"NANFO_STREAM_RETENTION_INTERVAL_SECONDS": "60", "NANFO_STREAM_RETENTION_JITTER_SECONDS": "5"}, 965),
    ("telemetry-retention", {"NANFO_TELEMETRY_RETENTION_INTERVAL_SECONDS": "3600"}, 4800),
])
def test_probe_accepts_live_fresh_record_and_rejects_stale_dead_or_reused(tmp_path, loop, environ, limit):
    environ = {**environ, "WORKER_HEARTBEAT_PATH": str(tmp_path / "hb.json")}
    path = tmp_path / f"hb.json.{loop}"
    now = time.monotonic()
    clock = lambda: now  # noqa: E731
    assert supervise.check(loop, environ=environ, clock=clock)["ready"] is False  # missing
    heartbeat(path, os.getpid(), now - limit + 1)
    assert supervise.check(loop, environ=environ, clock=clock) == {"ready": True, "checks": {"heartbeat_" + loop: "ok"}}
    heartbeat(path, os.getpid(), now - limit - 1)
    assert supervise.check(loop, environ=environ, clock=clock)["ready"] is False  # stale
    record = {"pid": os.getpid(), "start": "0", "progress": now}
    path.write_text(json.dumps(record))
    assert supervise.check(loop, environ=environ, clock=clock)["ready"] is False  # PID reused
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    path.write_text(json.dumps({"pid": dead.pid, "start": "1", "progress": now}))
    assert supervise.check(loop, environ=environ, clock=clock)["ready"] is False
    path.write_text("{" * 2000)
    assert supervise.check(loop, environ=environ, clock=clock)["ready"] is False


# --- Task 2: per-role entrypoint allowlists, staging, Redis ACL ---

def secret(root, name, value, mode=0o400):
    path = root / name
    path.write_text(value + "\n")
    path.chmod(mode)
    return path


@pytest.fixture
def secret_root(tmp_path):
    root = tmp_path / "secrets"
    root.mkdir()
    for name in ("postgres_runtime_password", "redis_password", "neo4j_password"):
        secret(root, name, name.replace("_", "-") + "-0123456789abcdef")
    return root


def base_environment(role):
    return {"APP_ENV": "production", "NANFO_SERVICE_ROLE": role, "POSTGRES_HOST": "postgres",
            "POSTGRES_PORT": "5432", "POSTGRES_DB": "nanfo", "POSTGRES_USER": "nanfo_runtime"}


def test_api_role_loads_signing_key_and_only_unexpired_previous_keys(secret_root):
    secret(secret_root, "jwt_secret", "j" * 16 + "0123456789abcdef")
    secret(secret_root, "jwt_previous_secrets", f"{2000}:{'a' * 64},{1000}:{'b' * 64}")
    environ = {**base_environment("api"), "JWT_SECRET_KEY": "ambient", "JWT_PREVIOUS_SECRET_KEYS": "ambient-old"}
    assert entrypoint.prepare(environ, secret_root=secret_root, now=1500) == 0o077
    assert environ["JWT_SECRET_KEY"] == "j" * 16 + "0123456789abcdef"
    assert environ["JWT_PREVIOUS_SECRET_KEYS"] == "a" * 64
    assert environ["POSTGRES_PASSWORD"].startswith("postgres-runtime")
    environ = base_environment("api")
    entrypoint.prepare(environ, secret_root=secret_root, now=2500)
    assert "JWT_PREVIOUS_SECRET_KEYS" not in environ


def test_worker_role_never_receives_or_tolerates_jwt_keys(secret_root):
    environ = {**base_environment("worker"), "JWT_SECRET_KEY": "ambient-must-vanish"}
    entrypoint.prepare(environ, secret_root=secret_root)
    assert "JWT_SECRET_KEY" not in environ and environ["REDIS_PASSWORD"]
    secret(secret_root, "jwt_secret", "j" * 32)
    with pytest.raises(ValueError, match="must not receive"):
        entrypoint.prepare(base_environment("worker"), secret_root=secret_root)


@pytest.mark.parametrize("missing", ["NANFO_SERVICE_ROLE", "APP_ENV"])
def test_role_and_environment_must_be_explicit(secret_root, missing):
    environ = base_environment("worker")
    environ.pop(missing)
    with pytest.raises(ValueError, match="Explicit"):
        entrypoint.prepare(environ, secret_root=secret_root)
    with pytest.raises(ValueError):
        entrypoint.prepare({**base_environment("admin")}, secret_root=secret_root)


def test_secret_files_must_be_owner_only_single_link(secret_root):
    (secret_root / "redis_password").chmod(0o440)
    with pytest.raises(ValueError):
        entrypoint.prepare(base_environment("worker"), secret_root=secret_root)
    (secret_root / "redis_password").chmod(0o400)
    os.link(secret_root / "redis_password", secret_root / "hardlink")
    with pytest.raises(ValueError):
        entrypoint.prepare(base_environment("worker"), secret_root=secret_root)


def test_telemetry_retention_dsn_is_derived_only_on_request(secret_root):
    environ = {**base_environment("worker"), "NANFO_TELEMETRY_RETENTION_DSN_FROM_SECRETS": "true",
               "TELEMETRY_RETENTION_DSN": "postgresql+asyncpg://attacker@elsewhere/db"}
    entrypoint.prepare(environ, secret_root=secret_root)
    assert environ["TELEMETRY_RETENTION_DSN"] == (
        "postgresql+asyncpg://nanfo_runtime:postgres-runtime-password-0123456789abcdef@postgres:5432/nanfo"
    )
    assert "NANFO_TELEMETRY_RETENTION_DSN_FROM_SECRETS" not in environ
    environ = {**base_environment("worker"), "TELEMETRY_RETENTION_DSN": "postgresql://ambient"}
    entrypoint.prepare(environ, secret_root=secret_root)
    assert "TELEMETRY_RETENTION_DSN" not in environ
    with pytest.raises(ValueError):
        entrypoint.prepare({**base_environment("worker"), "NANFO_TELEMETRY_RETENTION_DSN_FROM_SECRETS": "1"},
                           secret_root=secret_root)
    with pytest.raises(ValueError):
        entrypoint.prepare({**base_environment("worker"), "POSTGRES_HOST": "evil@host",
                            "NANFO_TELEMETRY_RETENTION_DSN_FROM_SECRETS": "true"}, secret_root=secret_root)


def test_path_consumed_key_files_are_validated_and_umask_is_allowlisted(secret_root, tmp_path):
    key = tmp_path / "lab_command_key"
    key.write_text("k" * 64)
    key.chmod(0o400)
    environ = {**base_environment("worker"), "NANFO_LAB_COMMAND_KEY_FILE": str(key), "NANFO_UMASK": "027"}
    assert entrypoint.prepare(environ, secret_root=secret_root) == 0o027
    key.chmod(0o440)
    with pytest.raises(ValueError, match="Key file"):
        entrypoint.prepare({**environ}, secret_root=secret_root)
    key.chmod(0o400)
    short = tmp_path / "short"
    short.write_text("k" * 8)
    short.chmod(0o400)
    with pytest.raises(ValueError):
        entrypoint.prepare({**environ, "NANFO_RECEIVER_HEALTH_PUBLIC_KEY_FILE": str(short)}, secret_root=secret_root)
    with pytest.raises(KeyError):
        entrypoint.prepare({**environ, "NANFO_UMASK": "000"}, secret_root=secret_root)


@pytest.fixture
def volume_tree(tmp_path, monkeypatch):
    source, volumes = tmp_path / "source", tmp_path / "volumes"
    source.mkdir()
    volumes.mkdir()
    for name in volume_init.LAYOUT:
        (volumes / name).mkdir()
    for name in volume_init.SOURCE_SECRETS:
        (source / name).write_text(f"{name}-value-0123456789abcdef\n")
        (source / name).chmod(0o600)
    owners = {}

    def chown(path, uid, gid):
        owners[Path(path).name] = (uid, gid)

    def fchown(fd, uid, gid):
        owners[os.readlink(f"/proc/self/fd/{fd}")] = (uid, gid)

    return source, volumes, owners, chown, fchown


def test_fresh_staging_splits_role_volumes_and_keeps_the_receiver_private_key_out(volume_tree):
    source, volumes, owners, chown, fchown = volume_tree
    volume_init.initialize(source=source, volumes=volumes, chown=chown, fchown=fchown)
    staged = {name: {path.name for path in (volumes / name).iterdir()} for name in volume_init.STAGING}
    assert staged["runtime_secrets_api"] == {"postgres_runtime_password", "redis_password", "neo4j_password",
                                             "jwt_secret", "receiver_health_public_key.pem"}
    assert staged["runtime_secrets_worker"] == {"postgres_runtime_password", "redis_password", "neo4j_password",
                                                "receiver_health_public_key.pem"}
    assert staged["execution_secrets"] == staged["lab_secrets"] == {"lab_command_key"}
    assert "jwt_secret" in staged["init_secrets"] and "redis_admin_password" in staged["init_secrets"]
    assert all("receiver_health_private_key.pem" not in names for names in staged.values())
    assert owners["lab_secrets"] == (0, 0) and owners["lab_output"] == (0, 10001)
    assert owners[str(volumes / "lab_secrets/lab_command_key")] == (0, 0)
    assert owners[str(volumes / "execution_secrets/lab_command_key")] == (10001, 10001)
    for directory in staged:
        for name in staged[directory]:
            assert stat.S_IMODE((volumes / directory / name).stat().st_mode) == 0o400
    assert stat.S_IMODE((volumes / "lab_commands").stat().st_mode) == 0o750


def test_fresh_staging_refuses_nonempty_volume_or_unexpected_sources(volume_tree):
    source, volumes, _, chown, fchown = volume_tree
    (source / "extra").write_text("x")
    (source / "extra").chmod(0o600)
    with pytest.raises(ValueError, match="allowlist"):
        volume_init.initialize(source=source, volumes=volumes, chown=chown, fchown=fchown)
    (source / "extra").unlink()
    (volumes / "reports" / "evidence").write_text("keep")
    with pytest.raises(ValueError, match="nonempty"):
        volume_init.initialize(source=source, volumes=volumes, chown=chown, fchown=fchown)
    assert (volumes / "reports" / "evidence").read_text() == "keep"


def test_restage_replaces_atomically_and_removes_optional_previous_keys(volume_tree, monkeypatch):
    source, volumes, _, chown, fchown = volume_tree
    volume_init.initialize(source=source, volumes=volumes, chown=chown, fchown=fchown)
    identity = (os.getuid(), os.getgid())
    monkeypatch.setattr(volume_init, "LAYOUT", {name: (*identity, mode) for name, (_, _, mode) in volume_init.LAYOUT.items()})
    before = (volumes / "runtime_secrets_worker/redis_password").stat().st_ino
    (source / "redis_password").chmod(0o600)
    (source / "redis_password").write_text("rotated-redis-password-0123456789\n")
    volume_init.restage("redis_password", source=source, volumes=volumes, fchown=fchown)
    for holder in ("init_secrets", "runtime_secrets_api", "runtime_secrets_worker"):
        path = volumes / holder / "redis_password"
        assert path.read_text() == "rotated-redis-password-0123456789\n"
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert (volumes / "runtime_secrets_worker/redis_password").stat().st_ino != before
    assert not [p for p in volumes.rglob(".*restage*")]
    (source / "jwt_previous_secrets").write_text(f"{int(time.time()) + 900}:{'a' * 64}\n")
    (source / "jwt_previous_secrets").chmod(0o600)
    volume_init.restage("jwt_previous_secrets", source=source, volumes=volumes, fchown=fchown)
    assert (volumes / "runtime_secrets_api/jwt_previous_secrets").exists()
    assert not (volumes / "runtime_secrets_worker/jwt_previous_secrets").exists()
    (source / "jwt_previous_secrets").unlink()
    volume_init.restage("jwt_previous_secrets", source=source, volumes=volumes, fchown=fchown)
    assert not (volumes / "runtime_secrets_api/jwt_previous_secrets").exists()
    with pytest.raises(ValueError):
        volume_init.restage("unknown", source=source, volumes=volumes, fchown=fchown)
    (source / "jwt_secret").unlink()
    with pytest.raises(ValueError, match="Required"):
        volume_init.restage("jwt_secret", source=source, volumes=volumes, fchown=fchown)


def test_restage_refuses_unexpected_volume_layout(volume_tree):
    source, volumes, _, chown, fchown = volume_tree
    volume_init.initialize(source=source, volumes=volumes, chown=chown, fchown=fchown)
    # Test directories are not owned by 10001; production layout must match exactly.
    with pytest.raises(ValueError, match="layout"):
        volume_init.restage("redis_password", source=source, volumes=volumes, fchown=fchown)


def test_manage_secret_inventory_matches_volume_staging():
    assert set(manage.SECRET_NAMES) == set(volume_init.SOURCE_SECRETS)
    assert set(manage.VOLUMES) == set(compose()["volumes"])
    assert set(volume_init.LAYOUT) == set(manage.VOLUMES) - {"postgres_data", "redis_data", "neo4j_data"}
    assert set(entrypoint.ROLE_SECRETS["api"]) - set(entrypoint.ROLE_SECRETS["worker"]) == {"JWT_SECRET_KEY"}


def run_redis_entrypoint(tmp_path, app, admin):
    secrets_dir, runtime = tmp_path / "run-secrets", tmp_path / "run-redis"
    secrets_dir.mkdir()
    runtime.mkdir()
    (secrets_dir / "redis_password").write_text(app + "\n")
    (secrets_dir / "redis_admin_password").write_text(admin + "\n")
    script = (DEPLOY / "redis-entrypoint.sh").read_text()
    assert "exec gosu redis redis-server /run/redis/redis.conf" in script
    script = script.replace("/run/secrets/", f"{secrets_dir}/").replace("/run/redis/", f"{runtime}/")
    script = script.replace("chown redis:redis", ": chown").replace("exec gosu redis redis-server", "exec cat")
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=10)


def test_redis_acl_disables_default_and_stores_only_password_hashes(tmp_path):
    app, admin = "a" * 40, "b" * 40
    result = run_redis_entrypoint(tmp_path, app, admin)
    assert result.returncode == 0, result.stderr
    config = result.stdout
    assert app not in config and admin not in config and "requirepass" not in config
    lines = config.splitlines()
    assert "user default off resetpass -@all resetkeys resetchannels" in lines
    assert f"user nanfo on #{hashlib.sha256(app.encode()).hexdigest()} ~* &* +@all -@dangerous +info +client|setname +client|id" in lines
    assert f"user nanfo-admin on #{hashlib.sha256(admin.encode()).hexdigest()} ~* &* +@all" in lines
    assert "maxmemory-policy noeviction" in lines and "appendfsync always" in lines


@pytest.mark.parametrize("app,admin", [("short", "b" * 40), ("a" * 40 + "\nuser x on", "b" * 40), ("c" * 40, "c" * 40)])
def test_redis_entrypoint_refuses_unsafe_or_shared_passwords(tmp_path, app, admin):
    assert run_redis_entrypoint(tmp_path, app, admin).returncode != 0


def test_redis_entrypoint_is_baked_and_no_runtime_file_comes_from_the_checkout():
    services = compose()["services"]
    redis = services["redis"]
    assert redis["image"] == "${NANFO_REDIS_IMAGE:?Initialize configuration}"
    assert redis["build"]["dockerfile"] == "deploy/Dockerfile.redis" and "entrypoint" not in redis
    assert mounts(redis) == ["redis_data:/data"]
    assert redis["secrets"] == ["redis_password", "redis_admin_password"]
    assert "--user nanfo-admin" in redis["healthcheck"]["test"][1]
    dockerfile = (DEPLOY / "Dockerfile.redis").read_text()
    assert "COPY deploy/redis-entrypoint.sh" in dockerfile
    for path in DEPLOY.glob("compose*.yaml"):
        text = path.read_text()
        assert "source: ./" not in text and "file: ./" not in text and ":/deploy/" not in text, path.name
        assert "configs:" not in text, path.name
    assert compose()["x-environment"]["REDIS_USERNAME"] == "nanfo"


# --- Task 3: pinned current images ---

def test_store_images_are_current_pinned_multi_arch_indexes():
    postgres = compose()["services"]["postgres"]["image"]
    assert postgres == "postgres:17.11-bookworm@sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652"
    assert "FROM redis:7.4.11-bookworm@sha256:c6eabf748fc7a61dbb5a705c78bcf3d6377b1127a97d0ce965c11c44ba46896f" in (
        DEPLOY / "Dockerfile.redis").read_text()
    neo4j = (DEPLOY / "Dockerfile.neo4j").read_text()
    assert "FROM neo4j:5.26.31-community-trixie@sha256:ab3aafb0020e6fed65bb2b59f7db1fabd7ee0568c4da46f3cc3b8fad77801d61" in neo4j
    assert "bullseye" not in neo4j.split("FROM", 1)[1].splitlines()[0]
    major, minor, patch = (int(part) for part in re.search(r"redis:(\d+)\.(\d+)\.(\d+)", (DEPLOY / "Dockerfile.redis").read_text()).groups())
    assert (major, minor) == (7, 4) and patch >= 6  # CVE-2025-49844
    assert manage.NEO4J_TAG == "5.26.31" and manage.REDIS_TAG == "7.4.11"


# --- Task 8: PostgreSQL connection budget ---

def test_postgres_connection_budget_covers_every_pool():
    services = compose()["services"]
    postgres = services["postgres"]
    command = postgres["command"]
    assert command[:2] == ["postgres", "-c"] and command[2].startswith("max_connections=")
    limit = int(command[2].split("=", 1)[1])
    config = (ROOT / "backend/app/core/config.py").read_text()
    pool = int(re.search(r"DB_POOL_SIZE: int = Field\(default=(\d+)", config).group(1))
    overflow = int(re.search(r"DB_MAX_OVERFLOW: int = Field\(default=(\d+)", config).group(1))
    long_running = {name for name, svc in services.items()
                    if svc.get("image") == BACKEND_IMAGE and "profiles" not in svc and name != "stream-retention"}
    # api2 + fleet overlays, SQLAlchemy default pool for telemetry retention (5 + 10),
    # six concurrent worker health probes, one-shot maintenance/rotation, superuser slots.
    budget = (len(long_running) + 2) * (pool + overflow) + 15 + 6 + 10 + 3
    assert budget <= limit == 200
    assert postgres["pids_limit"] >= limit + 50
