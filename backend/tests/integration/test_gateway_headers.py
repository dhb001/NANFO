"""Run the shipped gateway config on loopback with temporary paths; no Docker/deployment."""

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("NANFO_TEST_NGINX") != "1", reason="NANFO_TEST_NGINX=1 required"
)

ROOT = Path(__file__).resolve().parents[3]
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self' blob: data:; worker-src 'self' blob:; object-src 'none'; "
       "base-uri 'self'; frame-ancestors 'none'; form-action 'self'")


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    nginx = shutil.which("nginx")
    assert nginx, "Install nginx before enabling NANFO_TEST_NGINX"
    sys.path.insert(0, str(ROOT / "deploy"))
    try:
        import gateway_config
    finally:
        sys.path.remove(str(ROOT / "deploy"))
    root = tmp_path_factory.mktemp("gateway")
    html = root / "html"
    (html / "assets").mkdir(parents=True)
    (html / "index.html").write_text("<html>NANFO gateway fixture</html>")
    (html / "assets" / "app-1234.js").write_text("console.log('nanfo');\n" * 200)
    seen = []

    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append({key.lower(): value for key, value in self.headers.items()} | {"path": self.path})
            body = b"x" * 4096 if self.path.startswith("/api/large") else b"upstream fixture"
            self.send_response(401 if self.path == "/api/private" else 200)
            self.send_header("Content-Type", "application/json" if self.path.startswith("/api/large") else "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    # Keep production headers/proxy/logging; substitute only host paths, listener and
    # service discovery (host nginx must not depend on Docker DNS). No trusted hop.
    prefix = root / "prefix"
    config = gateway_config.render(prefix, listen=f"127.0.0.1:{port}",
                                   upstreams=[f"127.0.0.1:{upstream.server_port}"], html=html)
    process = None
    try:
        subprocess.run([nginx, "-t", "-c", str(config), "-p", str(prefix)], check=True, capture_output=True, timeout=5)
        process = subprocess.Popen([nginx, "-c", str(config), "-p", str(prefix), "-g", "daemon off;"])
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            for _ in range(100):
                try:
                    client.get("/")
                    break
                except httpx.ConnectError:
                    assert process.poll() is None, (prefix / "error.log").read_text()
                    time.sleep(0.02)
            else:
                pytest.fail("temporary nginx did not start")
            yield client, seen, prefix
    finally:
        try:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=5)


@pytest.mark.parametrize("path,status", [
    ("/", 200), ("/ops/digital-twin", 200), ("/missing.map", 404), ("/assets/missing.js", 404),
    ("/assets/app-1234.js", 200), ("/api/private", 401), ("/api/docs", 404), ("/api/openapi.json", 404),
    ("/ready", 404), ("/health", 200), ("/index.html", 200),
])
def test_headers_on_static_spa_errors_and_proxy(gateway, path, status):
    client, _, _ = gateway
    response = client.get(path)
    assert response.status_code == status
    assert response.headers["content-security-policy"] == CSP
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in response.headers["permissions-policy"]
    assert b"NANFO gateway fixture" not in response.content or path in {"/", "/ops/digital-twin", "/index.html"}


def test_asset_caching_compression_and_spa_revalidation(gateway):
    client, _, _ = gateway
    asset = client.get("/assets/app-1234.js", headers={"Accept-Encoding": "gzip"})
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert asset.headers["content-encoding"] == "gzip" and b"nanfo" in asset.content
    for path in ("/", "/index.html", "/ops/digital-twin"):
        assert client.get(path).headers["cache-control"] == "no-cache"
    proxied = client.get("/api/large", headers={"Accept-Encoding": "gzip"})
    # Proxied (token-bearing) responses are never compressed at the edge (BREACH).
    assert "content-encoding" not in proxied.headers and proxied.content == b"x" * 4096


def test_forwarding_ignores_untrusted_client_headers_and_logs_no_query(gateway):
    client, seen, prefix = gateway
    response = client.get("/api/large?token=secret-query-token", headers={
        "X-Forwarded-For": "198.51.100.5", "X-Forwarded-Proto": "https", "X-Request-ID": "trace-123",
        "Sec-WebSocket-Protocol": "nanfo.v1, nanfo.bearer.secret-bearer"})
    assert response.status_code == 200
    forwarded = next(row for row in reversed(seen) if row["path"].startswith("/api/large?token="))
    assert forwarded["x-forwarded-for"] == "127.0.0.1" and forwarded["x-forwarded-proto"] == "http"
    assert forwarded["x-request-id"] == "trace-123"
    assert forwarded["sec-websocket-protocol"] == "nanfo.v1, nanfo.bearer.secret-bearer"
    time.sleep(0.1)
    log = (prefix / "access.log").read_text()
    assert "secret-query-token" not in log and "secret-bearer" not in log and "trace-123" in log
