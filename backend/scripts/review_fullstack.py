"""ADR027 R09: minified frontend against exact-owned authenticated stores/workers.

From backend: poetry run python -m scripts.review_fullstack --help
No supplied service URLs, shared Compose resources, auth overrides, or skip mode.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.audit_isolated_suite import AuditLab, junit_counts, junit_failures, redis_version
from scripts.verify_measured_twin import (
    BACKEND, AcceptanceFailure, environment, high_port, port_free, private_file, require,
)

REPO = BACKEND.parent
FRONTEND = REPO / "frontend"
LABEL = "org.nanfo.adr027.fullstack"


def exact_image(value: str) -> str:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise argparse.ArgumentTypeError("an exact locally installed sha256 image ID is required")
    return value


def clean_environment() -> dict[str, str]:
    # No caller DSNs, .env, auth switches, NODE_OPTIONS, npm hooks, or browser URLs.
    return {key: os.environ[key] for key in (
        "PATH", "HOME", "LANG", "LC_ALL", "DOCKER_HOST", "DOCKER_CONTEXT",
        "XDG_RUNTIME_DIR", "PLAYWRIGHT_BROWSERS_PATH",
    ) if key in os.environ}


def source_digest() -> str:
    paths = []
    for directory, suffixes in (
        (BACKEND / "app", {".py"}), (BACKEND / "alembic", {".py", ".ini"}),
        (BACKEND / "scripts", {".py"}), (FRONTEND / "src", {".ts", ".tsx", ".css"}),
        (FRONTEND / "tests/fullstack", {".ts", ".json"}),
        (FRONTEND / "public", None),
    ):
        paths.extend(p for p in directory.rglob("*") if p.is_file() and (suffixes is None or p.suffix in suffixes))
    paths.extend([BACKEND / "poetry.lock", BACKEND / "pyproject.toml", FRONTEND / "package-lock.json",
                  FRONTEND / "package.json", FRONTEND / "vite.config.ts", FRONTEND / "index.html",
                  FRONTEND / "playwright.fullstack.config.ts"])
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(str(path.relative_to(REPO)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


class Processes:
    """Reap exact process groups, including orphaned browser/build descendants."""

    def __init__(self, root: Path):
        self.root = root
        self.children: list[subprocess.Popen] = []

    def start(self, name, argv, env, *, cwd=None, pass_fds=()):
        with (self.root / f"{name}.log").open("xb") as log:
            child = subprocess.Popen(argv, cwd=cwd or self.root, env=env,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True, pass_fds=pass_fds, umask=0o077)
        self.children.append(child)
        return child

    @staticmethod
    def stop(child):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(child.pid, sig)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                continue
        return child.poll() is not None

    def run(self, name, argv, env, *, cwd=None, timeout=120):
        child = self.start(name, argv, env, cwd=cwd)
        try:
            require(child.wait(timeout=timeout) == 0, f"{name}_failed")
        finally:
            self.stop(child)

    def cleanup(self):
        outcomes = []
        for child in reversed(self.children):
            try:
                outcomes.append(self.stop(child))
            except Exception:
                outcomes.append(False)
        return all(outcomes)


class OwnedNeo4j:
    """One pinned container; cidfile + random ownership label fence all deletion."""

    def __init__(self, root, env, image):
        self.root, self.env, self.image = root, env, image
        self.owner = uuid.uuid4().hex
        self.cidfile = root / "neo4j.cid"
        self.cid = None
        self.port = high_port()

    def docker(self, *args, check=True):
        result = subprocess.run(["docker", *args], env=self.env, capture_output=True,
                                text=True, timeout=60, stdin=subprocess.DEVNULL)
        if result.returncode and check:
            private_file(self.root / f"neo4j-command-{uuid.uuid4().hex}.log", result.stderr)
        require(not check or result.returncode == 0, "neo4j_docker_command_failed")
        return result

    def inspect(self):
        require(bool(self.cid and re.fullmatch(r"[0-9a-f]{64}", self.cid)), "neo4j_id_missing")
        record = json.loads(self.docker("container", "inspect", self.cid).stdout)[0]
        require(record["Id"] == self.cid and record["Image"] == self.image
                and record["Config"]["Labels"].get(LABEL) == self.owner, "neo4j_ownership_mismatch")
        return record

    def start(self):
        image = json.loads(self.docker("image", "inspect", self.image).stdout)[0]
        require(image["Id"] == self.image and image["Os"] == "linux", "neo4j_image_mismatch")
        self.docker(
            "create", "--pull=never", "--name", f"nanfo-r09-neo4j-{self.owner}",
            "--cidfile", str(self.cidfile), "--label", f"{LABEL}={self.owner}",
            "--publish", f"127.0.0.1:{self.port}:7687", "--restart=no", "--log-driver=json-file",
            "--log-opt", "max-size=1m", "--log-opt", "max-file=1",
            "--memory=1g", "--cpus=1", "--pids-limit=256", "--security-opt=no-new-privileges",
            "--tmpfs", "/data:rw,nosuid,nodev,size=256m", "--tmpfs", "/logs:rw,nosuid,nodev,size=32m",
            "-e", "NEO4J_AUTH", "-e", "NEO4J_server_memory_heap_initial__size=256m",
            "-e", "NEO4J_server_memory_heap_max__size=256m",
            "-e", "NEO4J_db_tx__log_rotation_size=16M",
            "-e", "NEO4J_db_tx__log_preallocate=false",
            "-e", "NEO4J_db_tx__log_rotation_retention__policy=32M size",
            "-e", "NEO4J_server_memory_pagecache_size=64m", self.image,
        )
        self.cid = self.cidfile.read_text().strip()
        record = self.inspect()
        require(record["HostConfig"]["PortBindings"] == {
            "7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(self.port)}]}, "neo4j_binding_mismatch")
        require(not any(m["Type"] == "bind" for m in record["Mounts"]), "neo4j_unexpected_bind_mount")
        self.docker("start", self.cid)

    def cleanup(self):
        # Recover exact identity even when Docker create was interrupted.
        if self.cid is None and self.cidfile.exists():
            self.cid = self.cidfile.read_text().strip()
        if self.cid:
            self.inspect()
            self.docker("rm", "--force", "--volumes", self.cid)
            require(self.docker("container", "inspect", self.cid, check=False).returncode != 0,
                    "neo4j_container_remains")
        return port_free(self.port)


class ProductionFiles(SimpleHTTPRequestHandler):
    """Only the newly built public tree is served. SPA navigation falls back to index."""

    def log_message(self, *_args):
        pass

    def do_GET(self):  # noqa: N802 - stdlib handler API
        if self.path.split("?", 1)[0].startswith(("/ops/", "/login")):
            self.path = "/index.html"
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


async def seed_users():
    # Run in a clean child CWD/env before any application imports. No auth dependency replacement.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.core.security import hash_password
    from app.modules.identity.repository import UserRepository

    engine = create_async_engine(get_settings().POSTGRES_DSN)
    users = {}
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            repo = UserRepository(db)
            for name in ("owner", "member", "outsider"):
                password = secrets.token_urlsafe(32)
                email = f"r09-{name}@example.com"
                user = await repo.create(email, hash_password(password), f"R09 {name}")
                await repo.assign_role(user.user_id, "Admin" if name != "member" else "Operator")
                users[name] = {"email": email, "password": password, "user_id": str(user.user_id)}
            await db.commit()
        private_file(Path(os.environ["R09_FIXTURE"]), json.dumps({"users": users}))
    finally:
        await engine.dispose()


async def wait_neo4j(env):
    from neo4j import AsyncGraphDatabase

    async with AsyncGraphDatabase.driver(env["NEO4J_URI"], auth=("neo4j", env["NEO4J_PASSWORD"])) as driver:
        async with asyncio.timeout(120):
            while True:
                try:
                    await driver.verify_connectivity()
                    return
                except Exception:
                    await asyncio.sleep(0.5)


def wait_http(url, child=None):
    import httpx

    with httpx.Client(timeout=2, trust_env=False) as client:
        for _ in range(120):
            require(child is None or child.poll() is None, "http_process_exited")
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    raise AcceptanceFailure("http_readiness_timeout")


def seed_http(env, api):
    """Only identities are bootstrapped in SQL; all tenant/inventory writes use real HTTP."""
    import httpx

    fixture = json.loads(Path(env["R09_FIXTURE"]).read_text())
    with httpx.Client(base_url=api, timeout=20, trust_env=False) as client:
        def call(method, path, *, token=None, data=None, status=200):
            response = client.request(method, path, json=data, headers={
                "X-Request-ID": str(uuid.uuid4()), **({"Authorization": f"Bearer {token}"} if token else {}),
            })
            require(response.status_code == status, "http_seed_status_failed")
            payload = response.json()
            require(payload["success"] is True and set(payload) == {"success", "data", "meta", "errors"},
                    "http_seed_envelope_failed")
            return payload["data"]

        tokens = {}
        for name, user in fixture["users"].items():
            tokens[name] = call("POST", "/api/v1/auth/login", data={k: user[k] for k in ("email", "password")})["access_token"]
        for name in ("owner", "outsider"):
            token = tokens[name]
            org = call("POST", "/api/v1/organizations", token=token,
                       data={"name": f"R09 {name}", "slug": f"r09-{name}"}, status=201)
            workspace = call("POST", f"/api/v1/organizations/{org['org_id']}/workspaces", token=token,
                             data={"name": f"R09 {name} workspace"}, status=201)
            fixture[name] = {"org_id": org["org_id"], "workspace_id": workspace["workspace_id"]}
        owner = fixture["owner"]
        call("POST", f"/api/v1/organizations/{owner['org_id']}/members", token=tokens["owner"],
             data={"user_id": fixture["users"]["member"]["user_id"], "org_role": "Operator"}, status=201)
        networks = []
        for i in range(21):
            networks.append(call("POST", "/api/v1/networks", token=tokens["owner"], status=201,
                                 data={"workspace_id": owner["workspace_id"], "name": f"R09 network {i + 1:02d}"}))
        owner["network_id"] = networks[0]["network_id"]
        for i in range(21):
            call("POST", f"/api/v1/networks/{owner['network_id']}/devices", token=tokens["owner"], status=201,
                 data={"hostname": f"r09-device-{i + 1:02d}", "device_type": "switch"})
        # Await the real outbox/Redis/topology consumer; an empty graph must not mask a broken worker.
        for _ in range(120):
            graph = call("GET", f"/api/v1/topology/graph?network_id={owner['network_id']}", token=tokens["owner"])
            if len(graph["nodes"]) == 21:
                break
            time.sleep(0.5)
        else:
            raise AcceptanceFailure("inventory_topology_projection_timeout")
    # Credentials stay private and are removed on every exit. Never print HTTP bodies.
    Path(env["R09_FIXTURE"]).write_text(json.dumps(fixture))


def validate_counts(counts):
    require(counts is not None and counts["total"] >= 5, "browser_results_missing_or_incomplete")
    require(counts["failed"] == counts["errors"] == counts["skipped"] == 0
            and counts["passed"] == counts["total"], "browser_results_not_zero_skip_pass")


def browser_results(path):
    try:
        return junit_counts(path), junit_failures(path)
    except (ET.ParseError, OSError):
        return None, []


def main(argv=None):
    if argv is None and sys.argv[1:] == ["--internal-seed"]:
        asyncio.run(seed_users())
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    redis = parser.add_mutually_exclusive_group(required=True)
    redis.add_argument("--redis-server", type=Path, help="absolute installed Redis/Valkey7+ binary")
    redis.add_argument("--redis-image-id", type=exact_image, help="exact local Redis7+ image; never pulled")
    parser.add_argument("--neo4j-image-id", required=True, type=exact_image, help="exact local Neo4j5 community image")
    parser.add_argument("--report", required=True, type=Path, help="new credential-free JSON in existing directory")
    parser.add_argument("--timeout", type=int, default=900, help="browser wall-clock seconds, 60..1800")
    parser.add_argument("--private-diagnostics", type=Path, help="new UID-private failure-log directory; never publish")
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        parser.error("run as a dedicated non-root UID (Postgres and protected asset store require it)")
    if not 60 <= args.timeout <= 1800:
        parser.error("timeout must be 60..1800 seconds")
    if args.report.exists() or not args.report.parent.is_dir():
        parser.error("report must be new, with an existing parent")
    if args.private_diagnostics and (args.private_diagnostics.exists() or not args.private_diagnostics.parent.is_dir()):
        parser.error("private diagnostics must be a new directory with an existing parent")
    clean = clean_environment()
    if not all(shutil.which(name, path=clean.get("PATH")) for name in ("initdb", "postgres", "docker", "node")):
        parser.error("installed initdb/postgres, Docker and Node are mandatory")
    if args.redis_server:
        if not args.redis_server.is_absolute() or not args.redis_server.is_file():
            parser.error("redis-server must be an absolute installed executable")
        try:
            redis_version(args.redis_server)
        except (ValueError, OSError, subprocess.SubprocessError):
            parser.error("Redis/Valkey7+ executable required")
    for file in ("node_modules/vite/bin/vite.js", "node_modules/@playwright/test/cli.js"):
        if not (FRONTEND / file).is_file():
            parser.error("install locked frontend dependencies and Playwright Chromium first")
    parent = Path("/tmp/opencode")
    parent.mkdir(mode=0o700, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="nanfo-r09-", dir=parent))
    result = {"lane": "R09", "status": "failed", "stage": "preflight", "counts": None}
    result["runtime"] = {"python": sys.version.split()[0], "neo4j_image_id": args.neo4j_image_id,
                         "redis_image_id": args.redis_image_id, "uid": os.geteuid()}
    lab = neo = server = thread = listener = None
    processes = Processes(root)
    cleanup = {}
    code = 1

    def interrupted(signum, _frame):
        raise InterruptedError(signum)

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        result["source_sha256"] = source_digest()
        with environment(clean):
            lab = AuditLab(root, str(args.redis_server) if args.redis_server else None, args.redis_image_id)
        env = lab.env
        env.update(APP_ENV="production", EXECUTION_MODE="production", EMULATION_CONTROL_ENABLED="false",
                   PYTHONPATH=str(BACKEND), WORKER_HEARTBEAT_PATH="", WORKER_ITERATION_TIMEOUT_SECONDS="330",
                   RATE_LIMIT_LOGIN_MAX_ATTEMPTS="30", R09_FIXTURE=str(root / "fixture.json"))
        neo = OwnedNeo4j(root, {**clean, "NEO4J_AUTH": "neo4j/" + env["NEO4J_PASSWORD"]}, args.neo4j_image_id)
        env.update(NEO4J_USER="neo4j", NEO4J_URI=f"bolt://127.0.0.1:{neo.port}")
        # Reserve API socket and retain ownership until uvicorn inherits it.
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        api = f"http://127.0.0.1:{listener.getsockname()[1]}"
        dist = root / "dist"
        server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ProductionFiles, directory=str(dist)))
        origin = f"http://127.0.0.1:{server.server_port}"
        env["CORS_ALLOW_ORIGINS"] = origin
        browser_env = {**clean, "R09_FIXTURE": env["R09_FIXTURE"], "R09_BASE_URL": origin,
                       "R09_API_URL": api, "R09_OUTPUT": str(root / "browser"),
                       "R09_JUNIT": str(root / "browser.xml"), "R09_PRODUCTION_BUILD": "1"}
        result["stage"] = "production_build"
        processes.run("build", ["node", str(FRONTEND / "node_modules/vite/bin/vite.js"), "build", "--mode",
                      "production", "--outDir", str(dist), "--minify", "terser"],
                      {**clean, "VITE_API_BASE_URL": api, "VITE_WS_BASE_URL": api.replace("http:", "ws:"),
                       "VITE_ENABLE_MOCK_WS": "false"},
                      cwd=FRONTEND, timeout=240)
        require((dist / "index.html").is_file() and any((dist / "assets").glob("*.js")), "build_output_missing")
        result["build_sha256"] = {str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(dist.rglob("*")) if p.is_file()}
        result["stage"] = "owned_stores"
        lab.start_postgres()
        lab.start_redis()
        neo.start()
        asyncio.run(wait_neo4j(env))
        result["stage"] = "migration"
        migration = ("from alembic.config import Config; from alembic import command; "
                     f"c=Config({str(BACKEND / 'alembic/alembic.ini')!r}); "
                     f"c.set_main_option('script_location', {str(BACKEND / 'alembic')!r}); command.upgrade(c, 'head')")
        processes.run("migration", [sys.executable, "-c", migration], env)
        processes.run("seed", [sys.executable, "-m", "scripts.review_fullstack", "--internal-seed"], env)
        result["stage"] = "api_and_workers"
        api_child = processes.start("api", [sys.executable, "-m", "uvicorn", "app.main:app", "--fd",
                                    str(listener.fileno()), "--no-access-log", "--log-level", "critical"],
                                    env, pass_fds=(listener.fileno(),))
        listener.close()
        listener = None
        wait_http(api + "/ready", api_child)
        workers = [processes.start(name, [sys.executable, "-m", f"scripts.run_{name}_worker"],
                                   {**env, "WORKER_HEARTBEAT_PATH": str(root / f"heartbeat-{name}")})
                   for name in ("network_outbox", "report", "simulation")]
        result["stage"] = "authenticated_http_seed"
        seed_http(env, api)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        wait_http(origin)
        result["stage"] = "production_browser"
        processes.run("playwright", ["node", str(FRONTEND / "node_modules/@playwright/test/cli.js"), "test",
                      "--config", "playwright.fullstack.config.ts"], browser_env, cwd=FRONTEND, timeout=args.timeout)
        require(all(child.poll() is None for child in [api_child, *workers]), "runtime_exited")
        result["counts"], _ = browser_results(root / "browser.xml")
        validate_counts(result["counts"])
        result["source_sha256_after"] = source_digest()
        require(result["source_sha256_after"] == result["source_sha256"], "source_mutated_during_acceptance")
        result.update(status="passed", stage="complete")
        code = 0
    except (Exception, KeyboardInterrupt) as exc:
        # Fixed failure codes only; HTTP bodies, credentials, stacks and socket URLs stay private.
        result["failure"] = str(exc) if isinstance(exc, AcceptanceFailure) else type(exc).__name__
        result["counts"], result["failed_cases"] = browser_results(root / "browser.xml")
    finally:
        # Do not let a second TERM interrupt exact-resource cleanup.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if listener:
            listener.close()
        if server:
            if thread:
                server.shutdown()
                thread.join(timeout=10)
            server.server_close()
            cleanup["frontend_port_closed"] = port_free(server.server_port)
        if "api" in locals():
            api_port = int(api.rsplit(":", 1)[1])
        cleanup["process_groups_reaped"] = processes.cleanup()
        if "api_port" in locals():
            cleanup["api_port_closed"] = port_free(api_port)
        if code and neo and neo.cid:
            try:
                neo.inspect()
                logs = neo.docker("logs", neo.cid, check=False)
                private_file(root / "neo4j.log", logs.stdout + logs.stderr)
            except Exception:
                pass
        if code and args.private_diagnostics:
            try:
                args.private_diagnostics.mkdir(mode=0o700)
                for path in [*root.glob("*.log"), root / "browser.xml"]:
                    if path.is_file():
                        destination = args.private_diagnostics / path.name
                        shutil.copyfile(path, destination)
                        destination.chmod(0o600)
                if (root / "browser").is_dir():
                    shutil.copytree(root / "browser", args.private_diagnostics / "browser")
            except OSError:
                result["diagnostic_preservation_failed"] = True
        try:
            cleanup["neo4j_removed"] = neo.cleanup() if neo else True
        except Exception:
            cleanup["neo4j_removed"] = False
        try:
            if lab:
                cleanup.update({key: value for key, value in lab.cleanup().items() if key != "owned_pids"})
            else:
                shutil.rmtree(root)
                cleanup["private_tree_removed"] = not root.exists()
        except Exception:
            cleanup["stores_and_private_tree_removed"] = False
        if not all(cleanup.values()):
            result["status"], code = "cleanup_failed", 1
        result["cleanup"] = cleanup
        signal.signal(signal.SIGTERM, previous)
        serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
        with args.report.open("x") as handle:
            handle.write(serialized)
        print(json.dumps({key: value for key, value in result.items() if key != "build_sha256"}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
