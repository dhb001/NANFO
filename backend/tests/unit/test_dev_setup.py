"""Run only copied setup scripts with a fake daemon; Compose rendering is read-only."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
NAMES = ("POSTGRES_PASSWORD", "NEO4J_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET_KEY")


@pytest.fixture
def setup_tree(tmp_path):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Compose CLI needed for config rendering, never a live daemon")
    for name in ("backend", "scripts", "bin"):
        (tmp_path / name).mkdir()
    for name in ("docker-compose.yml", ".env.example", "Makefile"):
        shutil.copyfile(ROOT / "backend" / name, tmp_path / "backend" / name)
    shutil.copyfile(ROOT / "scripts/dev-start.sh", tmp_path / "scripts/dev-start.sh")
    fake = tmp_path / "bin/docker"
    fake.write_text(f'''#!{sys.executable}
import json, os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ["CALL_LOG"]).open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
if args == ["info"]:
    sys.exit(0)
if args == ["compose", "up", "--help"]:
    print("up --wait --wait-timeout" if not os.environ.get("OLD_COMPOSE") else "up -d")
    sys.exit(0)
if "config" in args:
    sys.exit(subprocess.run([{docker!r}, *args]).returncode)
if "up" in args:
    sys.exit(int(os.environ.get("START_STATUS", "0")))
sys.exit("Unexpected Docker operation")
''')
    fake.chmod(0o700)
    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    env.update(PATH=f"{tmp_path / 'bin'}:{env['PATH']}", CALL_LOG=str(tmp_path / "calls.jsonl"))
    return tmp_path, env


def run_setup(tree, **overrides):
    root, env = tree
    result = subprocess.run(
        ["bash", str(root / "scripts/dev-start.sh")], env={**env, **overrides},
        cwd=root, capture_output=True, text=True, timeout=20,
    )
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    return result, calls


def write_env(root, value):
    text = (root / "backend/.env.example").read_text()
    for name in NAMES:
        text = text.replace(f"{name}=\n", f"{name}={value}\n")
    target = root / "backend/.env"
    target.write_text(text)
    target.chmod(0o600)
    return target


def starts(calls):
    return [call for call in calls if "up" in call and "--help" not in call]


def test_generates_private_independent_secrets_and_waits(setup_tree):
    result, calls = run_setup(setup_tree, NANFO_DEV_WAIT_SECONDS="42")
    assert result.returncode == 0, result.stderr
    target = setup_tree[0] / "backend/.env"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    values = dict(line.split("=", 1) for line in target.read_text().splitlines() if "=" in line and not line.startswith("#"))
    assert len({values[name] for name in NAMES}) == 4
    for name in NAMES:
        assert len(values[name]) == 64
        assert values[name] not in result.stdout + result.stderr
    assert starts(calls) == [["compose", "--env-file", ".env", "-f", "docker-compose.yml",
                             "up", "-d", "--wait", "--wait-timeout", "42"]]
    assert "are healthy" in result.stdout


@pytest.mark.parametrize("secret", ["CHANGE_ME", "nanfo_dev_secret", "", "short"])
def test_existing_unsafe_env_is_preserved_and_never_started(setup_tree, secret):
    target = write_env(setup_tree[0], secret)
    original = target.read_bytes()
    result, calls = run_setup(setup_tree)
    assert result.returncode != 0
    assert not starts(calls)
    assert target.read_bytes() == original
    if secret:
        assert secret not in result.stdout + result.stderr


def test_existing_valid_env_is_never_rewritten(setup_tree):
    target = write_env(setup_tree[0], "custom@special/#%:credential-with-32-chars")
    before = target.stat()
    original = target.read_bytes()
    result, _ = run_setup(setup_tree)
    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == original
    assert target.stat().st_mtime_ns == before.st_mtime_ns
    assert target.stat().st_ino == before.st_ino


def test_shell_placeholder_override_is_rejected(setup_tree):
    write_env(setup_tree[0], "valid-custom-credential-over-32-characters")
    result, calls = run_setup(setup_tree, REDIS_PASSWORD="CHANGE_ME")
    assert result.returncode != 0 and not starts(calls)
    assert "CHANGE_ME" not in result.stdout + result.stderr


def test_env_is_not_executed(setup_tree):
    root = setup_tree[0]
    target = write_env(root, "valid-custom-credential-over-32-characters")
    with target.open("a") as stream:
        stream.write(f"\nUNUSED=$(touch {root / 'executed'})\n")
    result, _ = run_setup(setup_tree)
    assert result.returncode == 0
    assert not (root / "executed").exists()


def test_dangling_env_symlink_is_not_clobbered(setup_tree):
    root = setup_tree[0]
    target = root / "backend/.env"
    target.symlink_to(root / "absent")
    result, calls = run_setup(setup_tree)
    assert result.returncode != 0 and not starts(calls)
    assert target.is_symlink() and not target.exists()


def test_failed_health_wait_never_reports_success(setup_tree):
    result, calls = run_setup(setup_tree, START_STATUS="1")
    assert result.returncode != 0 and len(starts(calls)) == 1
    assert "[done]" not in result.stdout


@pytest.mark.parametrize("options", [{"OLD_COMPOSE": "1"}, {"NANFO_DEV_WAIT_SECONDS": "0"}, {"NANFO_DEV_WAIT_SECONDS": "3601"}])
def test_unsupported_or_unbounded_wait_is_rejected_before_start(setup_tree, options):
    result, calls = run_setup(setup_tree, **options)
    assert result.returncode != 0 and not starts(calls)
    assert not (setup_tree[0] / "backend/.env").exists()


def test_sample_cannot_render_and_all_dev_ports_are_loopback(setup_tree):
    root, env = setup_tree
    command = [shutil.which("docker"), "compose", "--env-file", str(root / "backend/.env.example"),
               "-f", str(root / "backend/docker-compose.yml"), "config", "--format", "json"]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    result = subprocess.run(command, env={**env, **dict.fromkeys(NAMES, "fixture-credential-over-32-characters")},
                            capture_output=True, text=True, timeout=15, check=True)
    services = json.loads(result.stdout)["services"]
    assert sum(len(service["ports"]) for service in services.values()) == 4
    assert all(port["host_ip"] == "127.0.0.1" for service in services.values() for port in service["ports"])


def make_dry_run(target):
    if shutil.which("make") is None:
        pytest.skip("make is required to render Makefile recipes")
    result = subprocess.run(["make", "-n", target], cwd=ROOT / "backend", capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line.strip()]


@pytest.mark.parametrize("target,operation", [("migrate", "upgrade head"), ("migrate-down", "downgrade -1")])
def test_make_uses_actual_alembic_config(target, operation):
    assert make_dry_run(target) == [f"poetry run alembic -c alembic/alembic.ini {operation}"]


PYTHON_TARGETS = ("migrate", "migrate-down", "dev", "test", "test-unit", "test-integration", "lint", "check")


@pytest.mark.parametrize("target", PYTHON_TARGETS)
def test_make_python_targets_use_the_locked_poetry_environment(target):
    lines = make_dry_run(target)
    assert lines and all(line.startswith("poetry run ") for line in lines)


def test_make_dev_server_binds_loopback_only():
    [line] = make_dry_run("dev")
    assert "--host 127.0.0.1" in line and "0.0.0.0" not in line


def workflow(name):
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


def backend_job_commands():
    return [step.get("run", "") for step in workflow("quality.yml")["jobs"]["backend"]["steps"]]


def test_make_lint_and_check_match_the_ci_backend_job():
    ci = backend_job_commands()
    assert make_dry_run("lint") == ["poetry run ruff check app tests scripts"]
    assert any(" ".join(command.split()) == "poetry run ruff check app tests scripts" for command in ci)
    ruff, pytest_line = make_dry_run("check")
    assert ruff == "poetry run ruff check app tests scripts"
    assert pytest_line.startswith("poetry run pytest tests/unit tests/integration ")
    assert '-m "not private_artifacts"' in pytest_line
    portable = [command for command in ci if "pytest tests/unit tests/integration" in command]
    assert portable and all('-m "not private_artifacts"' in command and "--deselect" not in command
                            for command in portable)


def test_python_version_pin_matches_every_ci_interpreter():
    pinned = (ROOT / "backend/.python-version").read_text().strip()
    assert pinned == "3.12.14"
    versions = {
        str(step["with"]["python-version"])
        for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
        for job in workflow(path.name)["jobs"].values()
        for step in job.get("steps", [])
        if "setup-python" in step.get("uses", "")
    }
    assert versions == {pinned}
