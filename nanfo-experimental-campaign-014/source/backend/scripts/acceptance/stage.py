"""Private child adapter for shipped verifiers; no shared source/config edits.

AST adaptation changes only literal migration target/assertion 0012/0016 to 0019,
the execution image literal and override image constant. Every adaptation is
recorded. Verifier assertions, fault controls, API requests and plan fences remain.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import os
import secrets
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.acceptance.common import (
    IMAGE,
    NAME,
    OWNER_LABEL,
    STAGE_LABEL,
    Blocked,
    read_json,
    sanitize,
    sha,
    write_new,
)
from scripts.acceptance.runtime import owned, snapshot

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"

FIXTURE_TESTS = (
    "tests/unit/test_alert_detector.py", "tests/unit/test_alert_consumer.py",
    "tests/unit/test_plugin_service.py", "tests/unit/test_report_artifacts.py",
    "tests/integration/test_alert_postgres.py", "tests/integration/test_plugin_postgres.py",
)


def test_counts(path):
    raw = path.read_bytes()
    if len(raw) > 4 * 1024 * 1024 or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise Blocked("test_report_bound_or_entity")
    root = ET.fromstring(raw)
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    counts = {key: sum(int(suite.get(key, "0")) for suite in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    return counts


def adapted_source(path, replacements):
    raw = path.read_bytes()
    tree = ast.parse(raw, filename=str(path))
    counts = dict.fromkeys(replacements, 0)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in replacements:
            counts[node.value] += 1
            node.value = replacements[node.value]
    if any(count == 0 for count in counts.values()):
        raise Blocked("verifier_adapter_contract_changed")
    return compile(tree, str(path), "exec"), {"source_sha256": sha(raw), "literal_replacements": replacements,
                                              "replacement_counts": counts}


def emulation_verifier():
    path = BACKEND / "scripts/verify_emulation.py"
    raw = path.read_bytes()
    tree = ast.parse(raw, filename=str(path))
    module = types.ModuleType("scripts.acceptance_emulation")
    module.__file__ = str(path)
    exec(compile(tree, str(path), "exec"), module.__dict__)

    return module


async def run(args):
    # Clear inherited application/DSN/training configuration before importing app.
    keep = {key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ}
    os.environ.clear()
    os.environ.update(keep)
    os.environ.update(PYTHONPATH=f"{BACKEND}:{ROOT}", PYTHONDONTWRITEBYTECODE="1")
    from scripts import verify_execution as helper

    directory = Path(args.directory).resolve()
    work = directory / "work"
    work.mkdir(mode=0o700)
    suffix = secrets.token_hex(16)
    before = snapshot()
    names = set()
    original = helper.external
    adaptations = []
    test_results = []

    async def external(*argv, **kwargs):
        argv = list(argv)
        if argv[:2] == ["docker", "compose"]:
            raise Blocked("global_compose_lifecycle_denied")
        pytest_run = argv[:3] == [sys.executable, "-m", "pytest"]
        if pytest_run:
            # XML is used only to count outcomes, then discarded: failure XML may
            # include SQL parameters or server traces. Never report all-skipped green.
            argv += ["--junitxml=" + str(work / "pytest-private.xml"), "--tb=no", "-o", "junit_logging=no"]
        if argv[:2] == ["docker", "run"]:
            current = snapshot()
            if any(current.get(identity) != row for identity, row in before.items()):
                raise Blocked("baseline_changed_before_container_creation")
            if any(identity not in before and not owned(row, owner=args.owner, stage=args.stage,
                                                       baseline=before, names=names)
                   for identity, row in current.items()):
                raise Blocked("concurrent_unknown_container_preserved")
            if "--name" not in argv:
                raise Blocked("unnamed_container_denied")
            name = argv[argv.index("--name") + 1]
            if not NAME.fullmatch(name) or name in {row["Name"] for row in before.values()}:
                raise Blocked("container_name_not_isolated")
            write_new(directory / f"owned-{len(names):03d}.json",
                      {"name": name, "owner": args.owner, "stage": args.stage})
            names.add(name)
            argv[2:2] = ["--label", f"{OWNER_LABEL}={args.owner}", "--label", f"{STAGE_LABEL}={args.stage}"]
        if argv[:2] == ["docker", "rm"]:
            target = argv[-1]
            current = snapshot()
            row = next((row for identity, row in current.items() if identity == target or row["Name"] == target), None)
            if row is None:
                return ""
            if not owned(row, owner=args.owner, stage=args.stage, baseline=before, names=names):
                raise Blocked("verifier_cleanup_not_owned")
            argv[-1] = row["Id"]
        try:
            output = await original(*argv, **kwargs)
            if pytest_run:
                counts = test_counts(work / "pytest-private.xml")
                test_results.append(counts)
                if not counts["tests"] or any(counts[key] for key in ("skipped", "failures", "errors")):
                    raise Blocked("required_tests_skipped_or_failed")
                return "Required tests completed; raw diagnostic output withheld"
            return output
        finally:
            if pytest_run:
                (work / "pytest-private.xml").unlink(missing_ok=True)

    helper.external = external
    ports = {kind: helper.port() for kind in ("postgres", "redis", "neo4j")}
    env = {**os.environ, "APP_ENV": "verification", "LOG_LEVEL": "CRITICAL", "EXECUTION_MODE": "emulation",
           "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": str(ports["postgres"]),
           "POSTGRES_USER": "verifier", "POSTGRES_DB": "acceptance", "POSTGRES_PASSWORD": secrets.token_hex(24),
           "REDIS_HOST": "127.0.0.1", "REDIS_PORT": str(ports["redis"]), "REDIS_DB": "0",
           "REDIS_PASSWORD": secrets.token_hex(24), "NEO4J_URI": f"bolt://127.0.0.1:{ports['neo4j']}",
           "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": secrets.token_hex(24), "JWT_SECRET_KEY": secrets.token_hex(48),
           "EMULATION_CONTROL_ENABLED": "false", "TELEMETRY_RUNTIME_ADAPTER_MODE": "stub"}
    os.environ.update(env)
    from app.core.config import Settings, get_settings

    # Prevent .env from supplying any newly-added service or artifact setting.
    isolated = Settings(_env_file=None)
    if "REPORTS_STORAGE_PATH" in Settings.model_fields:
        isolated.REPORTS_STORAGE_PATH = str(work / "protected-report-storage")
    for field in Settings.model_fields:
        os.environ[field] = str(getattr(isolated, field))
    get_settings.cache_clear()
    artifact = {"version": 1, "passed": False, "checks": {}, "cases": {}, "actions": []}
    configs = [work / "redis.conf", work / "infrastructure-redis.conf"]
    try:
        if args.stage not in ("operator_override", "actions", "negative", "reports"):
            await external("docker", "run", "-d", "--name", f"nanfo-acceptance-postgres-{suffix}",
                           "-p", f"127.0.0.1:{ports['postgres']}:5432", "-e", "POSTGRES_USER", "-e", "POSTGRES_PASSWORD",
                           "-e", "POSTGRES_DB", "postgres:16-alpine", env=env)
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

            engine = create_async_engine(isolated.POSTGRES_DSN)
            try:
                async def ready():
                    try:
                        async with engine.connect() as db:
                            return await db.scalar(text("SELECT 1")) == 1
                    except Exception:
                        return False
                await helper.until(ready, timeout=90)
                await external(sys.executable, "-m", "alembic", "-c", "alembic/alembic.ini", "upgrade", "0019",
                               env=dict(os.environ), cwd=BACKEND)
                async with engine.connect() as db:
                    if await db.scalar(text("SELECT version_num FROM alembic_version")) != "0019":
                        raise Blocked("isolated_migration_head_mismatch")
            finally:
                await engine.dispose()
        if args.stage == "emulation":
            config = configs[1]
            fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(f'bind 0.0.0.0\nprotected-mode yes\nsave ""\nappendonly no\nrequirepass {env["REDIS_PASSWORD"]}\n')
            await external("docker", "run", "-d", "--name", f"nanfo-acceptance-redis-{suffix}", "--user", str(os.geteuid()),
                           "-p", f"127.0.0.1:{ports['redis']}:6379", "--mount", f"type=bind,source={config},target=/run/redis.conf,readonly",
                           "redis:7-alpine", "redis-server", "/run/redis.conf")
            await external("docker", "run", "-d", "--name", f"nanfo-acceptance-neo4j-{suffix}",
                           "-p", f"127.0.0.1:{ports['neo4j']}:7687", "-e", "NEO4J_AUTH",
                           "-e", "NEO4J_server_memory_heap_initial__size=256m", "-e", "NEO4J_server_memory_heap_max__size=256m",
                           "-e", "NEO4J_server_memory_pagecache_size=128m", "neo4j:5.25-community",
                           env={**env, "NEO4J_AUTH": "neo4j/" + env["NEO4J_PASSWORD"]})
            import redis.asyncio as redis
            from neo4j import AsyncGraphDatabase

            async def services_ready():
                try:
                    async with redis.from_url(isolated.REDIS_URL) as client:
                        await client.ping()
                    async with AsyncGraphDatabase.driver(isolated.NEO4J_URI, auth=(isolated.NEO4J_USER, isolated.NEO4J_PASSWORD)) as driver:
                        await driver.verify_connectivity()
                    return True
                except Exception:
                    return False
            await helper.until(services_ready, timeout=120)
        if args.stage in ("actions", "negative", "emulation"):
            scope = work / "scope"
            labdir = scope / "emulation"
            for name in ("output", "commands", "results"):
                (labdir / name).mkdir(parents=True, mode=0o755)
            lab_name = f"nanfo-acceptance-lab-{suffix}"

            async def lab_start(extra=(), detached=True):
                argv = ["docker", "run", *( ["-d"] if detached else []), "--name", lab_name,
                        "--privileged", "--network", "none", "--pids-limit", "256", "--memory", "768m", "--cpus", "2",
                        "--tmpfs", "/run:exec,size=64m", "--tmpfs", "/tmp:exec,size=64m",
                        "-e", "EMULATION_CONTROL_ENABLED=false"]
                for name in ("output", "commands", "results"):
                    argv += ["--mount", f"type=bind,source={labdir / name},target=/{name}" + (",readonly" if name == "commands" else "")]
                if args.stage == "negative":
                    argv += ["--mount", f"type=bind,source={Path(__file__).with_name('lab_negative.py')},target=/acceptance_negative.py,readonly",
                             "--entrypoint", "python"]
                await external(*argv, args.image, *extra, timeout=900 if not detached else 120)
                if detached:
                    async def ready():
                        try:
                            return '"passed": true' in await external("docker", "exec", lab_name, "python", "-m", "emulation.runner", "--request", "status", timeout=5)
                        except Exception:
                            return False
                    await helper.until(ready, timeout=100)

            if args.stage in ("actions", "negative"):
                await lab_start(("--verify-actions",) if args.stage == "actions" else ("/acceptance_negative.py",), detached=False)
                artifact, _ = read_json(labdir / "output" / ("actions-verification.json" if args.stage == "actions" else "negative.json"))
            else:
                verifier = emulation_verifier()

                # Its path calculations now resolve exclusively to owned runtime directories.
                verifier.__file__ = str(scope / "backend" / "scripts" / "verify_emulation.py")

                async def command(*argv, timeout=110):
                    if argv[:2] == ("docker", "compose") and "ps" in argv:
                        return ""  # No Compose project exists or is created by this adapter.
                    if len(argv) >= 3 and argv[1] == str(labdir / "control.py"):
                        if argv[2] == "start":
                            await lab_start()
                            return ""
                        if argv[2] == "stop":
                            return await external("docker", "rm", "-f", "-v", lab_name)
                        if argv[2] == "traffic":
                            return await external("docker", "exec", lab_name, "python", "-m", "emulation.runner", "--request", "traffic", timeout=timeout)
                        raise Blocked("unmapped_emulation_control")
                    return await external(*argv, timeout=timeout)
                verifier.command = command
                adaptations.append({"verifier": "verify_emulation.py", "source_sha256": sha((BACKEND / "scripts/verify_emulation.py").read_bytes()),
                                    "adapter": "owned paths; direct labeled Docker lifecycle instead of shared Compose; isolated DB/Redis/Neo4j; dispatch every merged handler"})
                await verifier.verify(work, artifact)
                artifact["passed"] = artifact.get("status") == "passed"
        elif args.stage in ("execution", "operator_override", "reports"):
            name = "verify_" + args.stage
            path = BACKEND / "scripts" / f"{name}.py"
            replacements = {{"execution": "0012", "operator_override": "0016", "reports": "0017"}[args.stage]: "0019"}
            if args.stage == "execution":
                replacements["nanfo-emulation:campus-small-v1"] = args.image
            elif args.stage == "operator_override":
                replacements["sha256:d91efe1717f29a277683b735418877d73243ae24ab80e4c2c3311f6f0343c05c"] = args.image
            code, adaptation = adapted_source(path, replacements)
            adaptations.append(adaptation)
            verifier = types.ModuleType(f"scripts.acceptance_{name}")
            verifier.__file__ = str(path)
            exec(code, verifier.__dict__)
            # The copied verifier must catch the actual helper exception class;
            # otherwise transient container readiness errors escape its retry.
            verifier.VerificationError = helper.VerificationError
            verifier.external = external
            await verifier.verify(work, artifact)
            if args.stage == "reports":
                artifact["passed"] = artifact.get("stage") == "passed"
        elif args.stage == "fixtures":
            await external(sys.executable, "-m", "pytest", *FIXTURE_TESTS, "-q", "--no-cov",
                           cwd=BACKEND, timeout=900, env={**os.environ,
                               "ALERT_TEST_DSN": isolated.POSTGRES_SYNC_DSN,
                               "PLUGIN_TEST_DSN": isolated.POSTGRES_SYNC_DSN})
            artifact.update(passed=True, evidence_kind="unit", source_kind="typed fixtures, not measured lab")
        else:
            raise Blocked("unknown_stage")
    except Exception as error:
        # Only type and source locations, never exception text/locals/server stack.
        locations = []
        tb = error.__traceback__
        while tb:
            filename = Path(tb.tb_frame.f_code.co_filename)
            if filename.name in {"stage.py", "verify_execution.py", "verify_emulation.py", "verify_operator_override.py", "verify_reports.py"}:
                locations.append({"file": filename.name, "line": tb.tb_lineno})
            if filename.name == "verify_emulation.py" and "errors" in tb.tb_frame.f_locals:
                artifact["consumer_error_types"] = [value for value in tb.tb_frame.f_locals["errors"]
                                                     if isinstance(value, str) and value.isidentifier()]
            tb = tb.tb_next
        write_new(directory / "diagnostic.json", {"exception_type": type(error).__name__, "verifier_locations": locations})
        raise
    finally:
        for path in configs:
            path.unlink(missing_ok=True)
        artifact["test_counts"] = {key: sum(item[key] for item in test_results)
                                   for key in ("tests", "failures", "errors", "skipped")}
        write_new(directory / "adaptations.json", adaptations)
        write_new(directory / "result.json", sanitize(artifact))
    return 0 if artifact.get("passed") is True else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--stage", choices=("emulation", "execution", "operator_override", "actions", "negative", "reports", "fixtures"), required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    if not args.live or not IMAGE.fullmatch(args.image):
        parser.error("Explicit --live and immutable sha256 image required")
    # Private child requires a parent-created admission record, not merely --live.
    admission, _ = read_json(Path(args.directory) / "admission.json")
    if admission != {"owner": args.owner, "stage": args.stage, "image": args.image}:
        return 2
    try:
        return asyncio.run(run(args))
    except BaseException:
        return 1  # Never print server exceptions, SQL, token URLs or stack traces.


if __name__ == "__main__":
    raise SystemExit(main())
