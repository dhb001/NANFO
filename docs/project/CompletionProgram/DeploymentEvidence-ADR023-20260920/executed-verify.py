"""Opt-in, container-only ADR020 acceptance. Never targets an existing project."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATTERN = re.compile(r"nanfo-deploy-verify-[0-9a-f]{32}\Z")
CASES = (
    "disk_capacity",
    "installed_source_parity",
    "package_contract",
    "locked_container_build",
    "fresh_volumes",
    "migration_0027",
    "bootstrap_login",
    "frontend_http",
    "full_stack_readiness",
    "distributed_failover",
    "simulation",
    "report_csv",
    "report_pdf",
    "spatial_asset_upload",
    "database_stop_readiness",
    "worker_stale_heartbeat",
    "api_worker_restart",
    "nonempty_archive_delete",
    "restored_archive_bytes",
    "lab_binding",
    "lab_congestion",
    "model_diagnostic",
    "coordinated_encrypted_backup",
    "distinct_fresh_restore",
    "restore_image_schema",
    "old_tokens_invalid",
    "restored_report_bytes",
    "restored_spatial_assets",
    "restored_workflows",
    "restored_telemetry",
    "source_unchanged",
    "campaign",
    "cleanup",
)
WORKERS = (
    "network-outbox-worker",
    "simulation-worker",
    "report-worker",
    "alert-worker",
    "execution-worker",
    "autonomy-worker",
)
STORES = ("postgres", "redis", "neo4j")


class VerificationError(Exception):
    """Only constant, credential-free messages may be emitted from this exception."""


class Blocked(VerificationError):
    pass


def check(condition, message):
    if not condition:
        raise VerificationError(message)


def private_write(path, value):
    data = (
        value
        if isinstance(value, bytes)
        else (json.dumps(value, indent=2) + "\n").encode()
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    return hashlib.sha256(value).hexdigest()


def run(
    args, *, env=None, stdin=None, timeout=120, safe_errors=(), private_diagnostic=None
):
    """Commands never inherit application settings, print output, or expose stdin."""
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "XDG_RUNTIME_DIR")
        if key in os.environ
    }
    environment.update(env or {})
    process = subprocess.Popen(
        [str(arg) for arg in args],
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        cwd=ROOT,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(input=stdin, timeout=timeout)
    except BaseException as error:
        # Kill CLI descendants as well as the operator parent before registering
        # leftovers. No background Docker client may race resource cleanup.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=5)
        if isinstance(error, subprocess.TimeoutExpired):
            raise VerificationError(
                "Command deadline exceeded; output withheld"
            ) from None
        raise
    if process.returncode and private_diagnostic is not None:
        private_write(private_diagnostic, stderr[:65536] + b"\nPRIVATE STDOUT\n" + stdout[-65536:])
    if process.returncode and safe_errors and len(stderr) <= 16384:
        try:
            diagnostic = json.loads(stderr)
        except (ValueError, UnicodeError):
            diagnostic = None
        if isinstance(diagnostic, dict) and diagnostic.get("status") == "refused":
            try:
                from deploy.backup_restore import STAGES
            except ModuleNotFoundError:
                from backup_restore import STAGES
            stage, error_type = diagnostic.get("stage"), diagnostic.get("error_type")
            if stage in STAGES and error_type in {
                "OperationError",
                "OSError",
                "ValueError",
                "KeyError",
                "TypeError",
                "CalledProcessError",
                "TimeoutExpired",
                "TarError",
                "ModuleNotFoundError",
                "ImportError",
                "PermissionError",
                "FileNotFoundError",
            }:
                raise VerificationError(
                    f"Operator refused at {stage} ({error_type}); private diagnostic retained"
                )
            reason = diagnostic.get("reason")
            if isinstance(reason, str) and reason in safe_errors:
                raise VerificationError("Operator refused: " + reason)
    check(
        process.returncode == 0,
        "Command failed ("
        + str(args[0])
        + ", exit "
        + str(process.returncode)
        + "); output withheld",
    )
    check(len(stdout) <= 16 * 1024 * 1024, "Command response exceeds bound")
    return stdout


def until(action, predicate=bool, *, timeout=180):
    deadline = time.monotonic() + timeout
    while True:
        value = action()
        if predicate(value):
            return value
        if time.monotonic() >= deadline:
            raise VerificationError("Readiness/progress deadline exceeded")
        time.sleep(1)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class API:
    def __init__(self, origin):
        check(
            re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", origin),
            "Non-loopback gateway refused",
        )
        self.origin = origin
        self.token = ""
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def raw(self, method, path, *, body=None, params=None, headers=None, timeout=10):
        check(path.startswith("/") and not path.startswith("//"), "Invalid API path")
        url = self.origin + path + ("?" + urlencode(params) if params else "")
        request_headers = {"Accept": "application/json"}
        if self.token:
            request_headers["Authorization"] = "Bearer " + self.token
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        request = Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers=request_headers,
            method=method,
        )
        try:
            response = self.opener.open(request, timeout=timeout)
        except HTTPError as error:
            response = error
        except (URLError, TimeoutError, ConnectionError):
            return 0, {}, b""
        with response:
            data = response.read(16 * 1024 * 1024 + 1)
            check(len(data) <= 16 * 1024 * 1024, "HTTP response exceeds bound")
            return response.code, response.headers, data

    def request(self, method, path, *, expected=200, **kwargs):
        status, _, raw = self.raw(method, path, **kwargs)
        check(
            status == expected,
            f"HTTP {method} {path}: got {status}, expected {expected}",
        )
        value = json.loads(raw)
        check(value.get("success") is (expected < 400), "Canonical envelope mismatch")
        return value["data"] if expected < 400 else value["errors"]

    def ready(self):
        status, _, raw = self.raw("GET", "/ready")
        if status != 200:
            return False
        value = json.loads(raw)
        data = value.get("data", {})
        realtime = data.get("realtime", {})
        delegated = (
            realtime.get("mode") == "distributed"
            and realtime.get("role") == "follower"
            and realtime.get("local_consumer_count") == 0
            and realtime.get("local_collector") is False
            and data.get("checks", {}).get("realtime_subscription") == "ok"
        )
        check(
            value.get("success") is True
            and value.get("data", {}).get("ready") is True
            and bool(value["data"].get("checks"))
            and all(
                status == "ok" or (key == "api_consumers" and status == "delegated" and delegated)
                for key, status in value["data"]["checks"].items()
            ),
            "Readiness envelope invalid",
        )
        return True


class Matrix:
    def __init__(self):
        self.guard = None
        self.progress = False
        self.rows = {
            name: {"status": "pending", "detail": "Not executed"} for name in CASES
        }

    def case(self, name, action, *, record=True):
        if self.progress:
            print(json.dumps({"case": name, "status": "starting"}), flush=True)
        if self.guard and name not in {"cleanup", "disk_capacity", "campaign"}:
            self.guard()
        try:
            detail = action()
        except Blocked as error:
            self.rows[name] = {"status": "blocked", "detail": str(error)}
            return None
        except BaseException as error:
            self.rows[name] = {
                "status": "failed",
                "detail": str(error)
                if isinstance(error, VerificationError)
                else type(error).__name__,
            }
            raise
        self.rows[name] = {
            "status": "passed",
            "detail": (detail or "Verified")
            if record
            else "Verified; sensitive runtime value not recorded",
        }
        return detail

    def block(self, name, reason):
        self.rows[name] = {"status": "blocked", "detail": reason}

    def result(self, *, final=False):
        rows = {name: dict(row) for name, row in self.rows.items()}
        if final:
            for row in rows.values():
                if row["status"] == "pending":
                    row.update(status="blocked", detail="Prerequisite did not complete")
        core = [
            row
            for name, row in rows.items()
            if name
            not in {
                "lab_binding",
                "lab_congestion",
                "model_diagnostic",
                "restored_telemetry",
                "distributed_failover",
            }
            or name == "distributed_failover" and row["status"] != "blocked"
        ]
        core_passed = all(row["status"] == "passed" for row in core)
        return {
            "cases": rows,
            "core_passed": core_passed,
            "all_green": all(row["status"] == "passed" for row in rows.values()),
            "step15_complete": core_passed
            and all(
                rows[name]["status"] == "passed"
                for name in ("lab_binding", "lab_congestion", "restored_telemetry")
            ),
            "counts": {
                status: sum(row["status"] == status for row in rows.values())
                for status in ("passed", "failed", "blocked", "pending")
            },
        }


def validate_compose(config, project, private_root):
    """Reject dangerous inputs before Docker can create or migrate anything."""
    check(PROJECT_PATTERN.fullmatch(project), "Unowned project refused")
    services = config.get("services", {})
    check(
        {*STORES, *WORKERS, "api", "gateway"}.issubset(services),
        "Full package services missing",
    )
    volumes = config.get("volumes", {})
    check(bool(volumes), "Persistent volumes missing")
    for value in volumes.values():
        check(
            not value.get("external") and not value.get("driver_opts"),
            "External/host-backed volume refused",
        )
        check(
            value.get("name", "").startswith(project + "_"),
            "Unowned volume name refused",
        )
    for value in config.get("networks", {}).values():
        check(not value.get("external"), "External network refused")
        check(
            value.get("name", "").startswith(project + "_"),
            "Unowned network name refused",
        )
    for name, service in services.items():
        check(not service.get("container_name"), "Fixed container name refused")
        check(
            service.get("network_mode") in {None, "none"}
            and not service.get("pid")
            and not service.get("ipc"),
            "Host/shared namespaces refused",
        )
        check(not service.get("devices"), "Host device mount refused")
        if service.get("privileged"):
            check(
                name == "lab"
                and service.get("network_mode") == "none"
                and "lab" in service.get("profiles", []),
                "Privilege outside disconnected opt-in lab",
            )
        ports = service.get("ports", [])
        if name != "gateway":
            check(not ports, "Non-gateway host port refused")
        else:
            check(
                len(ports) == 1
                and ports[0].get("host_ip") == "127.0.0.1"
                and str(ports[0].get("published", "0")) == "0",
                "Gateway must use random loopback publication",
            )
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                source = Path(mount["source"]).resolve()
                packaged_script = (
                    source == ROOT / "deploy" / "redis-entrypoint.sh"
                    and mount.get("read_only")
                    and mount.get("target") == "/deploy/redis-entrypoint.sh"
                )
                check(
                    source.is_relative_to(private_root.resolve()) or packaged_script,
                    "Bind outside new private run directory refused",
                )
            elif mount["type"] == "volume":
                check(
                    mount.get("source") in volumes,
                    "Anonymous/unregistered volume refused",
                )
            else:
                check(mount["type"] == "tmpfs", "Unsupported mount type")
        for category in ("secrets", "configs"):
            for mount in service.get(category, []):
                item = config.get(category, {}).get(mount["source"], {})
                check(
                    "file" in item
                    and (
                        Path(item["file"]).resolve().is_relative_to(private_root.resolve())
                        or category == "configs"
                        and item["file"] == str(ROOT / "deploy/nginx-distributed-upstream.conf")
                        and name == "gateway"
                    ),
                    "External secret/config refused",
                )
    if "api2" in services:
        for name in ("api", "api2"):
            check(
                str(services[name].get("environment", {}).get("API_REALTIME_DISTRIBUTED")).lower() == "true",
                "Two serving APIs require explicit distributed mode on both",
            )
        check(services["api"].get("volumes") == services["api2"].get("volumes"), "Distributed API storage differs")
    return {
        "volumes": sorted(value["name"] for value in volumes.values()),
        "services": sorted(services),
    }


class Stack:
    def __init__(self, project, files, env, registry):
        check(PROJECT_PATTERN.fullmatch(project), "Unowned project refused")
        self.project, self.files, self.env, self.registry = (
            project,
            files,
            env,
            registry,
        )
        self.config = None

    def compose(self, *args, timeout=120, stdin=None):
        command = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--env-file",
            "/dev/null",
        ]
        for path in self.files:
            command += ["-f", str(path)]
        if args and args[0] == "config":
            command += ["--profile", "*"]
        try:
            return run([*command, *args], env=self.env, timeout=timeout, stdin=stdin,
                       private_diagnostic=self.registry.directory / ("compose-" + uuid.uuid4().hex + ".private.log"))
        finally:
            if args and args[0] in {"create", "up", "run", "build", "restart"}:
                self.registry.register(self.project)

    def inspect_service(self, service):
        ids = self.compose("ps", "-aq", service).decode().split()
        check(len(ids) == 1, "Service container identity ambiguous")
        check(ids[0] in self.registry.containers, "Unregistered service container")
        row = json.loads(run(["docker", "inspect", ids[0]]))[0]
        check(
            row["Config"]["Labels"].get("com.docker.compose.project") == self.project,
            "Container ownership changed",
        )
        return row

    def signal(self, service, value):
        self.inspect_service(service)
        # init=true makes PID 1 tini. Freeze the PID in the actual work heartbeat,
        # leaving Docker's independent healthcheck process able to observe staleness.
        check(value in {"SIGSTOP", "SIGCONT"}, "Unsupported worker signal")
        self.compose(
            "exec",
            "-T",
            service,
            "python",
            "-c",
            "import json,os,signal; from pathlib import Path; "
            "p=Path(os.environ['WORKER_HEARTBEAT_PATH']+'.report'); "
            "pid=json.loads(p.read_text())['pid']; assert type(pid) is int and pid>1; "
            "os.kill(pid,signal." + value + ")",
        )

    def healthy(self, services):
        return all(
            self.inspect_service(name).get("State", {}).get("Health", {}).get("Status")
            == "healthy"
            for name in services
        )

    def gateway(self):
        row = self.inspect_service("gateway")
        ports = [
            port
            for values in row["NetworkSettings"]["Ports"].values()
            for port in (values or [])
        ]
        check(
            len(ports) == 1 and ports[0]["HostIp"] == "127.0.0.1",
            "Runtime gateway binding unsafe",
        )
        return API("http://127.0.0.1:" + ports[0]["HostPort"])


class Registry:
    """Only exact IDs/names observed under our pre-registered UUID labels are removed."""

    def __init__(self, directory):
        self.directory = directory
        self.preserve = False
        self.projects = set()
        self.containers, self.volumes, self.networks = {}, {}, {}

    def fresh(self, project):
        check(PROJECT_PATTERN.fullmatch(project), "Unowned project refused")
        check(project not in self.projects, "Project already registered")
        for kind in ("container", "volume", "network"):
            values = run(
                [
                    "docker",
                    kind,
                    "ls",
                    "-q",
                    "--filter",
                    "label=com.docker.compose.project=" + project,
                    *(["-a"] if kind == "container" else []),
                ]
            )
            check(
                not values.strip(),
                "Project already has resources; refusing fresh-start claim",
            )
        self.projects.add(project)

    def register(self, project):
        check(project in self.projects, "Project was not checked fresh")
        for kind, target in (
            ("container", self.containers),
            ("volume", self.volumes),
            ("network", self.networks),
        ):
            args = [
                "docker",
                kind,
                "ls",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + project,
            ]
            if kind == "container":
                args += ["-a", "--no-trunc"]
            for identity in run(args, timeout=15).decode().split():
                row = json.loads(
                    run(["docker", kind, "inspect", identity], timeout=15)
                )[0]
                labels = (
                    row["Config"].get("Labels", {})
                    if kind == "container"
                    else row.get("Labels", {})
                )
                check(
                    labels.get("com.docker.compose.project") == project,
                    "Resource ownership mismatch",
                )
                if kind == "volume":
                    check(
                        identity.startswith(project + "_"),
                        "Volume outside owned namespace",
                    )
                target[identity] = project
        # Append-only snapshots survive interruption without overwriting earlier evidence.
        private_write(
            self.directory / ("resources-" + uuid.uuid4().hex + ".json"),
            {
                "containers": self.containers,
                "volumes": self.volumes,
                "networks": self.networks,
            },
        )

    def cleanup(self, timeout=120):
        deadline = time.monotonic() + timeout
        failures = 0
        for kind, entries in (
            ("container", self.containers),
            ("network", self.networks),
            ("volume", self.volumes),
        ):
            if self.preserve and kind != "container":
                continue
            for identity, project in entries.items():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise VerificationError(
                        "Cleanup deadline exceeded; registered resources require review"
                    )
                try:
                    if kind == "container":
                        present = (
                            run(
                                [
                                    "docker",
                                    "container",
                                    "ls",
                                    "-aq",
                                    "--no-trunc",
                                    "--filter",
                                    "id=" + identity,
                                ],
                                timeout=min(10, remaining),
                            )
                            .decode()
                            .split()
                        )
                        if identity not in present:
                            continue  # Compose already removed this registered incarnation.
                    row = json.loads(
                        run(
                            ["docker", kind, "inspect", identity],
                            timeout=min(10, remaining),
                        )
                    )[0]
                    labels = (
                        row["Config"].get("Labels", {})
                        if kind == "container"
                        else row.get("Labels", {})
                    )
                    check(
                        labels.get("com.docker.compose.project") == project
                        and project in self.projects,
                        "Cleanup ownership changed",
                    )
                    if self.preserve:
                        if row["State"]["Running"]:
                            run(
                                ["docker", "stop", "--time", "5", identity],
                                timeout=max(0.1, min(10, deadline - time.monotonic())),
                            )
                        continue
                    run(
                        [
                            "docker",
                            kind,
                            "rm",
                            *(["-f"] if kind == "container" else []),
                            identity,
                        ],
                        timeout=max(0.1, min(15, deadline - time.monotonic())),
                    )
                except Exception:  # noqa: BLE001 - continue bounded cleanup without leaking Docker diagnostics
                    failures += 1
        check(
            not failures,
            "Registered resource cleanup failed; inspect private resource ledger",
        )
        if self.preserve:
            return {
                "capacity_abort": True,
                "owned_containers_stopped": True,
                "data_volumes_preserved": len(self.volumes),
            }
        return {
            "containers_removed": len(self.containers),
            "volumes_removed": len(self.volumes),
            "networks_removed": len(self.networks),
        }


def scenario():
    return {
        "version": 1,
        "seed": 7,
        "tick_ms": 100,
        "duration_ticks": 10,
        "links": [
            {
                "link_id": "ab",
                "source": "a",
                "target": "b",
                "capacity_mbps": 1.0,
                "buffer_bytes": 25000.0,
                "delay_ms": 0.0,
                "initial_queue_bytes": 0.0,
            }
        ],
        "flows": [
            {
                "flow_id": "f",
                "source": "a",
                "target": "b",
                "path": ["ab"],
                "demand_mbps": [2.0],
            }
        ],
        "action_binding": None,
        "limits": {
            "max_loss_pct": 100.0,
            "max_latency_ms": 10000.0,
            "min_throughput_mbps": 0.1,
        },
    }


def verify_simulation(api, network):
    job = api.request(
        "POST",
        "/api/v1/simulations/start",
        expected=202,
        body={
            "network_id": network,
            "scenario_name": "Package finite buffer",
            "scenario_config": scenario(),
        },
    )
    row = until(
        lambda: api.request("GET", "/api/v1/simulations/" + job["simulation_id"]),
        lambda value: value["state"] in {"completed", "failed"},
    )
    check(
        row["state"] == "completed" and row["risk_gate"] == "passed",
        "Simulation did not complete",
    )
    check(
        row["run_output"]["loss_pct"] == 45,
        "Independent finite-buffer loss expectation failed",
    )
    check(
        row["validation"]["source"] == "operator_configured_model"
        and row["validation"]["physical_safety_authorized"] is False,
        "Configured model provenance lost",
    )
    return row


def report_body(workspace, network, simulation, fmt):
    now = datetime.now(timezone.utc)
    return {
        "workspace_id": workspace,
        "network_id": network,
        "report_type": "executive_summary",
        "format": fmt,
        "date_range": {
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": (now + timedelta(minutes=1)).isoformat(),
        },
        "scope": {"simulation_ids": [simulation]},
    }


def download_report(api, workspace, job, fmt):
    path = "/api/v1/reports/" + job["report_id"]
    params = {"workspace_id": workspace}
    done = until(
        lambda: api.request("GET", path, params=params),
        lambda value: value["status"] in {"generated", "failed"},
    )
    check(done["status"] == "generated", "Report worker failed")
    status, headers, data = api.raw("GET", path + "/download", params=params)
    check(
        status == 200 and len(done["artifacts"]) == 1,
        "Report download/artifact count invalid",
    )
    artifact = done["artifacts"][0]
    check(
        len(data) == artifact["size_bytes"] == int(headers["Content-Length"]),
        "Report byte length mismatch",
    )
    check(digest(data) == artifact["checksum_sha256"], "Report SHA256 mismatch")
    check(
        headers["Content-Type"].split(";")[0] == artifact["media_type"],
        "Report media type mismatch",
    )
    if fmt == "csv":
        rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
        check(
            rows[0] == ["section", "row", "field", "value"]
            and any(
                "loss_pct" in row[2] and row[3] in {"45", "45.0"} for row in rows[1:]
            ),
            "CSV lacks actual simulation result",
        )
    else:
        check(
            data.startswith(b"%PDF-")
            and b"%%EOF" in data[-1024:]
            and b"/Type /Page" in data,
            "Downloaded PDF structure invalid",
        )
        # ReportLab's locked renderer uses ASCII85 + Flate page streams. Decode the
        # downloaded bytes independently, without installing a host PDF dependency.
        text = []
        for stream in re.findall(rb"stream\r?\n(.*?)endstream", data, re.DOTALL):
            stream = stream.strip()
            if stream.endswith(b"~>"):
                stream = base64.a85decode(stream[:-2])
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(stream, 2 * 1024 * 1024 + 1)
            check(
                len(decoded) <= 2 * 1024 * 1024 and decoder.eof,
                "PDF decoded stream bound/format invalid",
            )
            text.append(decoded)
        check(
            any(b"loss_pct" in page and b"45" in page for page in text),
            "PDF downloaded text lacks simulation result",
        )
    return {
        "report_id": done["report_id"],
        "sha256": digest(data),
        "size_bytes": len(data),
        "snapshot_sha256": done["snapshot_sha256"],
        "format": fmt,
    }


def frontend_smoke(api):
    status, headers, data = api.raw("GET", "/", headers={"Accept": "text/html"})
    check(
        status == 200 and "text/html" in headers.get("Content-Type", ""),
        "Frontend HTML unavailable",
    )
    check(b'id="root"' in data and b"<script" in data, "Frontend shell missing")
    assets = re.findall(rb'(?:src|href)="(/assets/[^"?#]+\.(?:js|css))"', data)
    check(bool(assets), "Built frontend assets missing")
    for asset in assets:
        status, asset_headers, content = api.raw("GET", asset.decode())
        check(
            status == 200
            and len(content) > 100
            and "text/html" not in asset_headers.get("Content-Type", ""),
            "Frontend asset served fallback HTML",
        )
    check(
        api.raw("GET", "/health")[0] == 200, "API liveness unavailable through gateway"
    )
    return {
        "html_bytes": len(data),
        "built_assets_fetched": len(assets),
        "browser_execution": "not tested; HTTP smoke only",
    }


def database_outage(stack, api):
    try:
        stack.compose("stop", "--timeout", "10", "postgres")

        def unavailable():
            status, _, raw = api.raw("GET", "/ready")
            if status != 503:
                return False
            value = json.loads(raw)
            return (
                value.get("success") is False
                and value["data"]["checks"].get("postgres") == "unavailable"
            )

        until(unavailable, timeout=40)
        check(
            api.raw("GET", "/health")[0] == 200,
            "Database outage incorrectly broke API liveness",
        )
    finally:
        stack.compose("start", "postgres")
    until(api.ready)
    until(lambda: stack.healthy(WORKERS))
    return "Actual PostgreSQL stop: /ready 503, /health 200; readiness and workers recovered"


def heartbeat_outage(stack):
    service = "report-worker"
    try:
        stack.signal(service, "SIGSTOP")

        def stale():
            row = stack.inspect_service(service)
            health = row["State"].get("Health", {})
            if health.get("Status") != "unhealthy":
                return False
            logs = health.get("Log", [])
            if not logs:
                return False
            # A generic probe failure (e.g. an exec error) is not stale-heartbeat proof.
            try:
                value = json.loads(logs[-1]["Output"])
            except (KeyError, ValueError):
                return False
            checks = value.get("checks", {})
            return (
                value.get("ready") is False
                and checks.get("postgres") == checks.get("redis") == "ok"
                and any(
                    key.startswith("heartbeat_") and status == "unavailable"
                    for key, status in checks.items()
                )
            )

        until(stale, timeout=480)
    finally:
        stack.signal(service, "SIGCONT")
    until(lambda: stack.healthy((service,)))
    return "Actual worker SIGSTOP produced stale-loop heartbeat with live stores; SIGCONT recovered"


def restart_with_pending_work(stack, api, workspace, network, simulation):
    stack.compose("stop", "--timeout", "15", "report-worker", "simulation-worker")
    pending_report = api.request(
        "POST",
        "/api/v1/reports/generate",
        expected=202,
        body=report_body(workspace, network, simulation, "csv"),
    )
    pending_sim = api.request(
        "POST",
        "/api/v1/simulations/start",
        expected=202,
        body={
            "network_id": network,
            "scenario_name": "Restart pending model",
            "scenario_config": scenario(),
        },
    )
    check(
        pending_report["status"] == "requested" and pending_sim["state"] == "queued",
        "Work was not durably queued with workers stopped",
    )
    old = {
        name: stack.inspect_service(name)["State"]["StartedAt"]
        for name in (*serving_apis(stack), *WORKERS)
    }
    stack.compose("restart", "--timeout", "15", *serving_apis(stack), *WORKERS, timeout=180)
    until(api.ready)
    until(lambda: stack.healthy(WORKERS))
    check(
        all(
            stack.inspect_service(name)["State"]["StartedAt"] != stamp
            for name, stamp in old.items()
        ),
        "API/worker process did not restart",
    )
    report = download_report(api, workspace, pending_report, "csv")
    simulation_row = until(
        lambda: api.request(
            "GET", "/api/v1/simulations/" + pending_sim["simulation_id"]
        ),
        lambda value: value["state"] in {"completed", "failed"},
    )
    check(
        simulation_row["state"] == "completed"
        and simulation_row["run_output"]["loss_pct"] == 45,
        "Restart lost pending simulation",
    )
    return {
        "report": report,
        "simulation_id": simulation_row["simulation_id"],
        "restarted_services": list(old),
    }


def bind_lab(stack, api):
    """Read topology from the installed image; create inventory solely via REST."""
    manifest = json.loads(
        stack.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "import json; from emulation.topology import manifest; print(json.dumps(manifest()))",
        )
    )
    profile = api.request("GET", "/api/v1/auth/me")
    org = api.request(
        "POST",
        "/api/v1/organizations",
        expected=201,
        body={"name": "Package verifier", "slug": stack.project},
    )
    workspace = api.request(
        "POST",
        f"/api/v1/organizations/{org['org_id']}/workspaces",
        expected=201,
        body={"name": "Package verification"},
    )
    network = api.request(
        "POST",
        "/api/v1/networks",
        expected=201,
        body={"workspace_id": workspace["workspace_id"], "name": "Package lab"},
    )
    binding = {
        "version": 1,
        "topology_id": manifest["topology_id"],
        "workspace_id": workspace["workspace_id"],
        "network_id": network["network_id"],
        "actor_user_id": profile["user_id"],
        "switches": {},
        "hosts": {},
        "port_capacities_mbps": manifest["port_capacities_mbps"],
    }
    for kind in ("switches", "hosts"):
        for node in manifest[kind]:
            device = api.request(
                "POST",
                f"/api/v1/networks/{network['network_id']}/devices",
                expected=201,
                body={
                    "hostname": node["name"],
                    "device_type": "switch" if kind == "switches" else "lab_endpoint",
                    "ip_address": node.get("ipv4"),
                    "spatial_ref_id": f"emulation/{manifest['topology_id']}/{node['name']}",
                },
            )
            binding[kind][node["dpid"] if kind == "switches" else node["name"]] = (
                device["device_id"]
            )
    # Canonical runtime schema coerces capacity integers to floats. The operator
    # digest must use those exact validated bytes, not the raw topology JSON types.
    return json.loads(
        stack.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "import sys; from app.modules.network.emulation import EmulationBinding; print(EmulationBinding.model_validate_json(sys.stdin.read()).model_dump_json())",
            stdin=json.dumps(binding).encode(),
        )
    )


def telemetry_snapshot(api, workspace, network, end):
    params = {
        "workspace_id": workspace,
        "network_id": network,
        "end_time": end,
        "page_size": 200,
    }
    records = []
    for page in range(1, 101):
        data = api.request(
            "GET", "/api/v1/telemetry/history", params={**params, "page": page}
        )
        records.extend(data["items"])
        if len(records) == data["total"]:
            return {
                "sha256": digest(sorted(records, key=lambda row: row["record_id"])),
                "count": len(records),
            }
        check(data["items"], "Telemetry pagination inconsistent")
    raise VerificationError("Telemetry verification bound exceeded")


def lab_traffic(stack, api, binding):
    row = stack.inspect_service("lab")
    check(
        row["HostConfig"]["NetworkMode"] == "none"
        and not row["NetworkSettings"]["Ports"],
        "Lab namespace/ports unsafe",
    )
    result = json.loads(
        stack.compose(
            "exec",
            "-T",
            "lab",
            "python",
            "-m",
            "emulation.runner",
            "--request",
            "traffic",
            timeout=90,
        )
    )
    check(result.get("passed") is True, "Real congestion traffic/readback failed")
    private_write(stack.registry.directory / "lab-baseline.json", result)
    delivered = result["iperf3"]["server"]["sum_received"]["bytes"]
    check(
        delivered > 1_000_000
        and result["peak_queue"]["backlog_bytes"] > 0
        and result["queue_samples"] > 0,
        "No measured congestion/delivery",
    )
    check(
        result["openflow_tx_bytes_delta"] >= delivered
        and result["ovs_cli_tx_bytes_delta"] >= delivered,
        "Measured forwarding counters disagree",
    )

    def measured():
        values = api.request(
            "GET",
            "/api/v1/telemetry/history",
            params={
                "workspace_id": binding["workspace_id"],
                "network_id": binding["network_id"],
                "page_size": 200,
            },
        )
        return any(
            row["tags"].get("run_id") == result["run_id"]
            and row["tags"].get("synthetic") is False
            and row["tags"].get("quality") == "measured"
            for row in values["items"]
        )

    try:
        until(measured, timeout=90)
    except VerificationError:
        values = api.request(
            "GET",
            "/api/v1/telemetry/history",
            params={
                "workspace_id": binding["workspace_id"],
                "network_id": binding["network_id"],
                "page_size": 10,
            },
        )
        private_write(stack.registry.directory / "telemetry-failure.json", values)
        raise VerificationError(
            "Measured telemetry ingestion deadline exceeded"
        ) from None

    def action(operation):
        time.sleep(3.2)  # Preserve the shipped manual-control hold-down.
        validated = api.request(
            "POST",
            "/api/v1/intents/validate",
            body={
                "workspace_id": binding["workspace_id"],
                "network_id": binding["network_id"],
                "intent": {
                    "action": "throttle_qos",
                    "scope": {"source_host": "h1", "destination_host": "h3"},
                    "constraints": {
                        "operation": operation,
                        "paths": [],
                        "dscp": None,
                        "rate_mbps": 5 if operation == "shape" else None,
                    },
                },
            },
        )
        check(validated["status"] == "validated", "Lab action validation rejected")
        accepted = api.request(
            "POST",
            "/api/v1/intents/execute",
            expected=202,
            body={
                "workspace_id": binding["workspace_id"],
                "intent_id": validated["intent_id"],
                "manual_approval": True,
                "idempotency_key": validated["intent_id"],
            },
        )
        check(
            accepted["status"] == "execution_started",
            "Lab execution did not enter durable worker queue",
        )
        private_write(
            stack.registry.directory / ("lab-" + operation + "-accepted.json"), accepted
        )
        try:
            done = until(
                lambda: api.request(
                    "GET",
                    "/api/v1/intents/" + validated["intent_id"],
                    params={"workspace_id": binding["workspace_id"]},
                ),
                lambda value: (
                    value["execution_provenance"].get("phase")
                    in {"completed", "failed", "rolled_back", "uncertain"}
                ),
            )
        except VerificationError:
            detail = api.request(
                "GET",
                "/api/v1/intents/" + validated["intent_id"],
                params={"workspace_id": binding["workspace_id"]},
            )
            private_write(
                stack.registry.directory / ("lab-" + operation + "-failure.json"),
                detail,
            )
            raise VerificationError(
                "Lab " + operation + " durable execution deadline exceeded"
            ) from None
        provenance = done["execution_provenance"]
        check(
            provenance["phase"] == "completed",
            "Lab execution did not reach verified completion",
        )
        proof = json.loads(
            stack.compose(
                "exec",
                "-T",
                "lab",
                "python",
                "-c",
                "import json,sys; from pathlib import Path; from emulation.actions import Actions; "
                "state=json.loads(Path('/results/.journal.json').read_text()); record=state['records'][sys.argv[1]]; "
                "actual=Actions(None).verify(record['prepared'],absent=record['command']['plan']['operation']=='restore'); "
                "print(json.dumps({'command':record['command'],'result':record['result'],'blocked':state['blocked'],'actual':actual}))",
                provenance["execution_id"],
            )
        )
        check(
            not proof["blocked"] and proof["result"]["status"] == "completed",
            "Independent lab journal/readback failed",
        )
        check(
            proof["command"]["plan_hash"] == provenance["plan_hash"]
            and proof["command"]["plan"]["operation"] == operation,
            "Lab readback belongs to different approved plan",
        )
        verification = proof["result"]["verification"]
        check(
            verification.get("readback_verified") is True
            and verification.get("config_readback_and_reachability") is True
            and verification.get("probe", {}).get("sent", 0) > 0
            and verification["probe"]["sent"] == verification["probe"]["received"],
            "Lab action lacks readback and reachability evidence",
        )
        return {
            "intent_id": validated["intent_id"],
            "execution_id": provenance["execution_id"],
            "plan_hash": provenance["plan_hash"],
        }

    shaped = action("shape")
    try:
        limited = json.loads(
            stack.compose(
                "exec",
                "-T",
                "lab",
                "python",
                "-m",
                "emulation.runner",
                "--request",
                "traffic",
                timeout=90,
            )
        )
        throughput = (
            limited["iperf3"]["server"]["sum_received"]["bits_per_second"] / 1_000_000
        )
        baseline = (
            result["iperf3"]["server"]["sum_received"]["bits_per_second"] / 1_000_000
        )
        check(
            limited.get("passed") is True
            and 1 < throughput < 6
            and throughput < baseline * 0.8,
            "Applied shaping did not change measured throughput",
        )
    finally:
        restored = action("restore")
    return {
        "run_id": result["run_id"],
        "delivered_bytes": delivered,
        "peak_backlog_bytes": result["peak_queue"]["backlog_bytes"],
        "api_measured_telemetry": True,
        "baseline_mbps": baseline,
        "shaped_mbps": throughput,
        "shape": shaped,
        "restore": restored,
        "autonomous_control": "not claimed; explicit approved manual control",
    }


def operator_tool(stack, action, archive, key_path):
    """Invoke the delivered operator tool, not its source functions or a mock."""
    tool = ROOT / "deploy" / "backup_restore.py"
    if not tool.is_file():
        raise Blocked("Operator backup tool not delivered")
    args = [
        sys.executable,
        str(tool),
        action,
        "--project",
        stack.project,
        "--env-file",
        "/dev/null",
        "--directory",
        str(archive),
        "--encryption-key-file",
        str(key_path),
    ]
    for path in stack.files:
        args += ["--compose-file", str(path)]
    try:
        # Only exact code-owned diagnostics may cross the subprocess boundary.
        # Driver output, arbitrary JSON reason strings and credentials stay hidden.
        return json.loads(
            run(
                args,
                env=stack.env,
                timeout=1800,
                private_diagnostic=archive.parent
                / ("operator-" + action + "-" + uuid.uuid4().hex + ".private.log"),
                safe_errors=(
                    "Operation failed safely; inspect local configuration.",
                    "Maintenance checkpoint refused: resolve physical execution/overrides with their owner services.",
                    "Docker operation failed; inspect scoped services locally (output suppressed for secrets).",
                    "Only project-owned networks are supported.",
                    "Only project-prefixed, non-external named volumes are supported.",
                    "Declared volume is missing; refusing incomplete backup before any service mutation.",
                    "Unrecognized/external volume; cannot prove complete backup.",
                    "Running deployment image differs from Compose image; exact restore cannot be guaranteed.",
                    "Actual external mount differs from Compose declaration.",
                    "Unbacked external bind mount. Move model/lab/report data to an owned named volume.",
                    "Anonymous or foreign mounted volume is not backed up.",
                    "Maintenance image lacks the required Neo4j graph checkpoint.",
                ),
            )
        )
    finally:
        stack.registry.register(stack.project)


def encrypted_backup(stack, archive, key_path):
    result = operator_tool(stack, "backup", archive, key_path)
    check(
        result.get("status") == "backed_up" and result.get("writers") == "stopped",
        "Operator did not complete coordinated backup",
    )
    check(
        not run(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + stack.project,
            ]
        ).strip(),
        "Source project still has running owners",
    )
    for service in (*serving_apis(stack), *WORKERS, *STORES, "gateway"):
        check(
            not stack.inspect_service(service)["State"]["Running"],
            "Source owner still running after backup",
        )
    raw = (archive / "manifest.json").read_bytes()
    signature = (archive / "manifest.hmac").read_text()
    check(
        hmac.compare_digest(
            signature, hmac.new(key_path.read_bytes(), raw, hashlib.sha256).hexdigest()
        ),
        "Backup manifest authentication mismatch",
    )
    manifest = json.loads(raw)
    check(
        manifest["project"] == stack.project and manifest.get("complete") is True,
        "Backup manifest scope/incomplete",
    )
    declared = {
        item["logical"]
        for item in manifest["volumes"]
        if item.get("kind", "volume") == "volume"
    }
    expected = {
        row["Labels"]["com.docker.compose.volume"]
        for row in json.loads(
            run(
                [
                    "docker",
                    "volume",
                    "inspect",
                    *[
                        name
                        for name, project in stack.registry.volumes.items()
                        if project == stack.project
                    ],
                ]
            )
        )
    }
    check(
        declared == expected and bool(declared),
        "Backup omits registered persistent volumes",
    )
    for item in [*manifest["volumes"], *manifest.get("binds", [])]:
        check(
            re.fullmatch(r"volume-[0-9]{4}\.tar\.gcm", item["file"]),
            "Unsafe backup payload path",
        )
        path = archive / item["file"]
        with path.open("rb") as stream:
            check(
                stream.read(len(b"NANFO-GCM-1\0")) == b"NANFO-GCM-1\0",
                "Backup payload is not encrypted GCM format",
            )
            stream.seek(0)
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        check(
            checksum == item["sha256"] and path.stat().st_mode & 0o077 == 0,
            "Encrypted payload integrity/permissions invalid",
        )
    verified = operator_tool(stack, "verify", archive, key_path)
    check(
        verified.get("status") == "authenticated",
        "Operator archive authentication failed",
    )
    return {
        "manifest_sha256": digest(raw),
        "encrypted_volumes": len(declared),
        "encrypted_bind_directories": len(manifest.get("binds", [])),
        "source_writers_stopped": True,
        "neo4j_graph": manifest["checkpoint"]["neo4j_graph"],
    }


def restore_stack(stack, source, archive, key_path):
    check(stack.project != source.project, "Restore target is source project")
    result = operator_tool(stack, "restore", archive, key_path)
    check(
        result.get("status") == "restored_verified"
        and result.get("writers") == "stopped",
        "Operator restore validation failed",
    )
    manifest = json.loads((archive / "manifest.json").read_bytes())
    graph = result.get("verification", {}).get("neo4j_graph")
    check(
        graph is not None and graph == manifest["checkpoint"]["neo4j_graph"],
        "Restored graph checkpoint differs from cold backup",
    )
    source_volumes = {
        name
        for name, project in stack.registry.volumes.items()
        if project == source.project
    }
    target_volumes = {
        name
        for name, project in stack.registry.volumes.items()
        if project == stack.project
    }
    check(
        bool(target_volumes) and source_volumes.isdisjoint(target_volumes),
        "Restore reused source volumes",
    )
    return {
        "source_project": source.project,
        "target_project": stack.project,
        "fresh_distinct_volumes": len(target_volumes),
        "neo4j_graph": graph,
    }


def create_spatial_assets(api, network):
    root = f"/api/v1/networks/{network}"
    registration = {
        "version": 1,
        "translation": {"x": 2.0, "y": 0.0, "z": 3.0},
        "rotation": {"x": 0.0, "y": 0.25, "z": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "target_units": "m",
        "target_up_axis": "y",
        "source": "deployment-acceptance",
    }
    body = b'{"asset":{"version":"2.0"},"scenes":[{"nodes":[]}],"scene":0}'
    result = api.request(
        "POST",
        root + "/campus/model-assets",
        body={
            "model_file_name": "acceptance.gltf",
            "model_mime_type": "model/gltf+json",
            "model_data_base64": base64.b64encode(body).decode(),
            "model_sha256": digest(body),
            "model_size_bytes": len(body),
            "registration": registration,
            "source": "deployment-acceptance",
        },
    )
    check(result["total"] == 1, "Asset upload count mismatch")
    asset = result["items"][0]
    check(
        asset["storage_backend"] == "local_cas"
        and asset["registration"] == registration,
        "Asset storage/registration receipt mismatch",
    )
    scene = {
        "version": 1,
        "coordinate_system": {"units": "m", "up_axis": "y"},
        "objects": [
            {
                "object_id": "acceptance-campus",
                "parent_id": None,
                "object_type": "campus",
                "name": "Deployment fixture",
                "position": {"x": 1.0, "y": 0.0, "z": 2.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "device_id": None,
                "provenance": {"source": "deployment-fixture", "accuracy_m": None},
            }
        ],
    }
    initial = api.request("GET", root + "/spatial-scene")
    first = api.request(
        "PUT",
        root + "/spatial-scene",
        body={"expected_revision": initial["revision"], "scene": scene},
    )
    scene["objects"][0]["position"]["x"] = 4.0
    second = api.request(
        "PUT",
        root + "/spatial-scene",
        body={"expected_revision": first["revision"], "scene": scene},
    )
    history = api.request("GET", root + "/spatial-scene/history")
    check(history["total"] >= 2, "Spatial history missing revisions")
    expected = {
        "asset": asset,
        "body_sha256": digest(body),
        "body_bytes": len(body),
        "scene": second,
        "history": history,
        "revision": first,
    }
    verify_spatial_assets(api, network, expected)
    return expected


def verify_spatial_assets(api, network, expected):
    root = f"/api/v1/networks/{network}"
    listing = api.request("GET", root + "/campus/model-assets")
    check(
        listing["total"] == 1 and listing["items"][0] == expected["asset"],
        "Asset identity/registration receipt changed",
    )
    asset = listing["items"][0]
    status, headers, body = api.raw("GET", asset["download_path"])
    check(
        status == 200
        and len(body) == expected["body_bytes"]
        and digest(body) == expected["body_sha256"],
        "Downloaded asset bytes changed",
    )
    check(
        base64.b64decode(asset["model_data_base64"], validate=True) == body,
        "Asset compatibility bytes differ from download",
    )
    check(
        headers.get("ETag") == '"sha256:' + digest(body) + '"'
        and "no-store" in headers.get("Cache-Control", ""),
        "Asset integrity/cache headers invalid",
    )
    check(
        api.request("GET", root + "/spatial-scene") == expected["scene"],
        "Current spatial scene changed",
    )
    check(
        api.request("GET", root + "/spatial-scene/history") == expected["history"],
        "Spatial history receipts changed",
    )
    check(
        api.request(
            "GET",
            root + "/spatial-scene/history/" + str(expected["revision"]["revision"]),
        )
        == expected["revision"],
        "Historical spatial body changed",
    )
    return {
        "asset_id": asset["campus_model_asset_id"],
        "sha256": digest(body),
        "bytes": len(body),
        "registration_sha256": digest(asset["registration"]),
        "history_revisions": expected["history"]["total"],
    }


def installed_schema(stack):
    value = (
        stack.compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "nanfo",
            "-Atc",
            "SELECT version_num FROM alembic_version",
        )
        .decode()
        .strip()
    )
    check(value == "0027", "Installed schema is not exactly migration 0027")
    return value


def image_inventory(stack):
    result = {}
    for name, spec in stack.config["services"].items():
        check(bool(spec.get("image")), "Package service lacks explicit image tag")
        row = json.loads(run(["docker", "image", "inspect", spec["image"]]))[0]
        check(re.fullmatch(r"sha256:[0-9a-f]{64}", row["Id"]), "Invalid image identity")
        result[name] = {
            "id": row["Id"],
            "os": row["Os"],
            "architecture": row["Architecture"],
        }
    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Authorize creation of new UUID-scoped Docker resources",
    )
    parser.add_argument(
        "--agents-idle",
        action="store_true",
        help="Attest packaging/backup/model/lab agents have finished; not a process detector",
    )
    parser.add_argument(
        "--lab",
        action="store_true",
        help="Require optional disconnected package lab; necessary for Step15 completion",
    )
    parser.add_argument(
        "--model",
        action="store_true",
        help="Request optional frozen model runtime diagnosis; never substitutes host inference",
    )
    parser.add_argument("--work-root", type=Path, default=Path("/tmp/opencode"))
    parser.add_argument("--distributed", action="store_true", help="Two distributed APIs and gateway failover gate")
    parser.add_argument(
        "--reuse-build-record",
        type=Path,
        help="Reference prior locked-build evidence; never build or pull",
    )
    parser.add_argument("--backend-image")
    parser.add_argument("--frontend-image")
    parser.add_argument("--neo4j-image")
    parser.add_argument(
        "--ai-image",
        help="Exact existing with-ai image ID; reuse never builds implicitly",
    )
    parser.add_argument(
        "--lab-image",
        help="Exact existing local operator image ID; never build or retag",
    )
    args = parser.parse_args(argv)
    if args.distributed and args.model:
        parser.error("Historical diagnostic campaign is singleton; use explicit live-AI overlays for distributed provider acceptance")
    if not args.live or not args.agents_idle:
        parser.error(
            "Live execution requires BOTH --live and --agents-idle; parent authorization required"
        )
    images = (args.backend_image, args.frontend_image, args.neo4j_image)
    if args.reuse_build_record:
        if not all(
            value and re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in images
        ):
            parser.error(
                "Reuse requires exact --backend-image, --frontend-image and --neo4j-image IDs"
            )
        if args.model and not args.ai_image:
            parser.error("Reuse with --model requires --ai-image; no implicit AI build")
        if args.lab and not args.lab_image:
            parser.error("Reuse with --lab requires --lab-image; no implicit lab build")
    elif any(images):
        parser.error("Image overrides require --reuse-build-record")
    if args.lab_image and not re.fullmatch(r"sha256:[0-9a-f]{64}", args.lab_image):
        parser.error("--lab-image must be an exact local sha256 image ID")
    if args.ai_image and (
        not args.model
        or not args.reuse_build_record
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", args.ai_image)
    ):
        parser.error(
            "--ai-image requires --model, --reuse-build-record and an exact local sha256 image ID"
        )
    return args


def disk_capacity(work_root):
    docker_root = Path(
        run(["docker", "info", "--format", "{{.DockerRootDir}}"]).decode().strip()
    )
    check(docker_root.is_absolute(), "Docker storage path unavailable")
    capacity_path = docker_root
    try:
        available = shutil.disk_usage(capacity_path).free
    except PermissionError:
        # Use the kernel's exact containing mount, not an arbitrary accessible
        # ancestor that could live on a different filesystem.
        mounts = [
            Path(line.split()[4].replace("\\040", " "))
            for line in Path("/proc/self/mountinfo").read_text().splitlines()
        ]
        capacity_path = max(
            (mount for mount in mounts if docker_root.is_relative_to(mount)),
            key=lambda path: len(path.parts),
        )
        available = shutil.disk_usage(capacity_path).free
    staging = shutil.disk_usage(work_root).free
    minimum = 1024**3
    if available < minimum or staging < minimum:
        raise Blocked(
            f"Insufficient disk: Docker available={available} bytes, staging available={staging} bytes; "
            f"each requires at least {minimum} bytes before fresh source/restore volumes. "
            "Free or expand Docker storage without pruning unrelated resources; tmpfs driver volumes are not supported by the cold-backup contract."
        )
    return {
        "docker_root": str(docker_root),
        "capacity_filesystem": str(capacity_path),
        "docker_available_bytes": available,
        "staging_available_bytes": staging,
        "minimum_bytes": minimum,
    }


def referenced_build(args, registry):
    raw = args.reuse_build_record.read_bytes()
    check(len(raw) <= 1024 * 1024, "Build evidence exceeds bound")
    text = raw.decode()
    if args.reuse_build_record.suffix == ".json":
        record = json.loads(raw)
        check(
            record.get("image_id") == args.backend_image
            and record.get("host_site_packages_used") is False
            and "poetry check --lock" in record.get("dependency_install", "")
            and "poetry install --only main" in record.get("dependency_install", ""),
            "Structured locked-build record invalid",
        )
        companion = (ROOT / "deploy/README.md").read_text()
        check(
            "npm ci" in companion
            and args.frontend_image in companion
            and args.neo4j_image in companion,
            "Companion frontend/Neo4j build record missing",
        )
        text += companion
    else:
        check(
            "Poetry" in text and "npm ci" in text and "real Docker builds" in text,
            "Prior locked-build evidence missing",
        )
    available_ids = set(
        run(["docker", "image", "ls", "-q", "--no-trunc"]).decode().split()
    )
    required = {
        "backend": args.backend_image,
        "frontend": args.frontend_image,
        "neo4j": args.neo4j_image,
    }
    if args.lab:
        required["lab"] = args.lab_image
    missing = {
        name: identity
        for name, identity in required.items()
        if identity not in available_ids
    }
    if missing:
        raise Blocked(
            "Required exact local images unavailable: "
            + json.dumps(missing, sort_keys=True)
            + ". Load the original exported images into this Docker daemon; no replacement build or pull performed."
        )
    images = {}
    for name, identity in (
        ("backend", args.backend_image),
        ("frontend", args.frontend_image),
        ("neo4j", args.neo4j_image),
    ):
        check(identity in text, "Exact image missing from prior build evidence")
        image = json.loads(run(["docker", "image", "inspect", identity]))[0]
        check(image["Id"] == identity, "Prior image identity mismatch")
        images[name] = {
            "id": identity,
            "os": image["Os"],
            "architecture": image["Architecture"],
        }
    if args.lab:
        image = json.loads(run(["docker", "image", "inspect", args.lab_image]))[0]
        check(image["Id"] == args.lab_image, "Operator lab image unavailable")
        images["lab"] = {"id": image["Id"]}
    if args.ai_image:
        check(
            args.ai_image in text and "uv sync --locked" in text,
            "AI image lacks verified locked-build evidence",
        )
        if args.ai_image in available_ids:
            image = json.loads(run(["docker", "image", "inspect", args.ai_image]))[0]
            images["ai"] = {
                "id": image["Id"],
                "os": image["Os"],
                "architecture": image["Architecture"],
            }
        else:
            images["ai"] = {
                "status": "blocked",
                "reason": "Exact optional AI image is not present",
            }
    paths = (
        "deploy/maintenance.py",
        "deploy/asset_checkpoint.py",
        "backend/app/api/readiness.py",
        "backend/app/core/runtime_health.py",
        "backend/app/core/config.py",
        "backend/app/modules/network/operations.py",
        "backend/app/modules/report/artifacts.py",
        "backend/app/modules/report/service.py",
        "backend/app/modules/report/worker.py",
    )
    project = "nanfo-deploy-verify-" + uuid.uuid4().hex
    registry.fresh(project)
    try:
        hashes = json.loads(
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull=never",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--label",
                    "com.docker.compose.project=" + project,
                    "--label",
                    "com.docker.compose.service=image-inspection",
                    "--entrypoint",
                    "python",
                    args.backend_image,
                    "-c",
                    "import hashlib,json,sys; from pathlib import Path; print(json.dumps({p:hashlib.sha256((Path('/opt/nanfo')/p).read_bytes()).hexdigest() for p in sys.argv[1:]}))",
                    *paths,
                ]
            )
        )
    finally:
        registry.register(project)
    return {
        "mode": "referenced_prior_locked_build_not_new_build",
        "evidence_path": str(args.reuse_build_record.resolve()),
        "evidence_sha256": digest(raw),
        "images": images,
        "installed_source_sha256": hashes,
        "source_mismatches": [
            path for path in paths if hashes[path] != digest((ROOT / path).read_bytes())
        ],
        "builds_performed": 0,
        "pulls_performed": 0,
    }


def source_fingerprint():
    paths = []
    for directory in ("deploy", "backend", "frontend", "emulation"):
        output = (
            run(
                [
                    "git",
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "--",
                    directory,
                ]
            )
            .decode()
            .splitlines()
        )
        paths.extend(path for path in output if runtime_source(path))
    result = {}
    for name in sorted(set(paths)):
        path = ROOT / name
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                result[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return digest(result)


def runtime_source(path):
    parts = Path(path).parts
    if any(
        part in {"__pycache__", "tests", "artifacts", "node_modules", "dist"}
        for part in parts
    ) or path.startswith("deploy/state/") or path.endswith((".pyc", ".md")):
        return False
    if parts[0] == "deploy":
        return Path(path).name in {
            "compose.yaml",
            "compose.ai.yaml",
            "compose.lab.yaml",
            "compose.distributed.yaml",
            "compose.fleet.yaml",
            "compose.distributed-fleet.yaml",
            "compose.live-ai.yaml",
            "compose.distributed-live-ai.yaml",
            "fleet.sources",
            "Dockerfile.backend",
            "Dockerfile.frontend",
            "Dockerfile.neo4j",
            "entrypoint.py",
            "initialize.py",
            "volume_init.py",
            "maintenance.py",
            "asset_checkpoint.py",
            "adr023_checkpoint.py",
            "archive_acceptance.py",
            "check_fleet_health.py",
            "telemetry_retention.py",
            "backup_restore.py",
            "nginx.conf",
            "nginx-upstream.conf",
            "nginx-distributed-upstream.conf",
            "redis-entrypoint.sh",
            "neo4j-entrypoint.sh",
        }
    return not Path(path).name.startswith("test_")


def fresh_volumes(stack):
    """No image-declared files or old named volume may masquerade as empty state."""
    image = stack.config["services"]["api"]["image"]
    created = []
    for logical, spec in stack.config["volumes"].items():
        name = spec["name"]
        check(
            not run(
                ["docker", "volume", "ls", "-q", "--filter", "name=^" + name + "$"]
            ).strip(),
            "Fresh volume name already exists",
        )
        try:
            run(
                [
                    "docker",
                    "volume",
                    "create",
                    "--label",
                    "com.docker.compose.project=" + stack.project,
                    "--label",
                    "com.docker.compose.volume=" + logical,
                    name,
                ]
            )
        finally:
            stack.registry.register(stack.project)
        try:
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--user",
                    "0:0",
                    "--label",
                    "com.docker.compose.project=" + stack.project,
                    "--label",
                    "com.docker.compose.service=verify-empty",
                    "--mount",
                    "type=volume,source="
                    + name
                    + ",target=/fresh,readonly,volume-nocopy",
                    "--entrypoint",
                    "python",
                    image,
                    "-c",
                    "import os,sys; sys.exit(bool(os.listdir('/fresh')))",
                ]
            )
        finally:
            stack.registry.register(stack.project)
        created.append(name)
    return {"empty_new_volumes": created, "existing_data": 0}


def protect_operator_directory(stack, path):
    """Only the newly generated copy is chowned; never touch original artifacts."""
    root = Path(stack.env["NANFO_STATE_DIR"])
    check(
        path.resolve().is_relative_to(root.resolve())
        and path != root
        and not path.is_symlink(),
        "Unowned operator path refused",
    )
    try:
        run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--user",
                "0:0",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "CHOWN",
                "--cap-add",
                "FOWNER",
                "--cap-add",
                "DAC_OVERRIDE",
                "--label",
                "com.docker.compose.project=" + stack.project,
                "--label",
                "com.docker.compose.service=verify-permissions",
                "--mount",
                "type=bind,source=" + str(path) + ",target=/operator",
                "--entrypoint",
                "python",
                stack.config["services"]["api"]["image"],
                "-c",
                (
                    "import os; from pathlib import Path; root=Path('/operator'); "
                    "paths=[root,*root.rglob('*')]; assert not any(p.is_symlink() for p in paths); "
                    "[(os.chown(p,0,0),os.chmod(p,0o755 if p.is_dir() else 0o444)) for p in paths]"
                ),
            ]
        )
    finally:
        stack.registry.register(stack.project)


def activate_lab(source, target, api, binding, directory):
    overlay = ROOT / "deploy" / "compose.lab.yaml"
    if not overlay.is_file():
        raise Blocked("Package lab overlay unavailable")
    private_write(directory / "binding" / "binding.json", binding)
    protect_operator_directory(source, directory / "binding")
    installed = source.compose(
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        "import os; from pathlib import Path; print(Path(os.environ['EMULATION_BINDING_PATH']).read_text())",
    )
    check(
        json.loads(installed) == binding,
        "Mounted operator binding differs from authenticated API inventory",
    )
    image = source.env.get("NANFO_LAB_IMAGE")
    if not image:
        image = source.project + ":lab"
        run(
            ["docker", "build", "--pull", "-t", image, str(ROOT / "emulation")],
            timeout=1800,
        )
    image_id = json.loads(run(["docker", "image", "inspect", image]))[0]["Id"]
    for stack in (source, target):
        stack.files = [*stack.files, overlay]
        stack.env.update(
            NANFO_LAB_IMAGE=image_id,
            EMULATION_BINDING_DIGEST=digest(binding),
            EMULATION_CONTROL_ENABLED="true" if stack is source else "false",
        )
        stack.config = json.loads(stack.compose("config", "--format", "json"))
        validate_compose(stack.config, stack.project, directory)
    try:
        source.compose("--profile", "lab", "up", "-d", "--no-deps", "lab", timeout=180)
    finally:
        source.registry.register(source.project)
    try:
        until(lambda: source.healthy(("lab",)), timeout=180)
    except VerificationError:
        row = source.inspect_service("lab")
        private_write(
            directory / "evidence" / "lab-start-failure.json",
            {"state": row["State"], "image": row["Image"]},
        )
        private_write(directory / "lab-failure.log", run(["docker", "logs", row["Id"]]))
        raise VerificationError(
            "Lab startup health deadline exceeded; private diagnostic retained"
        ) from None
    source.compose("stop", "--timeout", "15", "api", *WORKERS)
    source.env.update(
        EXECUTION_MODE="emulation", TELEMETRY_RUNTIME_ADAPTER_MODE="emulation"
    )
    source.config = json.loads(source.compose("config", "--format", "json"))
    source.compose("up", "-d", "--no-deps", "api", *WORKERS, timeout=180)
    source.compose("restart", "gateway")
    api.origin = source.gateway().origin
    try:
        until(api.ready)
        until(lambda: source.healthy(WORKERS))
    except VerificationError:
        status, _, content = api.raw("GET", "/ready")
        private_write(
            directory / "evidence" / "lab-api-ready-failure.json",
            {
                "status": status,
                "body": json.loads(content) if content else None,
                "services": {
                    name: source.inspect_service(name)["State"]
                    for name in ("api", *WORKERS)
                },
            },
        )
        raise VerificationError(
            "Emulation API/workers readiness failed; diagnostic retained"
        ) from None
    return {
        "binding_sha256": digest(binding),
        "installed_runtime_path": "/var/lib/nanfo/binding/binding.json",
        "isolated_lab_image": image_id,
        "lab_control": "explicit manual control; autonomy not enabled",
    }


def prepare_model(state, network):
    ai = ROOT / "ai-engine"
    checkpoint = ai / "artifacts/adr014-001/train-06/checkpoint.ptz"
    if not checkpoint.is_file():
        raise Blocked("Frozen ADR014 checkpoint unavailable")
    check(
        digest(checkpoint.read_bytes())
        == "5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5",
        "Frozen checkpoint pin mismatch",
    )
    with zipfile.ZipFile(checkpoint) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    models, registry_root = state / "models", state / "model-registry"
    models.mkdir(mode=0o755)
    registry_root.mkdir(mode=0o755)
    originals = {}
    total = 0

    def copy(relative):
        nonlocal total
        path = ai / relative
        check(
            path.resolve().is_relative_to(ai.resolve())
            and not path.is_symlink()
            and path.is_file(),
            "Frozen artifact path invalid",
        )
        data = path.read_bytes()
        total += len(data)
        check(
            total <= 32 * 1024 * 1024,
            "Frozen artifact copy exceeds 32 MiB bound; no large model archives",
        )
        target = models / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        private_write(target, data)
        originals[relative] = digest(data)
        return {"path": relative, "sha256": digest(data), "size_bytes": len(data)}

    checkpoint_ref = copy("artifacts/adr014-001/train-06/checkpoint.ptz")
    history = copy("artifacts/adr014-001/validation-06/last-history.json")
    check(
        history["sha256"]
        == "1ed5856374244fc1a547b05043f5c7f05d5a2da89a285fd27ec09186ba3123b7",
        "Frozen history pin mismatch",
    )
    benchmark = copy("artifacts/adr014-holdout-001/test-report.json")
    for relative, expected in manifest["client_source_files"].items():
        artifact = copy("artifacts/adr014-001/source/" + relative)
        check(
            artifact["sha256"] == expected,
            "Frozen source changed from checkpoint manifest",
        )
    registry = {
        "version": 1,
        "models": [
            {
                "model_id": "adr014-incumbent",
                "checkpoint_id": "train-06",
                "network_ids": [network],
                "checkpoint": checkpoint_ref,
                "source_directory": "artifacts/adr014-001/source",
                "source_sha256": manifest["client_source_files"],
                "histories": {
                    "validation-06": {"artifact": history, "network_ids": [network]}
                },
                "benchmark": {
                    "status": "qualified_scoped_benchmark",
                    "scope": "ADR014 reserved 12 seeds, stationary 2/20 Mbps impairment versus frozen nominal-cost OSPF",
                    "limitations": [
                        "Historical measured inference only; no live observer or execution authorization",
                        "Not capacity-aware OSPF or arbitrary-network superiority",
                    ],
                    "evidence": benchmark,
                },
            }
        ],
    }
    raw = json.dumps(registry, sort_keys=True, separators=(",", ":")).encode()
    private_write(registry_root / "registry.json", raw)
    return {
        "registry_sha256": digest(raw),
        "policy_sha256": checkpoint_ref["sha256"],
        "copied_bytes": total,
        "originals": originals,
    }


def diagnose_model(source, target, api, network, directory, login):
    overlay = ROOT / "deploy" / "compose.ai.yaml"
    if not overlay.is_file():
        raise Blocked("Optional independent AI image overlay unavailable")
    ai_image = source.env.get("NANFO_AI_IMAGE")
    if ai_image:
        available = run(["docker", "image", "ls", "-q", "--no-trunc"]).decode().split()
        if ai_image not in available:
            raise Blocked(
                "Exact optional AI image unavailable; core verification continues without a build"
            )
    prepared = prepare_model(directory, network)
    for name in ("models", "model-registry"):
        protect_operator_directory(source, directory / name)
        (Path(target.env["NANFO_STATE_DIR"]) / name).mkdir(mode=0o755)
    for stack in (source, target):
        stack.files = [*stack.files, overlay]
        stack.env.update(
            NANFO_AI_IMAGE=ai_image or source.project + ":with-ai",
            NANFO_MODEL_REGISTRY_SHA256=prepared["registry_sha256"],
        )
        stack.config = json.loads(stack.compose("config", "--format", "json"))
        validate_compose(stack.config, stack.project, directory)
    if not ai_image:
        source.compose("build", "--pull", "api", timeout=3600)
    source.compose("stop", "--timeout", "15", "api")
    source.compose(
        "up", "-d", "--no-build", "--pull", "never", "--no-deps", "api", timeout=180
    )
    source.compose("restart", "gateway")
    api.origin = source.gateway().origin
    until(api.ready)
    paths = (
        "deploy/maintenance.py",
        "backend/app/core/config.py",
        "backend/app/modules/network/operations.py",
        "backend/scripts/frozen_model_diagnostic.py",
    )
    hashes = json.loads(
        source.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "import hashlib,json,sys; from pathlib import Path; print(json.dumps({p:hashlib.sha256((Path('/opt/nanfo')/p).read_bytes()).hexdigest() for p in sys.argv[1:]}))",
            *paths,
        )
    )
    check(
        all(hashes[path] == digest((ROOT / path).read_bytes()) for path in paths),
        "With-AI installed runtime source parity failed",
    )
    login()  # A large locked AI image build may outlive the previous access token.
    runtime = json.loads(
        source.compose(
            "exec",
            "-T",
            "api",
            "/opt/nanfo/ai-runtime/bin/python",
            "-I",
            "-c",
            "import importlib.util,json,sys,torch; print(json.dumps({'prefix':sys.prefix,'torch':torch.__version__,'backend_present':importlib.util.find_spec('app') is not None}))",
        )
    )
    check(
        runtime["prefix"] == "/opt/nanfo/ai-runtime"
        and runtime["backend_present"] is False,
        "AI inference environment is not independent",
    )
    row = source.inspect_service("api")
    for destination in ("/var/lib/nanfo/models", "/var/lib/nanfo/model-registry"):
        mount = next(
            mount for mount in row["Mounts"] if mount["Destination"] == destination
        )
        check(
            mount["Type"] == "bind" and mount["RW"] is False,
            "Model artifact/registry mount is not read-only",
        )
    status, _, raw = api.raw(
        "POST",
        "/api/v1/autonomy/model/diagnose",
        body={"network_id": network, "history_reference": "validation-06"},
        timeout=40,
    )
    if status == 503:
        raise Blocked(
            "Actual container frozen inference unavailable (e.g. confinement/runtime capability); no host substitute"
        )
    check(status == 201, "Frozen diagnostic HTTP contract failed")
    envelope = json.loads(raw)
    check(envelope.get("success") is True, "Diagnostic canonical envelope invalid")
    result = envelope["data"]["result"]
    check(
        result["registry_sha256"] == prepared["registry_sha256"]
        and result["policy_sha256"] == prepared["policy_sha256"],
        "Diagnostic artifact provenance mismatch",
    )
    check(
        result["live"] is False
        and result["safety_authorized"] is False
        and result["execution"] == "not_applied"
        and result["evidence"],
        "Diagnostic overclaims live safety or lacks evidence",
    )
    for relative, expected in prepared["originals"].items():
        check(
            digest((ROOT / "ai-engine" / relative).read_bytes()) == expected,
            "Original frozen artifact was modified",
        )
    return {
        "diagnostic_id": envelope["data"]["diagnostic_id"],
        "registry_sha256": prepared["registry_sha256"],
        "policy_sha256": prepared["policy_sha256"],
        "copied_artifact_bytes": prepared["copied_bytes"],
        "runtime": runtime,
        "historical_only": True,
        "originals_unchanged": True,
    }


def package_contract():
    files = [
        ROOT / "deploy" / name
        for name in (
            "compose.yaml",
            "Dockerfile.backend",
            "Dockerfile.frontend",
            "initialize.py",
            "volume_init.py",
            "backup_restore.py",
        )
    ]
    missing = [path.name for path in files if not path.is_file()]
    if not (ROOT / "deploy/maintenance.py").is_file():
        missing.append("installed deploy.maintenance")
    if missing:
        raise Blocked("Package files pending: " + ", ".join(missing))
    backend = (ROOT / "deploy" / "Dockerfile.backend").read_text()
    frontend = (ROOT / "deploy" / "Dockerfile.frontend").read_text()
    check(
        "poetry check --lock" in backend
        and "poetry install --only main" in backend
        and "npm ci" in frontend,
        "Locked dependency installation stages missing",
    )
    for text in (backend, frontend):
        bases = re.findall(r"^FROM\s+(\S+)", text, re.MULTILINE)
        aliases = set(
            re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", text, re.MULTILINE | re.IGNORECASE)
        )
        check(
            all(
                base in aliases or re.search(r"@sha256:[0-9a-f]{64}$", base)
                for base in bases
            ),
            "Unpinned package base image",
        )
    return {"locked_stages_present": True, "live_build": "pending"}


def initialize_secrets(directory):
    directory.mkdir(mode=0o700)
    for name in (
        "postgres_admin_password",
        "postgres_owner_password",
        "postgres_runtime_password",
        "redis_password",
        "neo4j_password",
        "jwt_secret",
        "bootstrap_password",
    ):
        private_write(directory / name, secrets.token_urlsafe(48).encode())
    return (directory / "bootstrap_password").read_text()


def serving_apis(stack):
    return ("api", "api2") if isinstance(stack.config, dict) and "api2" in stack.config["services"] else ("api",)


def distributed_failover(stack):
    if len(serving_apis(stack)) != 2:
        raise Blocked("Optional distributed composition not requested")

    def readiness(name):
        return json.loads(stack.compose(
            "exec", "-T", name, "python", "-c",
            "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=4).read().decode())",
        ))["data"]

    def promoted(name):
        try:
            return readiness(name)["realtime"]["role"] == "leader"
        except VerificationError:
            return False

    until(lambda: stack.healthy(serving_apis(stack)))
    rows = {name: readiness(name) for name in serving_apis(stack)}
    check(sorted(row["realtime"]["role"] for row in rows.values()) == ["follower", "leader"], "Distributed leadership differs")
    leader = next(name for name, row in rows.items() if row["realtime"]["role"] == "leader")
    follower = next(name for name in rows if name != leader)
    check(rows[follower]["checks"]["api_consumers"] == "delegated"
          and rows[follower]["realtime"]["local_consumer_count"] == 0
          and rows[follower]["realtime"]["local_collector"] is False, "Follower owns legacy work")
    try:
        stack.compose("stop", "--timeout", "45", leader)
        until(lambda: promoted(follower), timeout=120)
        until(stack.gateway().ready)
    finally:
        stack.compose("start", leader)
    until(lambda: stack.healthy(serving_apis(stack)))
    until(lambda: sorted(readiness(name)["realtime"]["role"] for name in serving_apis(stack)) == ["follower", "leader"])
    return {"apis": 2, "leader_failover": True, "follower_work": "delegated", "sockets": "separate multiprocess acceptance required"}


def start_application(stack):
    # Explicit services prevent accidental reruns of fresh-only initialization or lab.
    stack.compose(
        "up", "-d", "--no-build", "--no-deps", *serving_apis(stack), *WORKERS, "gateway", timeout=180
    )
    api = stack.gateway()
    until(api.ready)
    until(lambda: stack.healthy(WORKERS))
    return api


def archive_fixture(stack, action, value):
    return json.loads(stack.compose(
        "run", "--rm", "--no-deps", "-T", "-e", "NANFO_DEPLOY_ACCEPTANCE=isolated-archive-v1",
        "telemetry-retention", "python", "/opt/nanfo/deploy/archive_acceptance.py", action,
        stdin=json.dumps(value).encode(), timeout=120,
    ))


def retention_cli(stack, operation, workspace, *args):
    return json.loads(stack.compose(
        "run", "--rm", "--no-deps", "-T", "telemetry-retention", "python",
        "/opt/nanfo/deploy/telemetry_retention.py", operation, "--workspace-id", workspace,
        "--max-batches", "10", "--batch-size", "100", "--timeout-seconds", "30", *args,
        timeout=120,
    ))


def nonempty_archive(stack, binding):
    value = {"workspace_id": binding["workspace_id"], "network_id": binding["network_id"],
             "device_id": next(iter(binding["hosts"].values()))}
    start = datetime.now(timezone.utc).isoformat()
    records = archive_fixture(stack, "historical", value)
    for owner in ("report", "intent", "alert", "simulation", "autonomy"):
        result = retention_cli(stack, "reconcile", value["workspace_id"], "--owner", owner)
        check(result[-1]["complete"] is True, "Owner reference reconciliation incomplete")
    records.update(archive_fixture(stack, "prospective", value))
    window = ("--start-time", start, "--end-time", datetime.now(timezone.utc).isoformat())
    dry_run = retention_cli(stack, "dry-run", value["workspace_id"], *window)
    candidates = [record for batch in dry_run for record in batch["prospective_candidates"]]
    check(candidates == [records["archive"]["record_id"]], "Archive eligibility includes history or pins")
    applied = retention_cli(stack, "apply", value["workspace_id"], *window)
    check(sum(batch["deleted"] for batch in applied) == 1, "Nonempty archive deletion missing")
    value["records"] = records
    proof = archive_fixture(stack, "verify", value)
    check(proof["archive_bytes"] > 0 and proof["row_restored"] is False, "Archive bytes/delete proof missing")
    return {"fixture": value, "proof": proof}


def restored_archive(stack, expected):
    value = expected["fixture"]
    check(archive_fixture(stack, "verify", value) == expected["proof"], "Restored archive/pin/tombstone proof differs")
    restored = retention_cli(stack, "restore", value["workspace_id"], "--record-id", value["records"]["archive"]["record_id"])
    check(restored["restored"] is True, "Scoped archive restore did not recreate record")
    return archive_fixture(stack, "verify", {**value, "restored": True})


def verify_live(args, directory, matrix, registry):
    if matrix.case("package_contract", package_contract) is None:
        return
    parity = True
    capacity = matrix.case("disk_capacity", lambda: disk_capacity(args.work_root))
    if capacity is None:
        return

    def capacity_guard():
        try:
            disk_capacity(args.work_root)
        except Blocked:
            registry.preserve = True
            raise

    matrix.guard = capacity_guard
    if args.reuse_build_record:
        prior = matrix.case(
            "locked_container_build", lambda: referenced_build(args, registry)
        )
        if prior is None:
            matrix.block(
                "model_diagnostic",
                "Optional model runtime not requested; core pinned images unavailable",
            )
            return

        def installed_parity():
            if prior["source_mismatches"]:
                raise Blocked(
                    "Pinned image/source mismatch: "
                    + ", ".join(prior["source_mismatches"])
                    + "; update the small runtime image after capacity is available, without rebuilding locked dependencies"
                )
            return "Installed maintenance/readiness bytes match current source"

        parity = matrix.case("installed_source_parity", installed_parity) is not None
        if not args.model:
            matrix.block("model_diagnostic", "Optional model diagnosis not requested")
    if not parity:
        return
    source_hash = source_fingerprint()
    time.sleep(20)
    check(
        source_fingerprint() == source_hash,
        "Source quiet gate failed; contributing agents are still editing",
    )
    secret_dir = directory / "secrets"
    password = initialize_secrets(secret_dir)
    key_dir = directory / "keys"
    key_dir.mkdir(mode=0o700)
    key_path = key_dir / "backup.key"
    private_write(key_path, secrets.token_bytes(32))
    archive = directory / "backup"
    archive.mkdir(mode=0o700)
    projects = ["nanfo-deploy-verify-" + uuid.uuid4().hex for _ in range(2)]
    for project in projects:
        registry.fresh(project)
    binding_dir = directory / "binding"
    binding_dir.mkdir(mode=0o755)
    env = {
        "NANFO_STATE_DIR": str(directory),
        "NANFO_BOOTSTRAP_EMAIL": "verify-" + uuid.uuid4().hex + "@example.com",
        "NANFO_HTTP_PORT": "0",
        "EXECUTION_MODE": "production",
        "NANFO_BACKEND_IMAGE": projects[0] + ":backend",
        "NANFO_FRONTEND_IMAGE": projects[0] + ":frontend",
        "NANFO_NEO4J_IMAGE": projects[0] + ":neo4j",
    }
    if args.reuse_build_record:
        env.update(
            NANFO_BACKEND_IMAGE=args.backend_image,
            NANFO_FRONTEND_IMAGE=args.frontend_image,
            NANFO_NEO4J_IMAGE=args.neo4j_image,
        )
    if args.lab_image:
        env["NANFO_LAB_IMAGE"] = args.lab_image
    if args.ai_image:
        env["NANFO_AI_IMAGE"] = args.ai_image
    files = [ROOT / "deploy" / "compose.yaml"]
    if args.distributed:
        files.append(ROOT / "deploy/compose.distributed.yaml")
    stacks = [Stack(project, files, env.copy(), registry) for project in projects]
    source, target = stacks
    restore_dir = directory / "restore"
    restore_dir.mkdir(mode=0o700)
    (restore_dir / "secrets").mkdir(mode=0o700)
    (restore_dir / "binding").mkdir(mode=0o755)
    for path in secret_dir.iterdir():
        private_write(restore_dir / "secrets" / path.name, path.read_bytes())
    target.env["NANFO_STATE_DIR"] = str(restore_dir)
    for stack in stacks:
        stack.env["NANFO_PROJECT"] = stack.project
        stack.config = json.loads(stack.compose("config", "--format", "json"))
        validate_compose(stack.config, stack.project, directory)

    def build():
        # Explicit serial builds support installations without the buildx plugin.
        # Cache remains enabled; fixed digest bases and locked installs are retained.
        for kind, service, target in (("backend", "api", "runtime"), ("frontend", "gateway", None), ("neo4j", "neo4j", None)):
            output = run([
                "docker", "build", "-f", str(ROOT / f"deploy/Dockerfile.{kind}"),
                "-t", source.config["services"][service]["image"],
                *(["--target", target] if target else []), str(ROOT),
            ], timeout=1200, private_diagnostic=directory / ("build-" + kind + ".private.log"))
            private_write(directory / ("build-" + kind + ".log"), output)
        source.compose("pull", "--policy", "missing", "postgres", "redis", timeout=300)
        check(
            source_fingerprint() == source_hash,
            "Source changed during build; wait for agents to finish and rerun",
        )
        return {
            "source_sha256": source_hash,
            "images": image_inventory(source),
            "host_application_packages_used": False,
            "build_cache": "allowed; locked install stages required by Dockerfiles",
        }

    def installed_runtime_parity():
        paths = [str(path.relative_to(ROOT)) for prefix in ("backend/app", "backend/scripts", "backend/alembic", "emulation", "deploy")
                 for path in (ROOT / prefix).rglob("*.py")
                 if not path.name.startswith("test_") and "tests" not in path.parts
                 and path.name != "verify.py" and "__pycache__" not in path.parts]
        expected = {"/opt/nanfo/" + name: digest((ROOT / name).read_bytes()) for name in paths}
        # Runs as the shipped non-root user, detecting unreadable COPY directories
        # as well as stale cache/source bytes before any initialized volumes.
        proof = json.loads(run([
            "docker", "run", "--rm", "--pull=never", "-i", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--label", "com.docker.compose.project=" + source.project,
            "--label", "com.docker.compose.service=source-parity", "--entrypoint", "python",
            source.config["services"]["api"]["image"], "-c",
            "import hashlib,json,sys; from pathlib import Path; expected=json.load(sys.stdin); "
            "bad=[p for p,h in expected.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]; "
            "print(json.dumps({'files':len(expected),'matched':not bad})); sys.exit(bool(bad))",
        ], stdin=json.dumps(expected).encode(), timeout=120,
           private_diagnostic=directory / "source-parity.private.log"))
        check(proof["matched"] is True, "Installed runtime source parity differs")
        return proof

    if not args.reuse_build_record:
        matrix.case("locked_container_build", build)
        matrix.case(
            "installed_source_parity", installed_runtime_parity
        )
    matrix.case("fresh_volumes", lambda: fresh_volumes(source))

    # Only fresh source gets migrations. Target restore never executes initialize.
    def initialize():
        source.compose("run", "--rm", "--no-deps", "volume-init", timeout=120)
        source.compose(
            "up",
            "-d",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "180",
            *STORES,
            timeout=240,
        )
        source.compose("run", "--rm", "--no-deps", "initialize", timeout=240)
        return installed_schema(source)

    matrix.case("migration_0027", initialize)
    api = matrix.case(
        "full_stack_readiness", lambda: start_application(source), record=False
    )
    # Never store the API object (which holds tokens) in evidence.
    matrix.rows["full_stack_readiness"]["detail"] = (
        "Gateway /ready and all six work-coupled worker healthchecks passed"
    )
    matrix.case("distributed_failover", lambda: distributed_failover(source))

    def login():
        value = api.request(
            "POST",
            "/api/v1/auth/login",
            body={"email": env["NANFO_BOOTSTRAP_EMAIL"], "password": password},
        )
        api.token = value["access_token"]
        check(
            "Admin" in api.request("GET", "/api/v1/auth/me")["roles"],
            "Bootstrap actor lacks Admin role",
        )
        return value

    tokens = matrix.case("bootstrap_login", login, record=False)
    matrix.rows["bootstrap_login"]["detail"] = {
        "generated_password": True,
        "password_in_argv": False,
        "authenticated_bootstrap_actor": True,
    }
    matrix.case("frontend_http", lambda: frontend_smoke(api))
    binding = bind_lab(source, api)
    workspace, network = binding["workspace_id"], binding["network_id"]
    spatial_assets = matrix.case(
        "spatial_asset_upload", lambda: create_spatial_assets(api, network)
    )
    # Scope creation uses the installed topology manifest even without the lab;
    # it does not fabricate observations or measured network telemetry.
    lab_result = None
    if args.lab:
        activated = matrix.case(
            "lab_binding", lambda: activate_lab(source, target, api, binding, directory)
        )
        if activated:
            lab_result = matrix.case(
                "lab_congestion", lambda: lab_traffic(source, api, binding)
            )
    else:
        matrix.block("lab_binding", "Lab profile not requested")
        matrix.block("lab_congestion", "Lab profile not requested")
    if args.model:
        matrix.case(
            "model_diagnostic",
            lambda: diagnose_model(source, target, api, network, directory, login),
        )
    else:
        matrix.block("model_diagnostic", "Frozen model diagnosis not requested")
    simulation = matrix.case("simulation", lambda: verify_simulation(api, network))
    matrix.rows["simulation"]["detail"] = {
        "simulation_id": simulation["simulation_id"],
        "loss_pct": simulation["run_output"]["loss_pct"],
        "configured_model_only": True,
    }
    reports = []
    for fmt in ("csv", "pdf"):

        def report(fmt=fmt):
            job = api.request(
                "POST",
                "/api/v1/reports/generate",
                expected=202,
                body=report_body(workspace, network, simulation["simulation_id"], fmt),
            )
            return download_report(api, workspace, job, fmt)

        reports.append(matrix.case("report_" + fmt, report))
    matrix.case("database_stop_readiness", lambda: database_outage(source, api))
    matrix.case("worker_stale_heartbeat", lambda: heartbeat_outage(source))
    restarted = matrix.case(
        "api_worker_restart",
        lambda: restart_with_pending_work(
            source, api, workspace, network, simulation["simulation_id"]
        ),
    )
    reports.append(restarted["report"])
    archive_proof = matrix.case("nonempty_archive_delete", lambda: nonempty_archive(source, binding))
    # Refresh immediately before backup so rejection cannot be credited to expiry.
    tokens = login()
    end = datetime.now(timezone.utc).isoformat()
    telemetry = telemetry_snapshot(api, workspace, network, end)
    before_sim = api.request(
        "GET", "/api/v1/simulations/" + simulation["simulation_id"]
    )
    before_intents = {}
    if lab_result:
        for operation in ("shape", "restore"):
            identity = lab_result[operation]["intent_id"]
            before_intents[identity] = api.request(
                "GET", "/api/v1/intents/" + identity, params={"workspace_id": workspace}
            )
    pinned_images = image_inventory(source)
    for stack in (source, target):
        pin_file = directory / (stack.project + "-images.json")
        private_write(
            pin_file,
            {
                "services": {
                    name: {"image": item["id"]} for name, item in pinned_images.items()
                }
            },
        )
        stack.files = [*stack.files, pin_file]
        stack.config = json.loads(stack.compose("config", "--format", "json"))
        validate_compose(stack.config, stack.project, directory)
    matrix.case(
        "coordinated_encrypted_backup",
        lambda: encrypted_backup(source, archive, key_path),
    )
    matrix.case(
        "distinct_fresh_restore",
        lambda: restore_stack(target, source, archive, key_path),
    )

    def image_schema():
        check(
            image_inventory(target) == image_inventory(source),
            "Restored image IDs/OS/architecture drifted",
        )
        installed_schema(target)
        return {
            "exact_image_ids_os_architecture": True,
            "schema": "0027",
            "target_migrations_executed": False,
        }

    matrix.case("restore_image_schema", image_schema)
    restored = start_application(target)

    def invalid_tokens():
        # Decode only expiry for the test, never accept this unverified payload as auth.
        payload = tokens["access_token"].split(".")[1]
        expiry = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )["exp"]
        check(
            expiry > time.time(),
            "Old token expired before restore test; invalidation unproven",
        )
        restored.token = tokens["access_token"]
        restored.request("GET", "/api/v1/auth/me", expected=401)
        restored.request(
            "POST",
            "/api/v1/auth/refresh",
            expected=401,
            body={"refresh_token": tokens["refresh_token"]},
        )
        restored.token = ""
        new = restored.request(
            "POST",
            "/api/v1/auth/login",
            body={"email": env["NANFO_BOOTSTRAP_EMAIL"], "password": password},
        )
        restored.token = new["access_token"]
        restored.request("GET", "/api/v1/auth/me")
        return "Unexpired old access and refresh rejected; new login accepted"

    matrix.case("old_tokens_invalid", invalid_tokens)

    def identical_reports():
        for report in reports:
            check(
                download_report(restored, workspace, report, report["format"])
                == report,
                "Restored report bytes/receipt changed",
            )
        return {"identical_downloads": len(reports), "formats": ["csv", "pdf"]}

    matrix.case("restored_report_bytes", identical_reports)
    matrix.case(
        "restored_spatial_assets",
        lambda: verify_spatial_assets(restored, network, spatial_assets),
    )

    def workflows():
        after = restored.request(
            "GET", "/api/v1/simulations/" + simulation["simulation_id"]
        )
        fields = (
            "simulation_id",
            "state",
            "run_output",
            "input_sha256",
            "checkpoint_sha256",
        )
        check(
            all(before_sim[field] == after[field] for field in fields),
            "Persisted workflow/model checkpoint changed",
        )
        check(
            restored.request(
                "GET", "/api/v1/simulations/" + restarted["simulation_id"]
            )["state"]
            == "completed",
            "Restart workflow missing after restore",
        )
        for identity, before in before_intents.items():
            after_intent = restored.request(
                "GET", "/api/v1/intents/" + identity, params={"workspace_id": workspace}
            )
            check(
                before["status"] == after_intent["status"]
                and before["execution_provenance"]
                == after_intent["execution_provenance"],
                "Physical workflow provenance lost during restore",
            )
        return {
            "simulation_checkpoint_identical": True,
            "restart_workflow_survived": True,
            "physical_workflows_identical": len(before_intents),
        }

    matrix.case("restored_workflows", workflows)
    if lab_result and telemetry["count"]:

        def restored_telemetry():
            check(
                telemetry_snapshot(restored, workspace, network, end) == telemetry,
                "Persisted telemetry identities/values changed",
            )
            return telemetry

        matrix.case("restored_telemetry", restored_telemetry)
    else:
        matrix.block(
            "restored_telemetry",
            "No actual measured telemetry existed; empty-to-empty is not survival proof",
        )
    matrix.case("restored_archive_bytes", lambda: restored_archive(target, archive_proof))
    matrix.case(
        "source_unchanged",
        lambda: check(
            source_fingerprint() == source_hash,
            "Source changed during campaign; evidence invalidated",
        ),
    )


def main(argv=None):
    args = parse_args(argv)
    check(
        args.work_root.is_dir() and not args.work_root.is_symlink(),
        "Work root must be an existing real directory",
    )
    os.umask(0o077)
    directory = Path(
        tempfile.mkdtemp(prefix="nanfo-deploy-verify-", dir=args.work_root)
    )
    evidence = directory / "evidence"
    evidence.mkdir(mode=0o700)
    matrix, registry = Matrix(), Registry(evidence)
    matrix.progress = True
    print(json.dumps({"evidence_directory": str(evidence)}), flush=True)

    def interrupted(signum, frame):
        raise VerificationError("Verification interrupted; cleanup required")

    old_handlers = {
        sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        matrix.case("campaign", lambda: verify_live(args, directory, matrix, registry))
    except BaseException as error:  # noqa: BLE001 - final evidence must never contain raw secrets
        # Matrix actions contain fixed diagnostic messages, not command stderr.
        if matrix.rows["package_contract"]["status"] == "pending":
            matrix.block(
                "package_contract",
                "Unexpected campaign failure: " + type(error).__name__,
            )
        failure = (
            str(error) if isinstance(error, VerificationError) else type(error).__name__
        )
    else:
        failure = None
    finally:
        for sig in old_handlers:
            signal.signal(sig, signal.SIG_IGN)
        try:
            matrix.case("cleanup", lambda: registry.cleanup(timeout=120))
        except BaseException:  # noqa: BLE001 - the matrix already recorded the cleanup failure
            failure = failure or "Registered resource cleanup failed"
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    result = matrix.result(final=True)
    result.update(
        live_authorized=True,
        agents_idle_attested=True,
        failure=failure,
        evidence_directory=str(evidence),
        live_requested_lab=args.lab,
        live_requested_model=args.model,
    )
    if failure:
        result.update(core_passed=False, all_green=False, step15_complete=False)
    private_write(evidence / "result.json", result)
    print(
        json.dumps(
            {
                "evidence": str(evidence / "result.json"),
                "counts": result["counts"],
                "step15_complete": result["step15_complete"],
                "all_green": result["all_green"],
            }
        )
    )
    return (
        0
        if result["step15_complete"]
        and (
            not args.model or result["cases"]["model_diagnostic"]["status"] == "passed"
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
