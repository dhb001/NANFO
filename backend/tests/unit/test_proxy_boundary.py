"""ADR027 exact-peer trust and real nginx/Uvicorn login-IP regression.

Only ephemeral loopback listeners/owned nginx child are used. Persistence is fake;
the real auth route/service, rate limiter, forwarding and HTTP transports execute.
"""

import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from unittest.mock import AsyncMock

from fastapi import FastAPI
import httpx
import pytest
import uvicorn
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import yaml

from app.api.v1.auth import router
from app.core.dependencies import get_db, get_redis
from app.modules.identity.repository import AuditLogRepository, UserRepository


ROOT = Path(__file__).resolve().parents[3]


def test_image_enables_proxy_parsing_but_trusts_nobody_without_compose_boundary():
    dockerfile = (ROOT / "deploy/Dockerfile.backend").read_text()
    command = next(line.removeprefix("CMD ") for line in dockerfile.splitlines() if line.startswith("CMD "))
    assert "--proxy-headers" in json.loads(command)
    assert 'FORWARDED_ALLOW_IPS=""' in dockerfile
    assert "--forwarded-allow-ips" not in json.loads(command)


@pytest.mark.parametrize("overlays", [
    [], ["distributed"], ["distributed", "fleet", "distributed-fleet"],
    ["distributed", "live-ai", "distributed-live-ai"],
    ["distributed", "autonomous-client", "distributed-autonomous-client"],
    ["distributed", "fleet", "distributed-fleet", "live-ai", "distributed-live-ai",
     "autonomous-client", "distributed-autonomous-client"],
])
def test_resolved_proxy_network_is_gateway_only_and_inherited_by_all_apis(overlays):
    if shutil.which("docker") is None:
        pytest.skip("Compose CLI unavailable")
    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    env.update(
        NANFO_PROJECT="nanfo-deploy-proxy-config-test", NANFO_STATE_DIR="/tmp/opencode/unprovisioned",
        NANFO_BACKEND_IMAGE="test:backend", NANFO_FRONTEND_IMAGE="test:frontend",
        NANFO_NEO4J_IMAGE="test:neo4j", NANFO_AI_IMAGE="test:ai", NANFO_FLEET_IMAGE="test:fleet",
        NANFO_BOOTSTRAP_EMAIL="test@example.com", NANFO_LIVE_MODEL_REGISTRY_SHA256="a" * 64,
        NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256="b" * 64,
        NANFO_PROXY_SUBNET="172.29.123.0/24", NANFO_PROXY_GATEWAY_IP="172.29.123.2",
    )
    command = ["docker", "compose", "--env-file", "/dev/null", "-f", str(ROOT / "deploy/compose.yaml")]
    for overlay in overlays:
        command += ["-f", str(ROOT / f"deploy/compose.{overlay}.yaml")]
    result = subprocess.run([*command, "--profile", "*", "config", "--format", "json"],
                            env=env, capture_output=True, text=True, check=True, timeout=15)
    config = json.loads(result.stdout)
    services = config["services"]
    apis = {"api", "api2"} if "distributed" in overlays else {"api"}
    for name in apis:
        assert services[name]["environment"]["FORWARDED_ALLOW_IPS"] == "172.29.123.2"
        assert set(services[name]["networks"]) == {"private", "proxy"}
        assert not services[name].get("ports")
    assert services["gateway"]["networks"]["proxy"]["ipv4_address"] == "172.29.123.2"
    assert set(services["gateway"]["networks"]) == {"proxy", "gateway"}
    assert {name for name, svc in services.items() if "proxy" in svc.get("networks", {})} == apis | {"gateway"}
    assert config["networks"]["proxy"]["internal"] is True
    assert config["networks"]["private"]["internal"] is True
    assert config["networks"]["proxy"]["ipam"]["config"][0]["subnet"] == "172.29.123.0/24"


@pytest.mark.parametrize("peer,expected", [
    ("172.30.27.2", "198.51.100.7"),
    ("172.30.27.3", "172.30.27.3"),
    ("172.19.0.5", "172.19.0.5"),
    ("203.0.113.20", "203.0.113.20"),
    ("127.0.0.1", "127.0.0.1"),
])
@pytest.mark.parametrize("scope_type", ["http", "websocket"])
async def test_configured_trust_rejects_other_private_public_and_local_peers(peer, expected, scope_type):
    config = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text())
    setting = config["services"]["api"]["environment"]["FORWARDED_ALLOW_IPS"]
    trusted = setting.split(":-", 1)[1].rstrip("}")
    captured = []

    async def app(scope, receive, send):
        captured.append(scope)

    middleware = ProxyHeadersMiddleware(app, trusted_hosts=trusted)
    await middleware({"type": scope_type, "client": (peer, 1234), "scheme": "http",
                      "headers": [(b"x-forwarded-for", b"198.51.100.7"),
                                  (b"x-forwarded-proto", b"https")]}, None, None)
    assert captured[0]["client"][0] == expected
    assert captured[0]["scheme"] == (
        ("wss" if scope_type == "websocket" else "https") if peer == trusted else "http"
    )


async def test_real_nginx_two_login_clients_and_untrusted_spoof(tmp_path, monkeypatch, fake_redis, mock_db):
    nginx = shutil.which("nginx")
    if nginx is None:
        pytest.skip("nginx executable required for live forwarding test")
    monkeypatch.setattr(UserRepository, "get_by_email", AsyncMock(return_value=None))
    audit = AsyncMock()
    monkeypatch.setattr(AuditLogRepository, "append", audit)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: fake_redis

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    api_port = listener.getsockname()[1]
    # Loopback stand-in for the exact fixed nginx peer; direct clients remain untrusted.
    server = uvicorn.Server(uvicorn.Config(
        app, proxy_headers=True, forwarded_allow_ips="127.0.0.10", lifespan="off",
        log_level="critical", access_log=False,
    ))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    process = None
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            gateway_port = reservation.getsockname()[1]
        upstream = tmp_path / "upstream.conf"
        upstream.write_text(f"upstream nanfo_api {{ server 127.0.0.1:{api_port}; }}\n")
        # Execute the checked-in forwarding directives, replacing only host paths,
        # ephemeral port and the loopback source-address stand-in for Docker IPAM.
        config = (ROOT / "deploy/nginx.conf").read_text()
        config = config.replace("worker_processes auto;", "worker_processes 1;")
        config = config.replace("pid /tmp/nginx.pid;", f"pid {tmp_path}/nginx.pid;")
        config = config.replace("/etc/nginx/nginx-upstream.conf", str(upstream))
        config = config.replace("listen 8080;", f"listen 127.0.0.1:{gateway_port};")
        for directory in ("client", "proxy", "fastcgi", "uwsgi", "scgi"):
            config = config.replace(f"/tmp/{directory};", f"{tmp_path}/{directory};")
        config = config.replace("proxy_http_version 1.1;", "proxy_http_version 1.1; proxy_bind 127.0.0.10;")
        path = tmp_path / "nginx.conf"
        path.write_text(config)
        process = subprocess.Popen([nginx, "-p", str(tmp_path), "-c", str(path), "-g", "daemon off;"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        async with httpx.AsyncClient(trust_env=False) as client:
            async with asyncio.timeout(10):
                while True:
                    assert process.poll() is None, process.stderr.read()
                    try:
                        await client.get(f"http://127.0.0.1:{gateway_port}/health")
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.02)

        async def login(source, port, email):
            transport = httpx.AsyncHTTPTransport(local_address=source)
            async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
                return await client.post(
                    f"http://127.0.0.1:{port}/api/v1/auth/login",
                    json={"email": email, "password": "deliberately-invalid"},
                    headers={"X-Forwarded-For": "198.51.100.99, 203.0.113.99", "X-Forwarded-Proto": "https"},
                )

        for _ in range(5):
            assert (await login("127.0.0.2", gateway_port, "first@example.com")).status_code == 401
        assert (await login("127.0.0.2", gateway_port, "first@example.com")).status_code == 429
        assert (await login("127.0.0.3", gateway_port, "second@example.com")).status_code == 401
        assert (await login("127.0.0.4", api_port, "direct@example.com")).status_code == 401
        assert await fake_redis.get("ratelimit:login:127.0.0.2") == "6"
        assert await fake_redis.get("ratelimit:login:127.0.0.3") == "1"
        assert await fake_redis.get("ratelimit:login:127.0.0.4") == "1"
        for address in ("127.0.0.10", "198.51.100.99", "203.0.113.99"):
            assert await fake_redis.get(f"ratelimit:login:{address}") is None
        assert {call.kwargs["metadata"]["ip_address"] for call in audit.await_args_list} == {
            "127.0.0.2", "127.0.0.3", "127.0.0.4",
        }
    finally:
        if process is not None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            process.stderr.close()
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        finally:
            listener.close()
