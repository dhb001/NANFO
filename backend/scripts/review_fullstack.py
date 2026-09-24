"""ADR027 R09 / ADR-028 C22: production gateway browser lane.

The minified frontend is built WITHOUT VITE_API_BASE_URL (same-origin API and
WebSocket, C16) and served through the real deploy/nginx.conf by the host nginx
binary (temporary prefix; only listener, host paths and the upstream include point
at the owned local API). Playwright runs against the gateway origin, against
exact-owned authenticated stores/workers.

From backend: poetry run python -m scripts.review_fullstack --help
No supplied service URLs, shared Compose resources, auth overrides, or skip mode.
"""

from __future__ import annotations

import argparse
import asyncio
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
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.audit_isolated_suite import AuditLab, junit_counts, redis_version
from scripts.verify_measured_twin import (
    BACKEND, AcceptanceFailure, environment, high_port, port_free, private_file, require,
)

REPO = BACKEND.parent
FRONTEND = REPO / "frontend"
LABEL = "org.nanfo.adr027.fullstack"
GATEWAY_TEMPLATE = REPO / "deploy/nginx.conf"
UPSTREAM_INCLUDE = "include /etc/nginx/nginx-upstream.conf;"
MIME_TYPES = Path("/etc/nginx/mime.types")
# The browser must never be granted cross-origin API access in this lane: only the
# same-origin gateway path can work (C16/C22).
NO_CROSS_ORIGIN = "http://cross-origin.invalid"
# A production bundle must not embed the development loopback API default (C16).
LOOPBACK_API = re.compile(rb"(?:127\.0\.0\.1|localhost|\[::1\]):8000")
MAX_FAILED_CASES = 50
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# Evidence policy: failure summaries never carry tokens, credentials, identifiers,
# socket origins or private paths. Order matters (most specific first).
REDACTIONS = (
    (re.compile(r"eyJ[\w-]{4,}\.[\w-]{4,}\.[\w-]{4,}"), "<jwt>"),
    (re.compile(r"(?i)\bbearer\s+\S+"), "Bearer <redacted>"),
    (re.compile(r"(?i)\bnanfo\.bearer\.\S+"), "nanfo.bearer.<redacted>"),
    (re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@"), "<credential-url>@"),
    (re.compile(r"(?i)([?&#][\w.-]*(?:token|key|secret|password|passwd|code|sig|session)[\w.-]*=)[^&\s\"']*"),
     r"\1<redacted>"),
    (re.compile(r"(?i)\b(?:https?|wss?)://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?"), "<loopback>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"(?:/(?:tmp|home|root|var|run|opt|proc|github|__w)/)[^\s:'\"()]*"), "<path>"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
    (re.compile(r"\b[0-9a-fA-F]{24,}\b"), "<hex>"),
    (re.compile(r"(?<![\w/])[A-Za-z0-9_-]{32,}(?![\w/])"), "<opaque>"),
)
ERROR_LINE = re.compile(r"^\s*(?P<cls>(?:[A-Z][A-Za-z0-9]*)?Error)\b:?\s*(?P<text>.*)$", re.MULTILINE)


def redact(text: str, limit: int = 240) -> str:
    """Single redacted line for the credential-free report."""
    value = ANSI.sub("", text or "")
    for pattern, replacement in REDACTIONS:
        value = pattern.sub(replacement, value)
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def failed_case_details(path: Path) -> list[dict[str, str]]:
    """Per failing case: name, error class and redacted first error line (C22)."""
    try:
        cases = ET.parse(path).getroot().iter("testcase")
    except (ET.ParseError, OSError):
        return []
    details = []
    for case in cases:
        problem = next((case.find(tag) for tag in ("failure", "error") if case.find(tag) is not None), None)
        if problem is None:
            continue
        body = ANSI.sub("", "\n".join(part for part in (problem.text or "", problem.get("message") or "") if part))
        match = ERROR_LINE.search(body)
        first = (f"{match['cls']}: {match['text']}" if match
                 else next((line for line in body.splitlines() if line.strip()), ""))
        name = " > ".join(part for part in (case.get("classname"), case.get("name")) if part)
        details.append({
            "case": redact(name, 200),
            "outcome": problem.tag,
            "error_class": match["cls"] if match else (problem.get("type") or problem.tag).strip()[:64],
            "first_error_line": redact(first),
        })
        if len(details) >= MAX_FAILED_CASES:
            break
    return details


def build_environment(clean: dict[str, str]) -> dict[str, str]:
    """Production build inputs: no API/WS base URL, so the bundle is same-origin (C16)."""
    env = {key: value for key, value in clean.items() if not key.startswith("VITE_")}
    env["VITE_ENABLE_MOCK_WS"] = "false"
    return env


def embedded_loopback_api(dist: Path) -> bool:
    """True when any built file carries a loopback API origin (dev default leaked into prod)."""
    return any(LOOPBACK_API.search(path.read_bytes()) for path in dist.rglob("*") if path.is_file())


def browser_environment(clean: dict[str, str], *, fixture: Path, origin: str, output: Path,
                        junit: Path) -> dict[str, str]:
    """Playwright talks to the gateway origin only: page, API and WebSocket are same-origin."""
    return {**clean, "R09_FIXTURE": str(fixture), "R09_BASE_URL": origin, "R09_API_URL": origin,
            "R09_OUTPUT": str(output), "R09_JUNIT": str(junit), "R09_PRODUCTION_BUILD": "1"}


def playwright_argv(*, traces: bool) -> list[str]:
    argv = ["node", str(FRONTEND / "node_modules/@playwright/test/cli.js"), "test",
            "--config", "playwright.fullstack.config.ts"]
    # Traces embed page screenshots and the run's ephemeral credentials. They are
    # recorded only for failing tests and only when failure artifacts are requested.
    return [*argv, "--trace", "retain-on-failure"] if traces else argv


def render_gateway_config(template: str, *, prefix: Path, dist: Path, upstream: Path, port: int,
                          deploy: Path = REPO / "deploy") -> str:
    """The production gateway config with only host-local substitutions.

    Security headers, CSP, proxy rules, WebSocket upgrade handling and logging stay
    byte-for-byte production. Unknown shape changes fail instead of being guessed.
    """
    require(template.count(UPSTREAM_INCLUDE) == 1, "gateway_upstream_include_changed")
    # Template-internal runtime paths first, before any host path (which may itself
    # live under /tmp) is inserted.
    config = re.sub(r"\bworker_processes\s+[^;]+;", "worker_processes 1;", template)
    config = config.replace("/tmp/", f"{prefix}/")
    config = config.replace("/dev/stderr", str(prefix / "error.log")).replace("/dev/stdout", str(prefix / "access.log"))
    config = config.replace(UPSTREAM_INCLUDE, f'include "{upstream}";')
    # Other /etc/nginx includes must be the host mime.types or files shipped from deploy/.
    for name in re.findall(r"include\s+/etc/nginx/([\w.-]+);", config):
        if name == "mime.types":
            continue
        require((deploy / name).is_file(), "gateway_unknown_include")
        config = config.replace(f"include /etc/nginx/{name};", f'include "{deploy / name}";')
    listen = re.compile(r"\blisten\s+8080\b[^;]*;")
    require(len(listen.findall(config)) == 1, "gateway_listener_changed")
    config = listen.sub(f"listen 127.0.0.1:{port};", config)
    require(config.count("/usr/share/nginx/html") == 1, "gateway_root_changed")
    config = config.replace("/usr/share/nginx/html", str(dist))
    require("/usr/share/nginx" not in config and "/dev/std" not in config, "gateway_unrendered_path")
    return config


def write_gateway(prefix: Path, dist: Path, api_port: int, port: int) -> Path:
    prefix.mkdir(mode=0o700)
    upstream = prefix / "nginx-upstream.conf"
    upstream.write_text(f"upstream nanfo_api {{ server 127.0.0.1:{api_port}; }}\n")
    config = prefix / "nginx.conf"
    config.write_text(render_gateway_config(GATEWAY_TEMPLATE.read_text(), prefix=prefix, dist=dist,
                                            upstream=upstream, port=port))
    return config


def export_failure_artifacts(browser: Path, destination: Path) -> None:
    """Copy only Playwright output (traces/screenshots) for a short-retention CI artifact.

    Regular files only: symlinks and special files are never followed or copied.
    """
    destination.mkdir(mode=0o700)
    target = destination / "playwright"
    if browser.is_dir():
        for path in sorted(browser.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            copy = target / path.relative_to(browser)
            copy.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(path, copy, follow_symlinks=False)
            copy.chmod(0o600)
    (destination / "README.txt").write_text(
        "R09/C22 failure artifacts: Playwright traces and screenshots of failing tests only.\n"
        "They contain this run's ephemeral users, passwords and tokens. The database, Redis,\n"
        "Neo4j and JWT key were generated for the run and destroyed at cleanup, so nothing\n"
        "here authenticates anywhere. Service logs stay in --private-diagnostics.\n")


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
                  FRONTEND / "playwright.fullstack.config.ts", GATEWAY_TEMPLATE])
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
    """(counts, per-failing-case details); unreadable/interrupted XML never blocks cleanup."""
    try:
        return junit_counts(path), failed_case_details(path)
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
    parser.add_argument("--failure-artifacts", type=Path,
                        help="new directory for Playwright traces/screenshots of failing tests (short-retention CI artifact)")
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        parser.error("run as a dedicated non-root UID (Postgres and protected asset store require it)")
    if not 60 <= args.timeout <= 1800:
        parser.error("timeout must be 60..1800 seconds")
    if args.report.exists() or not args.report.parent.is_dir():
        parser.error("report must be new, with an existing parent")
    for option, directory in (("private diagnostics", args.private_diagnostics),
                              ("failure artifacts", args.failure_artifacts)):
        if directory and (directory.exists() or not directory.parent.is_dir()):
            parser.error(f"{option} must be a new directory with an existing parent")
    clean = clean_environment()
    if not all(shutil.which(name, path=clean.get("PATH")) for name in ("initdb", "postgres", "docker", "node", "nginx")):
        parser.error("installed initdb/postgres, Docker, Node and nginx are mandatory")
    nginx = shutil.which("nginx", path=clean.get("PATH"))
    if not MIME_TYPES.is_file() or not GATEWAY_TEMPLATE.is_file():
        parser.error("the production gateway needs deploy/nginx.conf and the host /etc/nginx/mime.types")
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
                         "redis_image_id": args.redis_image_id, "uid": os.geteuid(),
                         "gateway": "deploy/nginx.conf", "same_origin": True}
    lab = neo = listener = None
    gateway_port = None
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
                   RATE_LIMIT_LOGIN_MAX_ATTEMPTS="30", R09_FIXTURE=str(root / "fixture.json"),
                   # No cross-origin grant: only the same-origin gateway path can work (C16/C22).
                   CORS_ALLOW_ORIGINS=NO_CROSS_ORIGIN)
        neo = OwnedNeo4j(root, {**clean, "NEO4J_AUTH": "neo4j/" + env["NEO4J_PASSWORD"]}, args.neo4j_image_id)
        env.update(NEO4J_USER="neo4j", NEO4J_URI=f"bolt://127.0.0.1:{neo.port}")
        # Reserve API socket and retain ownership until uvicorn inherits it.
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        api_port = listener.getsockname()[1]
        api = f"http://127.0.0.1:{api_port}"
        dist = root / "dist"
        gateway_port = high_port()
        origin = f"http://127.0.0.1:{gateway_port}"
        browser_env = browser_environment(clean, fixture=root / "fixture.json", origin=origin,
                                          output=root / "browser", junit=root / "browser.xml")
        result["stage"] = "production_build"
        processes.run("build", ["node", str(FRONTEND / "node_modules/vite/bin/vite.js"), "build", "--mode",
                      "production", "--outDir", str(dist), "--minify", "terser"],
                      build_environment(clean), cwd=FRONTEND, timeout=240)
        require((dist / "index.html").is_file() and any((dist / "assets").glob("*.js")), "build_output_missing")
        require(not embedded_loopback_api(dist), "build_embeds_loopback_api_origin")
        result["build_sha256"] = {str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(dist.rglob("*")) if p.is_file()}
        result["stage"] = "gateway_config"
        gateway_root = root / "gateway"
        gateway_config = write_gateway(gateway_root, dist, api_port, gateway_port)
        gateway_argv = [nginx, "-p", str(gateway_root), "-e", str(gateway_root / "error.log"), "-c", str(gateway_config)]
        processes.run("gateway-config-test", [*gateway_argv, "-t"], clean, timeout=30)
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
        result["stage"] = "production_gateway"
        gateway = processes.start("gateway", [*gateway_argv, "-g", "daemon off;"], clean)
        wait_http(origin + "/", gateway)
        # The API is reachable through the gateway, i.e. the same origin as the UI.
        wait_http(origin + "/ready", gateway)
        result["stage"] = "production_browser"
        processes.run("playwright", playwright_argv(traces=args.failure_artifacts is not None), browser_env,
                      cwd=FRONTEND, timeout=args.timeout)
        require(all(child.poll() is None for child in [api_child, *workers, gateway]), "runtime_exited")
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
        cleanup["process_groups_reaped"] = processes.cleanup()
        if "api_port" in locals():
            cleanup["api_port_closed"] = port_free(api_port)
        if gateway_port is not None:
            cleanup["gateway_port_closed"] = port_free(gateway_port)
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
                for path in [*root.glob("*.log"), *(root / "gateway").glob("*.log"), root / "browser.xml"]:
                    if path.is_file():
                        destination = args.private_diagnostics / (
                            f"gateway-{path.name}" if path.parent.name == "gateway" else path.name)
                        shutil.copyfile(path, destination)
                        destination.chmod(0o600)
                if (root / "browser").is_dir():
                    shutil.copytree(root / "browser", args.private_diagnostics / "browser")
            except OSError:
                result["diagnostic_preservation_failed"] = True
        if code and args.failure_artifacts:
            try:
                export_failure_artifacts(root / "browser", args.failure_artifacts)
                result["failure_artifacts"] = "playwright traces/screenshots exported"
            except OSError:
                result["failure_artifact_export_failed"] = True
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
