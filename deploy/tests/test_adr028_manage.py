"""ADR-028 manage.py operator commands and the rotation helper (tasks 6, 9, 11, 12).

C23 lab lifecycle, C15/C21 key provisioning, credential rotation (C19/C24), autoheal
and the default state location. Unit level only: every Docker/Compose invocation is
replaced by a recorder; no daemon, store or lab is contacted.
"""

import asyncio
import hashlib
import io
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from deploy import entrypoint, manage, secret_rotation, volume_init

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
DIGEST = "sha256:" + "ab" * 32
NETWORKS = {"NANFO_PROXY_SUBNET": "10.231.7.0/24", "NANFO_PROXY_GATEWAY_IP": "10.231.7.254",
            "NANFO_GATEWAY_SUBNET": "10.231.8.0/24", "NANFO_GATEWAY_BRIDGE_IP": "10.231.8.1"}
HELPER = ("run", "--rm", "--no-deps", "-T", "secret-rotation", "python", "/opt/nanfo/deploy/secret_rotation.py")


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A real ``manage.py init`` state directory; only the Docker probes are stubbed."""
    for key in [*manage.REQUIRED_CONFIG, "NANFO_BOOTSTRAP_EMAIL", "EXECUTION_MODE", "EMULATION_CONTROL_ENABLED",
                "TELEMETRY_RUNTIME_ADAPTER_MODE", "API_REALTIME_DISTRIBUTED", "NANFO_LAB_IMAGE",
                "NANFO_LAB_FROZEN_IMAGE", "NANFO_LAB_FROZEN"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(manage, "run", lambda *args, **kwargs: SimpleNamespace(stdout=""))
    monkeypatch.setattr(manage, "allocate_deployment_networks", lambda count=1: [dict(NETWORKS)])
    monkeypatch.setattr(manage, "require_consistent_schema", lambda *args: "0030")
    path = tmp_path.resolve() / "state"
    with monkeypatch.context() as scoped:
        # `docker volume inspect` of every target volume reports "absent".
        scoped.setattr(manage.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
        manage.generate(path, "nanfo-deploy-unit", 8787, "operator@example.com")
    return path


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    def compose(state, *args, capture=False, files=(), input=None):
        recorded.append(SimpleNamespace(args=args, files=tuple(files), input=input))
        return SimpleNamespace(stdout='{"status": "applied"}')

    monkeypatch.setattr(manage, "compose", compose)
    return recorded


@pytest.fixture
def restore_umask():
    previous = os.umask(0o022)
    os.umask(previous)
    yield
    os.umask(previous)


def initialized(state):
    (state / "initialized.json").write_text("{}")
    return state


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def services(name="compose.yaml"):
    return yaml.safe_load((DEPLOY / name).read_text())["services"]


# --- Task 6: C15/C21 provisioning ---

def test_init_provisions_c15_and_c21_keys_with_the_signing_key_outside_every_mount(state):
    from app.modules.autonomy.health_secret import load_signing_key, load_verify_key

    secrets_dir, receiver = state / "secrets", state / manage.RECEIVER_DIRECTORY
    # volume-init's exact allowlist: the signing key is not among the mounted sources.
    assert {path.name for path in secrets_dir.iterdir()} == volume_init.SOURCE_SECRETS
    assert [path.name for path in receiver.iterdir()] == [manage.RECEIVER_PRIVATE_KEY]
    assert mode(receiver) == 0o700 and mode(receiver / manage.RECEIVER_PRIVATE_KEY) == 0o600
    # The backend C21 loaders accept the generated pair (PKCS#8 private, SPKI public).
    signer = load_signing_key(receiver / manage.RECEIVER_PRIVATE_KEY)
    verifier = load_verify_key(secrets_dir / manage.RECEIVER_PUBLIC_KEY)
    assert signer.key_id == verifier.key_id and verifier.verify(b"receipt", signer.sign(b"receipt"))
    assert b"PRIVATE" not in (secrets_dir / manage.RECEIVER_PUBLIC_KEY).read_bytes()
    # C15: >= 32 random bytes (64 hex characters), owner-only.
    key = (secrets_dir / manage.LAB_COMMAND_KEY).read_bytes()
    assert re.fullmatch(rb"[0-9a-f]{64}", key) and mode(secrets_dir / manage.LAB_COMMAND_KEY) == 0o600
    for path in DEPLOY.glob("compose*.yaml"):
        assert "}/receiver" not in path.read_text(), path.name
    assert manage.load_config(state)["NANFO_PROJECT"] == "nanfo-deploy-unit"


def test_receiver_key_directory_must_stay_private_and_the_key_may_be_removed(state):
    receiver = state / manage.RECEIVER_DIRECTORY
    key = receiver / manage.RECEIVER_PRIVATE_KEY
    key.chmod(0o640)
    with pytest.raises(ValueError, match="private"):
        manage.load_config(state)
    key.chmod(0o600)
    receiver.chmod(0o750)
    with pytest.raises(ValueError, match="private"):
        manage.load_config(state)
    receiver.chmod(0o700)
    key.unlink()  # Installed at the receiver; the deployment host no longer needs it.
    manage.load_config(state)


def test_c21_public_key_reaches_exactly_the_receipt_verifiers():
    base = services()
    path = "/run/secrets/" + manage.RECEIVER_PUBLIC_KEY
    verifiers = {name for name, svc in base.items()
                 if svc.get("environment", {}).get("NANFO_RECEIVER_HEALTH_PUBLIC_KEY_FILE")}
    assert verifiers == {"api", "autonomy-worker", "execution-worker"}
    assert {base[name]["environment"]["NANFO_RECEIVER_HEALTH_PUBLIC_KEY_FILE"] for name in verifiers} == {path}
    for overlay in DEPLOY.glob("compose*.yaml"):
        text = overlay.read_text()
        assert "NANFO_RECEIVER_HEALTH_PRIVATE_KEY_FILE" not in text, overlay.name
        assert "NANFO_RECEIVER_HEALTH_LEGACY_HMAC" not in text, overlay.name
    assert manage.RECEIVER_PUBLIC_KEY in volume_init.STAGING["runtime_secrets_api"][1]
    assert manage.RECEIVER_PUBLIC_KEY in volume_init.STAGING["runtime_secrets_worker"][1]
    assert manage.RECEIVER_PRIVATE_KEY not in volume_init.SOURCE_SECRETS | volume_init.STAGED


def test_bootstrap_password_is_required_only_until_initialization(state):
    (state / "secrets/bootstrap_password").unlink()
    with pytest.raises(FileNotFoundError):
        manage.load_config(state)
    initialized(state)
    manage.load_config(state)
    (state / "secrets/redis_password").unlink()
    with pytest.raises(FileNotFoundError):
        manage.load_config(state)


# --- Task 6: C23 lab overlays and lifecycle ---

def test_successor_lab_has_the_c23_least_privilege_profile():
    lab = services("compose.lab.yaml")["lab"]
    assert "privileged" not in lab and lab["network_mode"] == "none" and lab["profiles"] == ["lab"]
    assert lab["cap_drop"] == ["ALL"] and sorted(lab["cap_add"]) == ["NET_ADMIN", "NET_RAW", "SYS_ADMIN"]
    assert lab["security_opt"] == ["no-new-privileges:true"] and lab["read_only"] is True
    assert lab["image"].startswith("${NANFO_LAB_IMAGE:?") and lab["restart"] == "no"
    for entry in lab["tmpfs"]:
        options = entry.split(":", 1)[1].split(",")
        assert "nosuid" in options and "nodev" in options, entry
    assert lab["volumes"] == ["lab_output:/output", "lab_commands:/commands:ro", "lab_results:/results",
                              "lab_secrets:/run/nanfo-lab-key:ro"]
    assert lab["environment"]["NANFO_LAB_COMMAND_KEY_FILE"] == "/run/nanfo-lab-key/" + volume_init.LAB_KEY
    # Root without DAC_OVERRIDE: owns output/results, reads 0640 commands through group 10001.
    assert lab["group_add"] == ["10001"]
    assert volume_init.LAYOUT["lab_output"] == volume_init.LAYOUT["lab_results"] == (0, 10001, 0o750)
    assert volume_init.LAYOUT["lab_commands"] == (10001, 10001, 0o750)
    assert services()["execution-worker"]["environment"]["NANFO_UMASK"] == "027"
    assert volume_init.LAYOUT["lab_secrets"] == (0, 0, 0o700)
    assert volume_init.STAGING["lab_secrets"] == (0, frozenset({volume_init.LAB_KEY}))
    for forbidden in ("devices", "pid", "ipc", "secrets", "ports", "networks", "user", "privileged"):
        assert forbidden not in lab


def test_frozen_overlay_is_opt_in_privileged_and_receives_no_key_material():
    lab = services("compose.lab.frozen.yaml")["lab"]
    assert lab["privileged"] is True and lab["network_mode"] == "none" and lab["profiles"] == ["lab"]
    assert lab["image"].startswith("${NANFO_LAB_FROZEN_IMAGE:?")
    # Compose itself refuses to render the frozen overlay without the acknowledgement.
    assert lab["labels"]["org.nanfo.lab.frozen-acknowledged"].startswith("${NANFO_LAB_FROZEN:?")
    assert not any(mount.startswith("lab_secrets") for mount in lab["volumes"])
    assert "NANFO_LAB_COMMAND_KEY_FILE" not in lab["environment"]
    # AI-Lab C15: the frozen lab cannot accept MAC'd commands, so control is pinned off.
    assert lab["environment"]["EMULATION_CONTROL_ENABLED"] == "false"


def test_frozen_lab_is_refused_without_the_explicit_acknowledgement(state, calls):
    warnings = []

    def warn(message, **kwargs):
        warnings.append(message)

    environ = {"NANFO_LAB_FROZEN_IMAGE": DIGEST}
    initialized(state)
    for value in (None, "true", "yes", "0", ""):
        env = dict(environ) if value is None else {**environ, "NANFO_LAB_FROZEN": value}
        with pytest.raises(ValueError, match="NANFO_LAB_FROZEN=1"):
            manage.lab(state, "start", frozen=True, environ=env, warn=warn)
    assert calls == [] and len(warnings) == 5
    assert all("privileged, end-of-life" in message and "Refused" in message for message in warnings)
    warnings.clear()
    manage.lab(state, "start", frozen=True, environ={**environ, "NANFO_LAB_FROZEN": "1"}, warn=warn)
    assert [call.files for call in calls] == [("compose.lab.frozen.yaml",)]
    assert calls[0].args == ("--profile", "lab", "up", "-d", "--no-build", "--no-deps", "lab")
    assert len(warnings) == 1 and "Refused" not in warnings[0]


def test_cli_frozen_lab_refusal_reaches_the_operator(state, calls, monkeypatch, capsys, restore_umask):
    monkeypatch.delenv("NANFO_LAB_FROZEN", raising=False)
    with pytest.raises(ValueError, match="NANFO_LAB_FROZEN=1"):
        manage.main(["--state", str(state), "lab", "start", "--frozen"])
    assert "end-of-life" in capsys.readouterr().err and calls == []


@pytest.mark.parametrize("image", ["", "nanfo-emulation:successor-adr028", "sha256:" + "a" * 63,
                                   "registry.example/lab:latest", "lab@sha256:" + "A" * 64])
def test_lab_requires_an_operator_pinned_immutable_image(state, calls, image):
    with pytest.raises(ValueError, match="NANFO_LAB_IMAGE must be"):
        manage.lab(initialized(state), "start", environ={"NANFO_LAB_IMAGE": image})
    assert calls == []


def test_successor_lab_starts_only_on_an_initialized_deployment(state, calls):
    environ = {"NANFO_LAB_IMAGE": "registry.example/nanfo/lab@" + DIGEST}
    with pytest.raises(ValueError, match="initialized"):
        manage.lab(state, "start", environ=environ)
    manage.lab(state, "status", environ=environ)
    initialized(state)
    manage.lab(state, "start", environ=environ)
    manage.lab(state, "stop", environ={"NANFO_LAB_IMAGE": DIGEST})
    assert [call.files for call in calls] == [("compose.lab.yaml",)] * 3
    assert calls[1].args == ("--profile", "lab", "up", "-d", "--no-build", "--no-deps", "lab")
    assert calls[2].args == ("stop", "--timeout", "30", "lab")


def test_initialized_deployments_may_build_only_the_separately_pinned_lab(state, monkeypatch, restore_umask):
    builds = []
    monkeypatch.setattr(manage, "build_images", lambda state_, **kwargs: builds.append(kwargs))
    initialized(state)
    manage.main(["--state", str(state), "build", "--service", "lab"])
    assert builds == [{"service": "lab", "with_ai": False, "with_fleet": False, "image_tag": None}]
    for service in ("backend", "frontend", "redis"):
        with pytest.raises(ValueError, match="Do not rebuild"):
            manage.main(["--state", str(state), "build", "--service", service])
    assert len(builds) == 1


def test_lab_build_uses_the_ai_lab_source_identity_and_never_moves_historical_tags():
    from emulation import control

    tag, source = manage.lab_build_identity()
    assert re.fullmatch(r"nanfo-emulation:successor-[0-9a-f]{12}", tag) and "operator-paths-adr020" not in tag
    assert source == control.sourceDigest(ROOT / "emulation") and tag.endswith(source[:12])
    # The staged context mirrors emulation/.dockerignore and control.py's IGNORED set ...
    ignored = {line.strip() for line in (ROOT / "emulation/.dockerignore").read_text().splitlines()
               if line.strip() and "/" not in line and "*" not in line}
    assert manage.LAB_IGNORED == ignored == control.IGNORED
    # ... so manage.py stages exactly the files AI-Lab's build digests (checked before building).
    staged = {}
    for path in sorted((ROOT / "emulation").rglob("*")):
        parts = path.relative_to(ROOT).parts
        if (not path.is_symlink() and path.is_file() and not manage.skipped_from_context("lab", parts)
                and manage.context_allowed("lab", "/".join(parts), parts, path.suffix)):
            staged["/".join(parts)] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert manage.lab_source_digest(staged) == source
    assert {"emulation/Dockerfile", "emulation/.dockerignore"} <= set(staged)
    for name in ("emulation/frozen/adr015-prechange-v4-source.tar.gz", "emulation/results/x.json",
                 "emulation/commands/c.json", "emulation/x.pyc", "deploy/manage.py"):
        assert not manage.context_allowed("lab", name, tuple(name.split("/")), Path(name).suffix)
    for kind in ("backend", "frontend"):
        assert manage.skipped_from_context(kind, ("emulation", ".dockerignore"))
        assert manage.skipped_from_context(kind, ("deploy", "state", "evidence.json"))
        assert manage.skipped_from_context(kind, ("deploy", "manage.py"))


# --- Task 9: credential rotation ---

def test_store_rotation_journals_applies_publishes_restages_and_restarts(state, calls):
    initialized(state)
    old = (state / "secrets/redis_password").read_text().strip()
    assert manage.rotate(state, "redis") == {"rotated": "redis", "restarted": manage.APPLICATION}
    new = (state / "secrets/redis_password").read_text().strip()
    assert new != old and re.fullmatch(r"[0-9a-f]{64}", new)
    assert mode(state / "secrets/redis_password") == 0o600
    assert not list((state / "secrets").glob(".*pending*"))
    assert [call.args for call in calls] == [
        (*HELPER, "apply", "redis"),
        ("run", "--rm", "--no-deps", "volume-init", "restage", "redis_password"),
        ("restart", *manage.APPLICATION),
        (*HELPER, "finalize", "redis"),
    ]
    assert json.loads(calls[0].input) == json.loads(calls[3].input) == {"password": new}
    # The credential travels on the helper's stdin only, never in argv.
    assert all(new not in " ".join(call.args) and old not in " ".join(call.args) for call in calls)


def test_interrupted_store_rotation_keeps_the_journal_and_resumes_idempotently(state, calls, monkeypatch):
    initialized(state)
    current = state / "secrets/postgres_runtime_password"
    before = current.read_bytes()
    recorder = manage.compose

    def unreachable(state_, *args, **kwargs):
        recorder(state_, *args, **kwargs)
        raise subprocess.CalledProcessError(1, "compose")

    monkeypatch.setattr(manage, "compose", unreachable)
    with pytest.raises(subprocess.CalledProcessError):
        manage.rotate(state, "postgres_app")
    pending = state / "secrets/.postgres_runtime_password.pending"
    journaled = pending.read_text().strip()
    assert current.read_bytes() == before and mode(pending) == 0o600
    monkeypatch.setattr(manage, "compose", recorder)
    with pytest.raises(ValueError, match="--resume"):
        manage.rotate(state, "postgres_app")
    calls.clear()
    manage.rotate(state, "postgres_app", resume=True)
    assert current.read_text().strip() == journaled and not pending.exists()
    assert json.loads(calls[0].input) == {"password": journaled}
    assert [call.args[-1] for call in calls] == ["postgres_app", "postgres_runtime_password",
                                                 manage.APPLICATION[-1]]
    calls.clear()
    # A resume after publication re-applies the published value (idempotent) and restages.
    manage.rotate(state, "postgres_app", resume=True)
    assert json.loads(calls[0].input) == {"password": journaled}


def test_owner_rotation_restages_the_initializer_copy_without_restarting_services(state, calls):
    initialized(state)
    manage.rotate(state, "postgres_owner")
    assert [call.args[-2:] for call in calls] == [("apply", "postgres_owner"), ("restage", "postgres_owner_password")]
    assert volume_init.STAGING["init_secrets"][1] >= {"postgres_owner_password", "neo4j_password", "redis_password"}


def test_rotation_requires_an_initialized_deployment_and_a_known_secret(state, calls):
    with pytest.raises(ValueError, match="initialized"):
        manage.rotate(state, "redis")
    initialized(state)
    with pytest.raises(KeyError):
        manage.rotate(state, "bootstrap_password")
    with pytest.raises(ValueError, match="jwt_secret only"):
        manage.rotate(state, "redis", finalize=True)
    assert calls == []
    assert sorted(manage.ROTATIONS) == ["jwt_secret", "neo4j", "postgres_app", "postgres_owner", "redis"]


def test_jwt_rotation_keeps_the_previous_key_verify_only_for_one_access_token_lifetime(state, calls):
    initialized(state)
    old = (state / "secrets/jwt_secret").read_text().strip()
    result = manage.rotate(state, "jwt_secret", now=lambda: 1_000_000)
    new = (state / "secrets/jwt_secret").read_text().strip()
    assert new != old and result["previous_valid_until"] == 1_000_000 + 15 * 60 + 30
    previous = state / "secrets" / manage.JWT_PREVIOUS
    assert previous.read_text() == f"{1_000_930}:{old}\n" and mode(previous) == 0o600
    assert [call.args for call in calls] == [
        ("run", "--rm", "--no-deps", "volume-init", "restage", "jwt_previous_secrets"),
        ("run", "--rm", "--no-deps", "volume-init", "restage", "jwt_secret"),
        ("restart", "api"),
    ]
    # The API entrypoint exports the previous key only while it is unexpired (C19).
    assert entrypoint.previous_keys(previous.read_text().strip(), 1_000_929) == [old]
    assert entrypoint.previous_keys(previous.read_text().strip(), 1_000_931) == []
    with pytest.raises(ValueError, match="overlap window"):
        manage.rotate(state, "jwt_secret", now=lambda: 1_000_100)
    with pytest.raises(ValueError, match="overlap window"):
        manage.rotate(state, "jwt_secret", finalize=True, now=lambda: 1_000_100)
    calls.clear()
    assert manage.rotate(state, "jwt_secret", finalize=True, now=lambda: 1_001_000)["previous_keys"] == 0
    assert not previous.exists() and (state / "secrets/jwt_secret").read_text().strip() == new
    assert [call.args[-1] for call in calls] == ["jwt_previous_secrets", "jwt_secret", "api"]


def test_interrupted_jwt_rotation_is_republished_with_resume(state, calls, monkeypatch):
    initialized(state)
    recorder = manage.compose

    def interrupted(state_, *args, **kwargs):
        recorder(state_, *args, **kwargs)
        if args[-1] == "jwt_secret":
            raise subprocess.CalledProcessError(1, "compose")

    monkeypatch.setattr(manage, "compose", interrupted)
    with pytest.raises(subprocess.CalledProcessError):
        manage.rotate(state, "jwt_secret", now=lambda: 2_000_000)
    monkeypatch.setattr(manage, "compose", recorder)
    with pytest.raises(ValueError, match="--resume"):
        manage.rotate(state, "jwt_secret", now=lambda: 2_000_010)
    calls.clear()
    result = manage.rotate(state, "jwt_secret", resume=True, now=lambda: 2_000_010)
    assert result == {"rotated": "jwt_secret", "resumed": True, "previous_valid_until": 2_000_930}
    assert [call.args[-1] for call in calls] == ["jwt_previous_secrets", "jwt_secret", "api"]
    with pytest.raises(ValueError, match="either"):
        manage.rotate(state, "jwt_secret", resume=True, finalize=True)


def test_jwt_overlap_is_bounded_and_zero_revokes_immediately(state, calls):
    initialized(state)
    with pytest.raises(ValueError, match="43200"):
        manage.rotate(state, "jwt_secret", overlap_seconds=43_201)
    assert manage.rotate(state, "jwt_secret", overlap_seconds=0)["previous_valid_until"] is None
    assert not (state / "secrets" / manage.JWT_PREVIOUS).exists()
    assert calls[-1].args == ("restart", "api")


def secret_root(tmp_path, **values):
    root = tmp_path / "run-secrets"
    root.mkdir()
    for name, value in values.items():
        (root / name).write_text(value + "\n")
        (root / name).chmod(0o400)
    return root


@pytest.mark.parametrize("payload", ['{"password": "short"}', json.dumps({"password": "a" * 40, "x": 1}),
                                     json.dumps(["a" * 40]), json.dumps({"password": "a" * 39 + "$"})])
def test_rotation_helper_reads_exactly_one_generated_password_object(payload):
    with pytest.raises(ValueError):
        secret_rotation.read_password(io.StringIO(payload))
    assert secret_rotation.read_password(io.StringIO(json.dumps({"password": "a" * 64}))) == "a" * 64


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        self.log.append(statement)


class FakeConnection:
    def __init__(self, log, **kwargs):
        self.kwargs, self.log, self.autocommit = kwargs, log, False

    def cursor(self):
        return FakeCursor(self.log)

    def close(self):
        self.log.append(("close", self.kwargs["user"]))


def test_postgres_rotation_sends_only_a_client_computed_scram_verifier(tmp_path, monkeypatch):
    import psycopg2.extensions
    from psycopg2 import sql

    password = "p" * 64
    verifier = "SCRAM-SHA-256$4096:c2FsdA==$c3RvcmVk:c2VydmVy"

    def encrypt_password(secret, role, connection, method):
        assert (secret, role, method) == (password, "nanfo_runtime", "scram-sha-256")
        return verifier

    monkeypatch.setattr(psycopg2.extensions, "encrypt_password", encrypt_password)
    log, connections = [], []

    def connect(**kwargs):
        connections.append(kwargs)
        return FakeConnection(log, **kwargs)

    root = secret_root(tmp_path, postgres_admin_password="admin-" + "x" * 32)
    assert secret_rotation.rotate_postgres("postgres_app", password, connect=connect, secret_root=root) == "applied"
    statements = [item for item in log if isinstance(item, sql.Composed)]
    assert len(statements) == 1
    parts = statements[0].seq
    assert [type(part) for part in parts] == [sql.SQL, sql.Identifier, sql.SQL, sql.Literal]
    assert parts[0].string == "ALTER ROLE " and parts[1].strings == ("nanfo_runtime",)
    assert parts[3].wrapped == verifier and password not in repr(statements[0])
    # Admin connection first, then a proof login with the new credential.
    assert [item["user"] for item in connections] == ["postgres", "nanfo_runtime"]
    assert connections[1]["password"] == password


class FakeRedis:
    log = []

    def __init__(self, *, username, password, **options):
        self.username, self.password = username, password

    async def execute_command(self, *args):
        FakeRedis.log.append((self.username, args))

    async def ping(self):
        FakeRedis.log.append((self.username, "ping"))
        return True

    async def aclose(self):
        pass


@pytest.mark.parametrize("action,rules", [("apply", ()), ("finalize", ("resetpass",))])
def test_redis_rotation_adds_then_finalizes_hashed_acl_passwords(tmp_path, action, rules):
    FakeRedis.log = []
    password = "r" * 64
    root = secret_root(tmp_path, redis_admin_password="admin-" + "y" * 32)
    status = asyncio.run(secret_rotation.rotate_redis(action, password, client=FakeRedis, secret_root=root))
    digest = "#" + hashlib.sha256(password.encode()).hexdigest()
    assert FakeRedis.log == [("nanfo-admin", ("ACL", "SETUSER", "nanfo", *rules, digest)), ("nanfo", "ping")]
    assert status == ("applied" if action == "apply" else "finalized")
    assert all(password not in str(entry) for entry in FakeRedis.log)


class FakeNeo4j:
    def __init__(self, accepted):
        self.accepted, self.log = accepted, []

    def __call__(self, uri, auth):
        return FakeNeo4jDriver(self, auth[1])


class FakeNeo4jDriver:
    def __init__(self, server, password):
        self.server, self.password = server, password

    async def verify_connectivity(self):
        from neo4j.exceptions import AuthError

        if self.password != self.server.accepted:
            raise AuthError("denied")

    def session(self, database):
        return FakeNeo4jSession(self.server, database)

    async def close(self):
        pass


class FakeNeo4jSession:
    def __init__(self, server, database):
        self.server, self.database = server, database

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, query, **params):
        self.server.log.append((self.database, query, params))
        self.server.accepted = params["new"]
        return SimpleNamespace(consume=self.consume)

    async def consume(self):
        return None


def test_neo4j_rotation_changes_its_own_password_with_parameters_and_is_idempotent(tmp_path):
    old, new = "o" * 40, "n" * 64
    root = secret_root(tmp_path, neo4j_password=old)
    server = FakeNeo4j(accepted=old)
    assert asyncio.run(secret_rotation.rotate_neo4j(new, driver_factory=server, secret_root=root)) == "applied"
    assert server.log == [("system", "ALTER CURRENT USER SET PASSWORD FROM $old TO $new", {"old": old, "new": new})]
    assert asyncio.run(secret_rotation.rotate_neo4j(new, driver_factory=server, secret_root=root)) == "already_applied"
    assert len(server.log) == 1
    with pytest.raises(ValueError, match="Neither"):
        asyncio.run(secret_rotation.rotate_neo4j("z" * 64, driver_factory=FakeNeo4j("q" * 40), secret_root=root))


def test_rotation_helper_output_never_contains_credentials(monkeypatch, capsys):
    password = "s" * 64

    def explode(action, kind, value):
        raise RuntimeError(f"driver echoed {value}")

    monkeypatch.setattr(secret_rotation, "execute", explode)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"password": password})))
    assert secret_rotation.main(["apply", "neo4j"]) == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {"status": "refused", "secret": "neo4j", "error_type": "RuntimeError"}
    assert password not in output


# --- Task 12: autoheal and restart policies ---

def docker_ps(unhealthy, healthy=("postgres", "redis", "neo4j")):
    """manage.run stand-in answering both docker ps queries and recording restarts."""
    restarts = []

    def run(command, *, capture=False, input=None):
        if command[:2] == ["docker", "restart"]:
            assert command[2:4] == ["-t", "45"]
            restarts.append(command[-1])
            return SimpleNamespace(stdout="")
        assert command[:2] == ["docker", "ps"] and "label=com.docker.compose.project=nanfo-deploy-unit" in command
        if "health=unhealthy" in command:
            return SimpleNamespace(stdout="".join(f"{identity} {service}\n" for identity, service in unhealthy()))
        assert "health=healthy" in command
        return SimpleNamespace(stdout="".join(f"{service}\n" for service in healthy))

    return run, restarts


def test_autoheal_restarts_only_application_containers_unhealthy_beyond_the_threshold(state, monkeypatch):
    current = [("a" * 12, "report-worker"), ("b" * 12, "postgres"), ("c" * 12, "lab"), ("zz", "api")]
    run, restarts = docker_ps(lambda: current)
    monkeypatch.setattr(manage, "run", run)
    events = []
    for count in (1, 2, 3):
        assert manage.autoheal(state, once=True, threshold=3, emit=events.append) == {"a" * 12: count}
    assert restarts == [] and mode(state / "autoheal.json") == 0o600
    assert manage.autoheal(state, once=True, threshold=3, emit=events.append) == {"a" * 12: 0}
    assert restarts == ["a" * 12]
    assert json.loads(events[-1]) == {"autoheal": "restarted", "service": "report-worker", "checks": 4}
    current = []
    assert manage.autoheal(state, once=True, threshold=3, emit=events.append) == {}
    assert json.loads((state / "autoheal.json").read_text()) == {}


def test_autoheal_defers_while_a_datastore_is_not_healthy(state, monkeypatch):
    run, restarts = docker_ps(lambda: [("d" * 12, "api")], healthy=("redis", "neo4j"))
    monkeypatch.setattr(manage, "run", run)
    events = []
    for _ in range(3):
        manage.autoheal(state, once=True, threshold=1, emit=events.append)
    assert restarts == []
    assert json.loads(events[-1]) == {"autoheal": "deferred", "reason": "datastore_not_healthy", "services": ["api"]}
    assert json.loads((state / "autoheal.json").read_text()) == {"d" * 12: 3}


def test_autoheal_loop_counts_consecutive_observations_in_memory(state, monkeypatch):
    run, restarts = docker_ps(lambda: [("e" * 12, "stream-retention")])
    monkeypatch.setattr(manage, "run", run)
    sleeps = []

    class Done(Exception):
        pass

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise Done

    with pytest.raises(Done):
        manage.autoheal(state, interval=10, threshold=2, sleep=sleep, emit=lambda _: None)
    assert restarts == ["e" * 12] and sleeps == [10, 10, 10]
    assert not (state / "autoheal.json").exists()


@pytest.mark.parametrize("kwargs", [{"threshold": 0}, {"threshold": 101}, {"interval": 4}, {"interval": 3601}])
def test_autoheal_bounds_fail_closed(state, kwargs):
    with pytest.raises(ValueError):
        manage.autoheal(state, once=True, **kwargs)


def test_restart_policies_restart_the_watchdog_exit_and_autoheal_excludes_stores_and_lab():
    watchdog = (ROOT / "backend/app/core/watchdog.py").read_text()
    assert re.search(r"^EXIT_CODE = 70\b", watchdog, re.MULTILINE)
    base = services()
    for name in manage.SERVICES:
        # unless-stopped restarts every exit status, including the watchdog's 70.
        assert base[name]["restart"] == "unless-stopped", name
    assert base["gateway"]["restart"] == "unless-stopped"
    assert not manage.AUTOHEAL_SERVICES & {*manage.STORES, "lab", "volume-init", "initialize", "maintenance"}
    api2 = services("compose.distributed.yaml")["api2"]
    fleet = services("compose.fleet.yaml")["fleet-worker"]
    assert api2["extends"]["service"] == "api" and fleet["extends"]["service"] == "network-outbox-worker"
    assert "restart" not in api2 and "restart" not in fleet  # inherited unless-stopped
    assert {"api2", "fleet-worker"} <= manage.AUTOHEAL_SERVICES


# --- Task 11: state location ---

def test_existing_in_repository_deployment_keeps_being_used_with_a_warning(tmp_path, monkeypatch):
    legacy = tmp_path / "repo/deploy/state"
    (legacy / "adr023-private-evidence").mkdir(parents=True)
    monkeypatch.setattr(manage, "LEGACY_STATE", legacy)
    warnings = []

    def warn(message, **kwargs):
        warnings.append(message)

    home = {"HOME": str(tmp_path / "home")}
    # Evidence-only deploy/state (no deployment.env) is not a deployment.
    assert manage.default_state(home, warn=warn) == tmp_path / "home/.local/state/nanfo"
    assert warnings == []
    (legacy / "deployment.env").write_text("NANFO_PROJECT=nanfo-deploy-old\n")
    assert manage.default_state(home, warn=warn) == legacy
    assert "inside the repository" in warnings[0] and "never moved" in warnings[0]
    assert sorted(path.name for path in legacy.iterdir()) == ["adr023-private-evidence", "deployment.env"]
    assert not (tmp_path / "home").exists()


def test_fresh_state_defaults_to_the_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "LEGACY_STATE", tmp_path / "absent")
    xdg = tmp_path / "xdg"
    assert manage.default_state({"XDG_STATE_HOME": str(xdg), "HOME": "/nonexistent"}) == xdg / "nanfo"
    assert manage.default_state({"HOME": str(tmp_path)}) == tmp_path / ".local/state/nanfo"
    # A relative XDG_STATE_HOME is invalid per the XDG specification and ignored.
    assert manage.default_state({"XDG_STATE_HOME": "relative", "HOME": str(tmp_path)}) == (
        tmp_path / ".local/state/nanfo")
    link = tmp_path / "linked-home"
    link.symlink_to(tmp_path, target_is_directory=True)
    resolved = manage.default_state({"HOME": str(link)})
    assert resolved == resolved.resolve() == tmp_path.resolve() / ".local/state/nanfo"
