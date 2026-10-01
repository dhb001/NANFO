"""No-store regressions for R09/C22 admission, gateway rendering, resource fencing and cleanup."""

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.review_fullstack import (
    GATEWAY_TEMPLATE, LABEL, MAX_FAILED_CASES, MIME_TYPES, NO_CROSS_ORIGIN, AcceptanceFailure, OwnedNeo4j,
    Processes, browser_environment, browser_results, build_environment, clean_environment, embedded_loopback_api,
    exact_image, export_failure_artifacts, failed_case_details, main, playwright_argv, redact,
    render_gateway_config, validate_counts,
)


@pytest.mark.parametrize("value", ["neo4j:5", "latest", "sha256:bad", "http://localhost:7687"])
def test_mutable_image_or_external_service_is_not_admitted(value):
    with pytest.raises(argparse.ArgumentTypeError):
        exact_image(value)


def test_caller_credentials_and_service_urls_are_not_inherited(monkeypatch):
    for key in ("POSTGRES_HOST", "REDIS_URL", "NEO4J_URI", "JWT_SECRET_KEY", "R09_API_URL", "NODE_OPTIONS"):
        monkeypatch.setenv(key, "must-not-propagate")
    assert "must-not-propagate" not in clean_environment().values()


@pytest.mark.parametrize("counts", [
    None, {"total": 0}, {"total": 4},
    {"total": 5, "passed": 4, "failed": 0, "errors": 0, "skipped": 1},
    {"total": 5, "passed": 4, "failed": 1, "errors": 0, "skipped": 0},
    {"total": 5, "passed": 4, "failed": 0, "errors": 1, "skipped": 0},
])
def test_missing_empty_partial_skipped_and_failed_browser_lanes_fail(counts):
    with pytest.raises(AcceptanceFailure):
        validate_counts(counts)


def test_complete_zero_skip_browser_lane_passes():
    validate_counts({"total": 5, "passed": 5, "failed": 0, "errors": 0, "skipped": 0})


def test_interrupted_browser_xml_does_not_interrupt_cleanup(tmp_path):
    report = tmp_path / "broken.xml"
    report.write_text("<testsuites><testsuite>")
    assert browser_results(report) == (None, [])


def test_neo4j_cleanup_refuses_other_owners_even_with_a_cidfile(tmp_path):
    neo = OwnedNeo4j(tmp_path, {}, "sha256:" + "a" * 64)
    cid = "b" * 64
    neo.cidfile.write_text(cid)
    neo.docker = Mock(return_value=Mock(stdout=json.dumps([{
        "Id": cid, "Image": neo.image, "Config": {"Labels": {LABEL: "another-owner"}},
    }])))
    with pytest.raises(AcceptanceFailure, match="ownership_mismatch"):
        neo.cleanup()
    assert all(call.args[0] != "rm" for call in neo.docker.call_args_list)


def test_interrupted_create_cidfile_recovers_exact_owned_container(tmp_path):
    neo = OwnedNeo4j(tmp_path, {}, "sha256:" + "a" * 64)
    cid = "b" * 64
    neo.cidfile.write_text(cid)
    neo.docker = Mock(side_effect=[
        Mock(stdout=json.dumps([{"Id": cid, "Image": neo.image, "Config": {"Labels": {LABEL: neo.owner}}}])),
        Mock(returncode=0), Mock(returncode=1),
    ])
    assert neo.cleanup()
    assert neo.docker.call_args_list[1].args == ("rm", "--force", "--volumes", cid)


def test_cleanup_continues_after_one_process_fails(tmp_path):
    processes = Processes(tmp_path)
    processes.children = [Mock(), Mock(), Mock()]
    processes.stop = Mock(side_effect=[OSError(), True, True])
    assert not processes.cleanup()
    assert processes.stop.call_count == 3


def test_timeout_reaps_owned_child_and_leaves_unrelated_child_alive(tmp_path):
    processes = Processes(tmp_path)
    env = {"PATH": os.environ["PATH"]}
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            processes.run("timeout", [sys.executable, "-c", "import time; time.sleep(60)"], env, timeout=0.1)
        assert processes.children[0].poll() is not None
        assert unrelated.poll() is None
        assert processes.cleanup()
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


# ── ADR-028 C16/C22: same-origin production build behind the real gateway ─────────

def test_production_build_carries_no_api_or_websocket_base_url():
    env = build_environment({"PATH": "/usr/bin", "VITE_API_BASE_URL": "http://127.0.0.1:8000",
                             "VITE_WS_BASE_URL": "ws://127.0.0.1:8000", "VITE_ANYTHING": "x"})
    assert env == {"PATH": "/usr/bin", "VITE_ENABLE_MOCK_WS": "false"}


def test_browser_uses_the_gateway_origin_for_page_api_and_websocket(tmp_path):
    origin = "http://127.0.0.1:43210"
    env = browser_environment({"PATH": "/usr/bin"}, fixture=tmp_path / "f.json", origin=origin,
                              output=tmp_path / "out", junit=tmp_path / "j.xml")
    assert env["R09_BASE_URL"] == env["R09_API_URL"] == origin
    assert env["R09_PRODUCTION_BUILD"] == "1"
    assert NO_CROSS_ORIGIN != origin and NO_CROSS_ORIGIN.endswith(".invalid")


@pytest.mark.parametrize("content,embedded", [
    (b'const API="http://127.0.0.1:8000";', True),
    (b'fetch("http://localhost:8000/api/v1")', True),
    (b'new WebSocket("ws://127.0.0.1:8000/ws/topology")', True),
    (b'const API="";const ws=location.origin.replace("http","ws")', False),
    (b'vite dev server http://127.0.0.1:5173', False),
])
def test_loopback_api_default_in_a_production_bundle_is_detected(tmp_path, content, embedded):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_bytes(b"<html></html>")
    (tmp_path / "assets/app.js").write_bytes(content)
    assert embedded_loopback_api(tmp_path) is embedded


def test_playwright_traces_are_recorded_only_when_failure_artifacts_are_requested():
    assert "--trace" not in playwright_argv(traces=False)
    argv = playwright_argv(traces=True)
    assert argv[argv.index("--trace") + 1] == "retain-on-failure"
    assert argv[-4:-2] == ["--config", "playwright.fullstack.config.ts"]


def render_real(tmp_path, port=43210):
    prefix, dist = tmp_path / "gateway", tmp_path / "dist"
    prefix.mkdir()
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>nanfo</title>")
    upstream = prefix / "nginx-upstream.conf"
    upstream.write_text("upstream nanfo_api { server 127.0.0.1:9; }\n")
    template = GATEWAY_TEMPLATE.read_text()
    return template, render_gateway_config(template, prefix=prefix, dist=dist, upstream=upstream, port=port), prefix


def test_real_gateway_config_keeps_every_production_rule_and_rewrites_only_host_bindings(tmp_path):
    template, rendered, prefix = render_real(tmp_path)
    assert re.findall(r"\blisten\s+[^;]+;", rendered) == ["listen 127.0.0.1:43210;"]
    assert f'include "{prefix / "nginx-upstream.conf"}";' in rendered
    # Host paths under /tmp (pytest tmp_path, the lane's /tmp/opencode root) stay intact.
    assert f"root {tmp_path / 'dist'};" in rendered
    assert f"pid {prefix}/nginx.pid;" in rendered
    for forbidden in ("/usr/share/nginx", "/dev/stdout", "/dev/stderr", "/etc/nginx/nginx-upstream.conf",
                      "pid /tmp/nginx.pid", "worker_processes auto"):
        assert forbidden not in rendered
    # Headers, CSP, proxy/WebSocket rules, locations and log format stay byte-for-byte production.
    kept = [line.strip() for line in template.splitlines()
            if re.match(r"\s*(add_header|location|proxy_|map|log_format|server_tokens|client_max_body_size)\b", line)]
    assert kept, "production gateway directives missing from deploy/nginx.conf"
    for line in kept:
        assert line in rendered, line


def test_gateway_rendering_fails_closed_on_unexpected_production_shape(tmp_path):
    template, _, prefix = render_real(tmp_path)
    options = dict(prefix=prefix, dist=tmp_path / "dist", upstream=prefix / "nginx-upstream.conf", port=1)
    cases = {
        "gateway_upstream_include_changed": template.replace("include /etc/nginx/nginx-upstream.conf;", ""),
        "gateway_listener_changed": template.replace("listen 8080;", "listen 8080;\n        listen 8080;"),
        "gateway_root_changed": template.replace("root /usr/share/nginx/html;", "root /srv/www;"),
        "gateway_unknown_include": template.replace("http {", "http {\n    include /etc/nginx/absent-extra.conf;"),
    }
    for code, broken in cases.items():
        with pytest.raises(AcceptanceFailure, match=code):
            render_gateway_config(broken, **options)


def test_gateway_includes_shipped_from_deploy_are_mapped_to_the_repository_copy(tmp_path):
    template, real, prefix = render_real(tmp_path)
    # Every /etc/nginx include the production template ships (headers, proxy rules, ...)
    # renders to the repository copy; the upstream include is the test upstream.
    shipped = sorted(set(re.findall(r"include\s+/etc/nginx/([\w.-]+);", template)) - {"mime.types", "nginx-upstream.conf"})
    assert shipped, "production gateway template ships no includes"
    for name in shipped:
        assert f'include "{GATEWAY_TEMPLATE.parent / name}";' in real
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    for name in shipped:
        shutil.copyfile(GATEWAY_TEMPLATE.parent / name, deploy / name)
    (deploy / "nanfo-extra.conf").write_text("# extra\n")
    rendered = render_gateway_config(template.replace("http {", "http {\n    include /etc/nginx/nanfo-extra.conf;"),
                                     prefix=prefix, dist=tmp_path / "dist", upstream=prefix / "nginx-upstream.conf",
                                     port=1, deploy=deploy)
    assert f'include "{deploy / "nanfo-extra.conf"}";' in rendered
    assert all(f'include "{deploy / name}";' in rendered for name in shipped)
    assert "include /etc/nginx/" not in rendered.replace("include /etc/nginx/mime.types;", "")
    assert "include /etc/nginx/mime.types;" in rendered


def test_rendered_production_gateway_passes_the_real_nginx_config_test(tmp_path):
    nginx = shutil.which("nginx")
    if nginx is None or not MIME_TYPES.is_file():
        pytest.skip("host nginx with /etc/nginx/mime.types required (installed in the production-browser lane)")
    _, rendered, prefix = render_real(tmp_path)
    config = prefix / "nginx.conf"
    config.write_text(rendered)
    result = subprocess.run([nginx, "-p", str(prefix), "-e", str(prefix / "error.log"), "-c", str(config), "-t"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_gateway_lane_refuses_to_start_without_host_nginx(tmp_path, monkeypatch, capsys):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("initdb", "postgres", "docker", "node"):
        tool = bin_dir / name
        tool.write_text("#!/bin/sh\nexit 0\n")
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    with pytest.raises(SystemExit) as raised:
        main(["--redis-image-id", "sha256:" + "a" * 64, "--neo4j-image-id", "sha256:" + "b" * 64,
              "--report", str(tmp_path / "report.json")])
    assert raised.value.code == 2
    assert "nginx" in capsys.readouterr().err
    assert not (tmp_path / "report.json").exists()


def test_new_failure_artifact_directory_is_required(tmp_path, capsys):
    existing = tmp_path / "exists"
    existing.mkdir()
    with pytest.raises(SystemExit):
        main(["--redis-image-id", "sha256:" + "a" * 64, "--neo4j-image-id", "sha256:" + "b" * 64,
              "--report", str(tmp_path / "report.json"), "--failure-artifacts", str(existing)])
    assert "failure artifacts must be a new directory" in capsys.readouterr().err


def playwright_junit(path, failures):
    cases = "".join(
        f'<testcase name="{name}" classname="regression.spec.ts" time="1">'
        f'<failure message="regression.spec.ts:1:1 {name}" type="FAILURE"><![CDATA[{body}]]></failure></testcase>'
        for name, body in failures)
    path.write_text(f'<testsuites><testsuite name="regression.spec.ts">{cases}'
                    '<testcase name="passes" classname="regression.spec.ts" time="1"/></testsuite></testsuites>')


def test_failed_cases_report_name_error_class_and_redacted_first_error_line(tmp_path):
    # Token-shaped values are generated at runtime: no credential-like literal lives in source.
    jwt = ".".join(base64.urlsafe_b64encode(part).rstrip(b"=").decode()
                   for part in (b'{"alg":"HS256","typ":"JWT"}', b'{"sub":"r09-owner"}', secrets.token_bytes(32)))
    token = secrets.token_urlsafe(32)
    uid = "3f1c2b4a-9d8e-4f7a-b6c5-d4e3f2a1b0c9"
    body = (f"  [production-chromium] › regression.spec.ts:10:5 › login\n\n"
            f"    TimeoutError: page.waitForResponse: Timeout 20000ms exceeded waiting for "
            f"http://127.0.0.1:43123/api/v1/auth/login?token={token} Bearer {jwt} user {uid} "
            f"r09-owner@example.com /tmp/opencode/nanfo-r09-abc/fixture.json {'a' * 64}\n"
            f"      at /home/runner/work/NANFO/frontend/tests/fullstack/support.ts:31:5")
    report = tmp_path / "browser.xml"
    playwright_junit(report, [("owner can sign in", body), ("plain failure", "expect(received).toBe(expected)")])
    counts, details = browser_results(report)
    assert counts == {"total": 3, "passed": 1, "failed": 2, "errors": 0, "skipped": 0}
    first, second = details
    assert first["case"] == "regression.spec.ts > owner can sign in"
    assert first["outcome"] == "failure" and first["error_class"] == "TimeoutError"
    line = first["first_error_line"]
    assert line.startswith("TimeoutError: page.waitForResponse: Timeout 20000ms exceeded")
    for secret in (jwt, token, uid, "r09-owner@example.com", "43123", "/tmp/opencode", "a" * 64):
        assert secret not in line
    for marker in ("<loopback>", "<redacted>", "<uuid>", "<email>", "<path>", "<hex>"):
        assert marker in line
    assert second["error_class"] == "FAILURE" and "expect(received)" in second["first_error_line"]
    assert "support.ts" not in json.dumps(details)


def test_failed_case_details_are_bounded(tmp_path):
    report = tmp_path / "browser.xml"
    playwright_junit(report, [(f"case {i}", f"Error: boom {i}") for i in range(MAX_FAILED_CASES + 5)])
    details = failed_case_details(report)
    assert len(details) == MAX_FAILED_CASES
    assert all(len(item["first_error_line"]) <= 240 for item in details)
    long_line = "word " * 100
    assert redact(long_line).endswith("...") and len(redact(long_line)) == 240
    # Colour codes from terminal-style messages never reach the report; opaque tokens collapse.
    assert redact("\x1b[31mError: failed\x1b[39m") == "Error: failed"
    assert redact("x" * 500) == "<opaque>"


def test_failure_artifacts_contain_only_regular_playwright_files(tmp_path):
    browser = tmp_path / "browser"
    (browser / "login-chromium").mkdir(parents=True)
    (browser / "login-chromium/trace.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    (browser / "login-chromium/test-failed-1.png").write_bytes(b"\x89PNG")
    secret = tmp_path / "fixture.json"
    secret.write_text('{"password": "never exported"}')
    (browser / "login-chromium/fixture-link.json").symlink_to(secret)
    destination = tmp_path / "artifacts"
    export_failure_artifacts(browser, destination)
    exported = sorted(p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file())
    assert exported == ["README.txt", "playwright/login-chromium/test-failed-1.png",
                        "playwright/login-chromium/trace.zip"]
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE((destination / "playwright/login-chromium/trace.zip").stat().st_mode) == 0o600
    assert "ephemeral" in (destination / "README.txt").read_text()
    with pytest.raises(FileExistsError):
        export_failure_artifacts(browser, destination)


def test_gateway_template_is_part_of_the_source_digest():
    source = Path(__file__).resolve().with_name("review_fullstack.py").read_text()
    assert "GATEWAY_TEMPLATE])" in source
