"""Operator-only ADR-009 bootstrap using existing authenticated REST contracts.

Run with PYTHONPATH=..:. so the trusted, checked-in emulation topology is importable.
Passwords/tokens are never arguments, output artifacts, or log fields.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import tempfile
import uuid
from pathlib import Path

import httpx

from app.modules.network.emulation import EmulationBinding


async def bind_emulation(client: httpx.AsyncClient, *, email: str, password: str,
                         manifest: dict, org_slug: str, workspace_name: str,
                         network_name: str) -> EmulationBinding:
    async def request(method: str, path: str, **kwargs):
        response = await client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise ValueError(f"Binding API request failed (HTTP {response.status_code})")
        envelope = response.json()
        if envelope.get("success") is not True or not isinstance(envelope.get("data"), dict):
            raise ValueError("Invalid binding API response")
        return envelope["data"]

    def select(items, field, value):
        matches = [item for item in items if item[field] == value]
        if len(matches) > 1:
            raise ValueError("Ambiguous existing inventory; use a dedicated emulation scope")
        return matches[0] if matches else None

    async def pages(path, **params):
        items = []
        for page in range(1, 101):
            data = await request("GET", path, params={**params, "page": page, "page_size": 100})
            items.extend(data["items"])
            if len(items) >= data["total"]:
                return items
            if not data["items"]:
                break
        raise ValueError("Inventory pagination limit or inconsistent response")

    tokens = await request("POST", "/api/v1/auth/login", json={"email": email, "password": password})
    client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
    try:
        profile = await request("GET", "/api/v1/auth/me")
        if not {"write:config", "read:topology"}.issubset(profile["permissions"]):
            raise ValueError("Binding actor requires write:config and read:topology")
        orgs = await pages("/api/v1/organizations")
        org = select(orgs, "slug", org_slug)
        if org is None:
            org = await request("POST", "/api/v1/organizations", json={"name": org_slug, "slug": org_slug})
        workspaces_path = f"/api/v1/organizations/{uuid.UUID(org['org_id'])}/workspaces"
        workspaces = await pages(workspaces_path)
        workspace = select(workspaces, "name", workspace_name)
        if workspace is None:
            workspace = await request("POST", workspaces_path, json={"name": workspace_name})
        workspace_id = str(uuid.UUID(workspace["workspace_id"]))
        networks = await pages("/api/v1/networks", workspace_id=workspace_id)
        network = select(networks, "name", network_name)
        if network is None:
            network = await request("POST", "/api/v1/networks", json={
                "workspace_id": workspace_id, "name": network_name,
                "description": "Isolated emulation observations (ADR-009)",
            })
        network_id = str(uuid.UUID(network["network_id"]))
        if network["workspace_id"] != workspace_id:
            raise ValueError("API network scope mismatch")
        devices_path = f"/api/v1/networks/{network_id}/devices"
        devices = await pages(devices_path)
        switches, hosts = {}, {}
        for kind in ("switches", "hosts"):
            for node in manifest[kind]:
                device = select(devices, "hostname", node["name"])
                expected_type = "switch" if kind == "switches" else "lab_endpoint"
                if device is None:
                    device = await request("POST", devices_path, json={
                        "hostname": node["name"], "device_type": expected_type,
                        "ip_address": node.get("ipv4"),
                        "spatial_ref_id": f"emulation/{manifest['topology_id']}/{node['name']}",
                    })
                if (device["network_id"] != network_id or device["status"] != "active"
                        or device["device_type"] != expected_type
                        or device.get("ip_address") != node.get("ipv4")):
                    raise ValueError("Existing device does not match trusted topology")
                target = switches if kind == "switches" else hosts
                target[node["dpid"] if kind == "switches" else node["name"]] = device["device_id"]
        return EmulationBinding.model_validate_json(json.dumps({
            "version": 1, "topology_id": manifest["topology_id"],
            "network_id": network_id, "workspace_id": workspace_id,
            "actor_user_id": profile["user_id"], "switches": switches, "hosts": hosts,
            "port_capacities_mbps": manifest["port_capacities_mbps"],
        }))
    finally:
        try:
            await request("POST", "/api/v1/auth/logout")
        finally:
            client.headers.pop("Authorization", None)


def save_binding(binding: EmulationBinding, output: Path, snapshot_path: Path) -> None:
    if output.resolve().is_relative_to(snapshot_path.parent.resolve()):
        raise ValueError("Binding must be outside producer output directory")
    if output.is_symlink() or not output.parent.is_dir():
        raise ValueError("Binding requires an existing operator-owned directory")
    info = output.parent.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError("Binding directory must be operator owned and not group/world writable")
    fd, temporary = tempfile.mkstemp(prefix=".binding-", dir=output.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(binding.model_dump_json(indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--org-slug", default="nanfo-emulation")
    parser.add_argument("--workspace-name", default="Emulation")
    parser.add_argument("--network-name", default="campus-small-v1")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--snapshot-path", required=True, type=Path)
    args = parser.parse_args()
    url = httpx.URL(args.api_url)
    if url.username or url.password or url.query or url.fragment or (
        url.scheme != "https" and not (url.scheme == "http" and url.host in {"localhost", "127.0.0.1", "::1"})
    ):
        raise ValueError("Use HTTPS or loopback HTTP without URL credentials")
    from emulation.topology import manifest

    email = os.environ.get("NANFO_BIND_EMAIL") or input("Email: ")
    password = os.environ.get("NANFO_BIND_PASSWORD") or getpass.getpass("Password: ")
    async with httpx.AsyncClient(base_url=args.api_url, timeout=30, follow_redirects=False,
                                trust_env=False) as client:
        binding = await bind_emulation(client, email=email, password=password, manifest=manifest(),
                                       org_slug=args.org_slug, workspace_name=args.workspace_name,
                                       network_name=args.network_name)
    save_binding(binding, args.output, args.snapshot_path)
    print("Trusted binding saved. No credentials stored. Live ingestion not verified.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ValueError, OSError, httpx.HTTPError):
        raise SystemExit("Binding failed; verify credentials, API availability, inventory and operator paths.") from None
