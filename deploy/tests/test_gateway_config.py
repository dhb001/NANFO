"""Gateway (nginx) policy, runtime rendering and CI-renderer compatibility (ADR-028 R06/C1/C22).

Static checks plus the real POSIX entrypoint; the live nginx behaviour is exercised by
backend/tests/unit/test_proxy_boundary.py and backend/tests/integration/test_gateway_headers.py.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from deploy import gateway_config, manage

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
NGINX = (DEPLOY / "nginx.conf").read_text()
HEADERS = (DEPLOY / "nginx-security-headers.conf").read_text()
PROXY = (DEPLOY / "nginx-proxy.conf").read_text()
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self' blob: data:; worker-src 'self' blob:; object-src 'none'; "
       "base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
HEADER_INCLUDE = "include /etc/nginx/nginx-security-headers.conf;"
PROXY_INCLUDE = "include /etc/nginx/nginx-proxy.conf;"


def uncommented(config):
    return "\n".join(line.split("#", 1)[0].rstrip() for line in config.splitlines())


def locations(config):
    """(selector, body) for every location block; blocks close on a line of their own."""
    return re.findall(r"^\s*location\s+([^{\n]+?)\s*\{\n(.*?)\n\s*\}$", uncommented(config), re.S | re.M)


def block(pattern):
    """Body of a top-level map/server block that closes on a line of its own."""
    return re.search(pattern + r"\s*\{\n(.*?)\n\s*\}$", uncommented(NGINX), re.S | re.M).group(1)


def directives(text):
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def test_security_headers_are_the_strict_set_and_always_sent():
    lines = directives(HEADERS)
    assert f'add_header Content-Security-Policy "{CSP}" always;' in lines
    assert 'add_header Referrer-Policy "no-referrer" always;' in lines
    assert 'add_header X-Content-Type-Options "nosniff" always;' in lines
    assert 'add_header X-Frame-Options "DENY" always;' in lines
    policy = next(line for line in lines if line.startswith("add_header Permissions-Policy"))
    for feature in ("camera=()", "microphone=()", "geolocation=()", "payment=()", "usb=()"):
        assert feature in policy
    assert all(line.startswith("add_header ") and line.endswith(" always;") for line in lines)
    assert "unsafe-eval" not in HEADERS and "*" not in CSP


def test_every_location_and_the_server_include_the_header_set():
    blocks = locations(NGINX)
    assert len(blocks) >= 11
    for selector, body in blocks:
        assert HEADER_INCLUDE in body, selector
    server = uncommented(NGINX).split("server {", 1)[1]
    assert HEADER_INCLUDE in server.split("location", 1)[0]
    # No location relies on inheritance: any add_header there would drop the set otherwise.
    assert NGINX.count(HEADER_INCLUDE) == len(blocks) + 1


def location(selector):
    return next(body for name, body in locations(NGINX) if name == selector)


def test_public_readiness_docs_and_source_maps_are_404():
    assert "return 404;" in location("= /ready")
    assert "return 404;" in location(r"~ \.map$")
    assert "return 404;" in location(r"~ ^/api/(docs|redoc|openapi\.json)(/|$)")
    for proxied in ("= /api/v1/auth/login", "/api/", "/ws/", "= /health"):
        assert PROXY_INCLUDE in location(proxied)
    assert "ready" not in "".join(body for name, body in locations(NGINX) if PROXY_INCLUDE in body)


def test_proxy_forwards_one_trusted_hop_subprotocol_and_request_id():
    lines = directives(PROXY)
    assert "proxy_pass http://nanfo_api;" in lines and "proxy_http_version 1.1;" in lines
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in lines  # overwrite, never append
    assert "proxy_set_header X-Forwarded-Proto $nanfo_forwarded_proto;" in lines
    assert "proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;" in lines
    assert "proxy_set_header X-Request-ID $nanfo_request_id;" in lines
    assert "gzip off;" in lines and "$proxy_add_x_forwarded_for" not in PROXY
    assert "proxy_max_temp_file_size 0;" in directives(NGINX)


def test_realip_trusts_only_the_rendered_hop_and_proto_comes_from_it():
    lines = directives(NGINX)
    assert "include /tmp/nginx/realip*.conf;" in lines
    assert "real_ip_header X-Forwarded-For;" in lines and "real_ip_recursive on;" in lines
    assert "set_real_ip_from" not in NGINX  # only the rendered include may add a trusted hop
    trusted = block(r"map \$realip_remote_addr \$nanfo_trusted_hop")
    assert directives(trusted) == ["default 0;", "include /tmp/nginx/trusted-hop*.map;"]
    proto = block(r'map "\$nanfo_trusted_hop:\$http_x_forwarded_proto" \$nanfo_forwarded_proto')
    assert directives(proto) == ["default $scheme;", '"1:https" https;', '"1:http" http;']
    request_id = block(r"map \$http_x_request_id \$nanfo_request_id")
    assert directives(request_id) == ["default $request_id;", '"~^[A-Za-z0-9._:-]{1,128}$" $http_x_request_id;']


def test_login_edge_rate_limit_returns_the_standard_envelope():
    lines = directives(NGINX)
    assert "limit_req_zone $binary_remote_addr zone=login:10m rate=10r/m;" in lines
    assert "limit_req_status 429;" in lines
    login = directives(location("= /api/v1/auth/login"))
    assert "limit_req zone=login burst=5 nodelay;" in login and "error_page 429 = @login_throttled;" in login
    throttled = location("@login_throttled")
    assert "default_type application/json;" in throttled and 'add_header Retry-After "6" always;' in throttled
    body = re.search(r"return 429 '(.*)';", throttled).group(1)
    envelope = json.loads(body.replace("$nanfo_request_id", "req-1").replace("$time_iso8601", "2026-09-24T00:00:00+00:00"))
    assert envelope == {"success": False, "data": None,
                        "meta": {"request_id": "req-1", "timestamp": "2026-09-24T00:00:00+00:00"},
                        "errors": {"code": "RATE_LIMITED", "message": "Too many login attempts. Please try again later."}}


def test_logging_is_json_without_query_strings_and_errors_are_bounded():
    log_format = re.search(r"log_format safe escape=json (.*?);\n", NGINX, re.S).group(1)
    for variable in ("$nanfo_request_id", "$request_time", "$upstream_status", "$uri", "$status"):
        assert variable in log_format
    for forbidden in ("$request\"", "$request_uri", "$args", "$query_string", "$http_referer", "$request ", "$is_args"):
        assert forbidden not in log_format
    lines = directives(NGINX)
    assert "error_log /dev/stderr warn;" in lines and "worker_processes 1;" in lines
    # Request-scoped nginx error records embed the request line (query strings) -> crit.
    assert "error_log /dev/stderr crit;" in directives(NGINX.split("server {", 1)[1])


def test_static_caching_and_compression_policy():
    assets = directives(location("/assets/"))
    assert "try_files $uri =404;" in assets
    assert 'add_header Cache-Control "public, max-age=31536000, immutable" always;' in assets
    assert 'add_header Cache-Control "no-cache" always;' in directives(location("= /index.html"))
    assert "try_files $uri $uri/ /index.html;" in directives(location("/"))
    lines = directives(NGINX)
    assert "gzip on;" in lines
    types = re.search(r"gzip_types (.*?);", NGINX, re.S).group(1).split()
    assert {"text/css", "application/javascript", "application/json", "image/svg+xml", "application/wasm"} <= set(types)


def render(tmp_path, **environment):
    prefix = tmp_path / "render"
    environ = {"PATH": os.environ["PATH"], **environment}
    return subprocess.run(["sh", str(DEPLOY / "gateway-entrypoint.sh"), "--render", str(prefix)],
                          env=environ, capture_output=True, text=True, timeout=10), prefix


def test_entrypoint_renders_trusted_hop_and_upstream_selection(tmp_path):
    result, prefix = render(tmp_path, NANFO_GATEWAY_TRUSTED_HOP="172.31.87.1", NANFO_GATEWAY_UPSTREAM="distributed")
    assert result.returncode == 0, result.stderr
    assert (prefix / "realip.conf").read_text() == "set_real_ip_from 172.31.87.1/32;\n"
    assert (prefix / "trusted-hop.map").read_text() == "172.31.87.1 1;\n"
    assert (prefix / "upstream.conf").read_text() == "include /etc/nginx/nanfo/upstream-distributed.conf;\n"
    assert oct((prefix / "realip.conf").stat().st_mode & 0o777) == "0o600"
    result, prefix = render(tmp_path)  # defaults: single upstream, nobody trusted
    assert result.returncode == 0
    assert (prefix / "upstream.conf").read_text() == "include /etc/nginx/nanfo/upstream-single.conf;\n"
    assert not (prefix / "realip.conf").exists() and not (prefix / "trusted-hop.map").exists()


@pytest.mark.parametrize("hop", ["256.1.1.1", "1.2.3", "01.2.3.4", "1.2.3.4/24", "1.2.3.4;", "a.b.c.d",
                                 "1.2.3.4 5.6.7.8", "::1", "1.2.3.4.5", "1..2.3"])
def test_entrypoint_refuses_anything_but_one_ipv4_hop(tmp_path, hop):
    result, prefix = render(tmp_path, NANFO_GATEWAY_TRUSTED_HOP=hop)
    assert result.returncode == 64 and not (prefix / "realip.conf").exists()


def test_entrypoint_refuses_unknown_upstream_mode_and_arguments(tmp_path):
    assert render(tmp_path, NANFO_GATEWAY_UPSTREAM="other")[0].returncode == 64
    assert subprocess.run(["sh", str(DEPLOY / "gateway-entrypoint.sh"), "--other"], capture_output=True).returncode == 64


def test_compose_pins_the_published_port_bridge_and_its_trusted_hop():
    config = yaml.safe_load((DEPLOY / "compose.yaml").read_text())
    gateway = config["services"]["gateway"]
    assert gateway["environment"] == {"NANFO_GATEWAY_TRUSTED_HOP": "${NANFO_GATEWAY_BRIDGE_IP:-172.31.87.1}",
                                      "NANFO_GATEWAY_UPSTREAM": "single"}
    assert config["networks"]["gateway"]["ipam"]["config"] == [
        {"subnet": "${NANFO_GATEWAY_SUBNET:-172.31.87.0/24}", "gateway": "${NANFO_GATEWAY_BRIDGE_IP:-172.31.87.1}"}]
    assert gateway["ports"] == ["127.0.0.1:${NANFO_HTTP_PORT:-8787}:8080"]
    assert gateway["healthcheck"]["test"][-1] == "http://127.0.0.1:8080/index.html"
    distributed = yaml.safe_load((DEPLOY / "compose.distributed.yaml").read_text())
    assert distributed["services"]["gateway"]["environment"] == {"NANFO_GATEWAY_UPSTREAM": "distributed"}
    assert "configs" not in distributed and "configs" not in distributed["services"]["gateway"]


def test_deployment_allocation_pins_distinct_proxy_and_gateway_bridges(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(manage, "run", Mock(side_effect=[
        Mock(stdout=""), Mock(stdout="[]"),
    ]))
    monkeypatch.setattr(manage.secrets, "randbelow", lambda size: 0)
    first, second = manage.allocate_deployment_networks(2)
    for value in (first, second):
        assert value["NANFO_GATEWAY_BRIDGE_IP"].endswith(".1") and value["NANFO_PROXY_GATEWAY_IP"].endswith(".254")
        assert value["NANFO_GATEWAY_SUBNET"] != value["NANFO_PROXY_SUBNET"]
    assert len({first["NANFO_GATEWAY_SUBNET"], second["NANFO_GATEWAY_SUBNET"],
                first["NANFO_PROXY_SUBNET"], second["NANFO_PROXY_SUBNET"]}) == 4


def test_frontend_image_bakes_every_gateway_file_and_runs_the_entrypoint():
    dockerfile = (DEPLOY / "Dockerfile.frontend").read_text()
    for source, target in (("nginx.conf", "/etc/nginx/nginx.conf"), ("nginx-upstream.conf", "/etc/nginx/nginx-upstream.conf"),
                           ("nginx-security-headers.conf", "/etc/nginx/nginx-security-headers.conf"),
                           ("nginx-proxy.conf", "/etc/nginx/nginx-proxy.conf"),
                           ("nginx-upstream-single.conf", "/etc/nginx/nanfo/upstream-single.conf"),
                           ("nginx-distributed-upstream.conf", "/etc/nginx/nanfo/upstream-distributed.conf"),
                           ("gateway-entrypoint.sh", "/usr/local/bin/nanfo-gateway-entrypoint.sh")):
        assert f"COPY deploy/{source} {target}" in dockerfile
        assert f"!deploy/{source}" in (DEPLOY / "Dockerfile.frontend.dockerignore").read_text()
        assert manage.context_allowed("frontend", f"deploy/{source}", ("deploy", source), Path(source).suffix)
    assert 'ENTRYPOINT ["sh", "/usr/local/bin/nanfo-gateway-entrypoint.sh"]' in dockerfile
    assert "npm ci --ignore-scripts" in dockerfile
    assert "VITE_" in dockerfile and "find dist -name '*.map' -delete" in dockerfile
    assert "ARG VITE" not in dockerfile and "ENV VITE" not in dockerfile


def test_frontend_build_refuses_vite_environment_without_a_masked_pipe():
    dockerfile = (DEPLOY / "Dockerfile.frontend").read_text()
    program = re.search(r"RUN awk '([^']+)'", dockerfile).group(1)

    def guard(**environment):
        return subprocess.run(["awk", program], env={"PATH": os.environ["PATH"], **environment},
                              capture_output=True, text=True, timeout=10)

    assert guard().returncode == 0
    refused = guard(VITE_API_BASE_URL="http://127.0.0.1:8000")
    assert refused.returncode == 1 and "C16" in refused.stderr
    # hadolint DL4006: no shell pipe whose left-hand failure could be masked.
    assert not [line for line in dockerfile.splitlines() if re.search(r"(?<!\|)\|(?!\|)", line)]


def test_shipped_config_stays_renderable_by_the_ci_gateway_lane(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "backend"))
    sys.modules.pop("scripts", None)
    from scripts.review_fullstack import render_gateway_config

    rendered = render_gateway_config(NGINX, prefix=tmp_path, dist=tmp_path / "dist", upstream=tmp_path / "up.conf", port=18123)
    assert "listen 127.0.0.1:18123;" in rendered and CSP not in rendered  # headers stay in the shipped include
    path = gateway_config.render(tmp_path / "local", listen="127.0.0.1:18124", upstreams=["127.0.0.1:9"],
                                 html=tmp_path / "html", trusted_hop="127.0.0.20")
    text = path.read_text()
    assert "/etc/nginx/nginx-" not in text and (tmp_path / "local" / "nginx" / "realip.conf").exists()
    assert (tmp_path / "local" / "nginx-security-headers.conf").read_text() == HEADERS
