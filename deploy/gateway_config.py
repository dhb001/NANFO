"""Render the production gateway config for a host nginx binary (tests/CI only).

Host-only helper (never packaged into an image): copies the shipped includes into a
private prefix, renders the runtime includes with the real gateway entrypoint
(``--render``) and substitutes only host paths, the listener, the upstream servers and
the web root. Security headers, CSP, realip trust, proxy rules and logging stay the
production bytes; unknown shape changes fail instead of being guessed.
"""

import os
import re
import subprocess
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent
UPSTREAM_INCLUDE = "include /etc/nginx/nginx-upstream.conf;"
INCLUDE = re.compile(r"include\s+/etc/nginx/([\w.-]+);")


def render(prefix, *, listen, upstreams, html, trusted_hop="", mode="single", proxy_extra="",
           deploy=DEPLOY, mime_types="/etc/nginx/mime.types"):
    """Write ``prefix/nginx.conf``; returns its path. ``upstreams``: host:port strings."""
    prefix = Path(prefix)
    prefix.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                   "NANFO_GATEWAY_TRUSTED_HOP": trusted_hop, "NANFO_GATEWAY_UPSTREAM": mode}
    subprocess.run(["sh", str(deploy / "gateway-entrypoint.sh"), "--render", str(prefix / "nginx")],
                   env=environment, check=True, capture_output=True, timeout=10)
    template = (deploy / "nginx.conf").read_text()
    if template.count(UPSTREAM_INCLUDE) != 1:
        raise ValueError("gateway_upstream_include_changed")
    config = template.replace("/tmp/", f"{prefix}/")
    config = config.replace("/dev/stderr", str(prefix / "error.log")).replace("/dev/stdout", str(prefix / "access.log"))
    upstream = prefix / "upstream-test.conf"
    upstream.write_text("upstream nanfo_api {\n" + "".join(f"    server {value};\n" for value in upstreams) + "}\n")
    config = config.replace(UPSTREAM_INCLUDE, f'include "{upstream}";')
    for name in sorted(set(INCLUDE.findall(config))):
        if name == "mime.types":
            config = config.replace("include /etc/nginx/mime.types;", f'include "{mime_types}";')
            continue
        source = deploy / name
        if not source.is_file():
            raise ValueError("gateway_unknown_include")
        copy = prefix / name
        text = source.read_text()
        if name == "nginx-proxy.conf" and proxy_extra:
            text += proxy_extra.rstrip("\n") + "\n"
        copy.write_text(text)
        config = config.replace(f"include /etc/nginx/{name};", f'include "{copy}";')
    listeners = re.findall(r"\blisten\s+8080\b[^;]*;", config)
    if len(listeners) != 1 or config.count("/usr/share/nginx/html") != 1:
        raise ValueError("gateway_listener_or_root_changed")
    config = re.sub(r"\blisten\s+8080\b[^;]*;", f"listen {listen};", config)
    config = config.replace("/usr/share/nginx/html", str(html))
    if "/etc/nginx/" in config.replace(f'include "{mime_types}";', "") or "/dev/std" in config:
        raise ValueError("gateway_unrendered_path")
    path = prefix / "nginx.conf"
    path.write_text(config)
    return path
