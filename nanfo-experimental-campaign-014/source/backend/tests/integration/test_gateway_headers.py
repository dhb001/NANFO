"""Run the gateway config on loopback with temporary paths; no Docker/deployment."""

import os
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("NANFO_TEST_NGINX") != "1", reason="NANFO_TEST_NGINX=1 required"
)


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    nginx = shutil.which("nginx")
    assert nginx, "Install nginx before enabling NANFO_TEST_NGINX"
    root = tmp_path_factory.mktemp("gateway")
    (root / "index.html").write_text("<html>NANFO gateway fixture</html>")

    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(401 if self.path == "/api/private" else 200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"upstream fixture")

        def log_message(self, *_):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config = (Path(__file__).resolve().parents[3] / "deploy/nginx.conf").read_text()
    config = config.replace("worker_processes auto", "worker_processes 1")
    config = config.replace("/tmp/", f"{root}/")
    config = config.replace("/dev/stderr", str(root / "error.log"))
    config = config.replace("/dev/stdout", str(root / "access.log"))
    config = config.replace("listen 8080", f"listen 127.0.0.1:{port}")
    config = config.replace("/usr/share/nginx/html", str(root))
    config = config.replace("http://api:8000", f"http://127.0.0.1:{upstream.server_port}")
    path = root / "nginx.conf"
    path.write_text(config)
    process = None
    try:
        subprocess.run([nginx, "-t", "-c", str(path), "-p", str(root)], check=True, capture_output=True)
        process = subprocess.Popen([nginx, "-c", str(path), "-p", str(root), "-g", "daemon off;"])
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            for _ in range(100):
                try:
                    client.get("/")
                    break
                except httpx.ConnectError:
                    assert process.poll() is None, (root / "error.log").read_text()
                    time.sleep(0.02)
            else:
                pytest.fail("temporary nginx did not start")
            yield client
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("path,status", [
    ("/", 200), ("/ops/digital-twin", 200), ("/missing.map", 404),
    ("/api/private", 401), ("/api/docs", 200), ("/health", 200),
])
def test_headers_on_static_spa_errors_and_proxy(gateway, path, status):
    response = gateway.get(path)
    assert response.status_code == status
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == (
        "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'"
    )
