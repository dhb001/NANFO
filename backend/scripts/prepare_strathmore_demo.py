"""Prepare a Strathmore demo dataset using existing NANFO API contracts only.

Run from ``backend/``:

    poetry run python scripts/prepare_strathmore_demo.py

Dry run is the default mode. Use ``--apply`` to execute API mutations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import httpx

from app.db.neo4j import close_neo4j, get_neo4j_driver, init_neo4j
from app.modules.network.synthetic_topology import (
    SYNTHETIC_TOPOLOGY_GENERATOR,
    PlannedDevice,
    SyntheticTopologyPlan,
    plan_synthetic_topology,
)
from app.modules.network.topology import TopologyQueryService

CAMPUS_CODE = "strathmore"

#: Provenance marker attached to every synthetic demo edge so the UI and any consumer
#: can state truthfully that this topology is generated, not discovered.
SYNTHETIC_DATASET_LABEL = "strathmore-demo"


@dataclass(frozen=True)
class DeviceCategorySpec:
    category: str
    hostname_prefix: str
    device_type: str
    zone: str
    location_label: str


@dataclass(frozen=True)
class FloorPlan:
    building_code: str
    building_name: str
    floor_code: str
    template_name: str


@dataclass(frozen=True)
class ExecutionContext:
    org_id: str
    workspace_id: str
    network_id: str
    created_device_ids: list[str]
    simulation_id: str | None
    intent_id: str | None


DEVICE_CATEGORY_ORDER = (
    "core_router",
    "firewall",
    "distribution_switch",
    "access_switch",
    "wifi_ap",
    "server",
    "ups_monitor",
    "security_gateway",
    "lab_endpoint",
)

DEVICE_CATEGORIES: dict[str, DeviceCategorySpec] = {
    "core_router": DeviceCategorySpec(
        category="core_router",
        hostname_prefix="rtr",
        device_type="router",
        zone="core",
        location_label="core routing",
    ),
    "firewall": DeviceCategorySpec(
        category="firewall",
        hostname_prefix="fw",
        device_type="firewall",
        zone="security",
        location_label="perimeter firewall",
    ),
    "distribution_switch": DeviceCategorySpec(
        category="distribution_switch",
        hostname_prefix="sw-dist",
        device_type="distribution_switch",
        zone="distribution",
        location_label="distribution switching",
    ),
    "access_switch": DeviceCategorySpec(
        category="access_switch",
        hostname_prefix="sw-acc",
        device_type="access_switch",
        zone="distribution",
        location_label="access switching",
    ),
    "wifi_ap": DeviceCategorySpec(
        category="wifi_ap",
        hostname_prefix="ap",
        device_type="wireless_ap",
        zone="wireless",
        location_label="wireless coverage",
    ),
    "server": DeviceCategorySpec(
        category="server",
        hostname_prefix="srv",
        device_type="server",
        zone="services",
        location_label="service workloads",
    ),
    "ups_monitor": DeviceCategorySpec(
        category="ups_monitor",
        hostname_prefix="ups",
        device_type="ups",
        zone="core",
        location_label="power and environment",
    ),
    "security_gateway": DeviceCategorySpec(
        category="security_gateway",
        hostname_prefix="sec",
        device_type="security_gateway",
        zone="security",
        location_label="cctv and access control",
    ),
    "lab_endpoint": DeviceCategorySpec(
        category="lab_endpoint",
        hostname_prefix="end",
        device_type="lab_endpoint",
        zone="lab",
        location_label="lab and endpoint services",
    ),
}

TEMPLATE_DEVICE_COUNTS: dict[str, dict[str, int]] = {
    # 23 devices
    "mdf_showcase": {
        "core_router": 1,
        "firewall": 1,
        "distribution_switch": 2,
        "access_switch": 4,
        "wifi_ap": 6,
        "server": 3,
        "ups_monitor": 2,
        "security_gateway": 2,
        "lab_endpoint": 2,
    },
    # 19 devices
    "academic_showcase": {
        "distribution_switch": 1,
        "access_switch": 4,
        "wifi_ap": 8,
        "server": 1,
        "ups_monitor": 1,
        "security_gateway": 2,
        "lab_endpoint": 2,
    },
    # 11 devices
    "standard_core": {
        "distribution_switch": 1,
        "access_switch": 2,
        "wifi_ap": 4,
        "server": 1,
        "ups_monitor": 1,
        "security_gateway": 1,
        "lab_endpoint": 1,
    },
    # 6 devices
    "light_placeholder": {
        "access_switch": 1,
        "wifi_ap": 3,
        "ups_monitor": 1,
        "lab_endpoint": 1,
    },
}

BUILDING_NAMES: dict[str, str] = {
    "sbs": "Strathmore Business School",
    "lib": "Main Library",
    "msb": "Management Sciences Building",
    "ssc": "Strathmore Student Center",
    "bld-e": "Building E",
    "bld-f": "Building F",
    "bld-g": "Building G",
}

BUILDING_ORDER = ("sbs", "lib", "msb", "ssc", "bld-e", "bld-f", "bld-g")

BUILDING_TEMPLATE_LAYOUT: dict[str, tuple[str, ...]] = {
    # 86 devices each
    "sbs": (
        "mdf_showcase",
        "academic_showcase",
        "standard_core",
        "standard_core",
        "standard_core",
        "standard_core",
    ),
    "lib": (
        "mdf_showcase",
        "academic_showcase",
        "standard_core",
        "standard_core",
        "standard_core",
        "standard_core",
    ),
    # 71 devices
    "msb": (
        "academic_showcase",
        "academic_showcase",
        "standard_core",
        "standard_core",
        "standard_core",
    ),
    # 60 devices
    "ssc": (
        "academic_showcase",
        "academic_showcase",
        "standard_core",
        "standard_core",
    ),
    # 12 devices each
    "bld-e": ("light_placeholder", "light_placeholder"),
    "bld-f": ("light_placeholder", "light_placeholder"),
    "bld-g": ("light_placeholder", "light_placeholder"),
}

BUILDING_DEVICE_TARGETS: dict[str, int] = {
    "sbs": 86,
    "lib": 86,
    "msb": 71,
    "ssc": 60,
    "bld-e": 12,
    "bld-f": 12,
    "bld-g": 12,
}


class NanfoApiError(RuntimeError):
    """Raised when a NANFO API request fails contract or status checks."""


def build_strathmore_floor_plan() -> list[FloorPlan]:
    """Return deterministic campus floor plan for Strathmore demo execution."""
    floor_plan: list[FloorPlan] = []
    for building_code in BUILDING_ORDER:
        building_name = BUILDING_NAMES[building_code]
        templates = BUILDING_TEMPLATE_LAYOUT[building_code]
        for floor_index, template_name in enumerate(templates, start=1):
            floor_plan.append(
                FloorPlan(
                    building_code=building_code,
                    building_name=building_name,
                    floor_code=f"f{floor_index:02d}",
                    template_name=template_name,
                )
            )
    return floor_plan


def build_strathmore_device_payloads(max_devices: int | None = None) -> list[dict[str, Any]]:
    """Build deterministic device payloads for ``POST /api/v1/networks/{id}/devices``."""
    if max_devices is not None and max_devices < 1:
        raise ValueError("max_devices must be >= 1 when provided.")

    payloads: list[dict[str, Any]] = []
    for floor in build_strathmore_floor_plan():
        template_counts = TEMPLATE_DEVICE_COUNTS[floor.template_name]
        for category in DEVICE_CATEGORY_ORDER:
            count = template_counts.get(category, 0)
            if count < 1:
                continue

            category_spec = DEVICE_CATEGORIES[category]
            for ordinal in range(1, count + 1):
                hostname = (
                    f"{category_spec.hostname_prefix}-{floor.building_code}-"
                    f"{floor.floor_code}-{ordinal:02d}"
                )
                spatial_ref_id = (
                    f"{CAMPUS_CODE}/{floor.building_code}/{floor.floor_code}/"
                    f"{category_spec.zone}/{hostname}"
                )
                location_hint = (
                    f"{floor.building_name} {floor.floor_code.upper()} "
                    f"{category_spec.location_label}"
                )
                payloads.append(
                    {
                        "hostname": hostname,
                        "device_type": category_spec.device_type,
                        "vendor": "NANFO",
                        "model": "STRATHMORE-DEMO",
                        "location_hint": location_hint,
                        "spatial_ref_id": spatial_ref_id,
                    }
                )

                if max_devices is not None and len(payloads) >= max_devices:
                    return payloads

    return payloads


def build_dataset_summary(device_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Return deterministic summary useful for evidence and manual validation."""
    by_building: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    floors_by_building: dict[str, set[str]] = {}

    for payload in device_payloads:
        device_type = str(payload.get("device_type", ""))
        if device_type:
            by_type[device_type] += 1

        spatial_ref = str(payload.get("spatial_ref_id", ""))
        parts = spatial_ref.split("/") if spatial_ref else []
        if len(parts) >= 3:
            building = parts[1]
            floor = parts[2]
            by_building[building] += 1
            floors_by_building.setdefault(building, set()).add(floor)

    return {
        "total_devices": len(device_payloads),
        "devices_by_building": dict(sorted(by_building.items())),
        "devices_by_type": dict(sorted(by_type.items())),
        "floors_by_building": {
            key: len(value)
            for key, value in sorted(floors_by_building.items())
        },
    }


def build_planned_devices_from_graph(graph_nodes: list[dict[str, Any]]) -> list[PlannedDevice]:
    """Project ``GET /api/v1/topology/graph`` nodes onto the topology planner input.

    Pure and defensive: rows missing a ``device_id`` are dropped rather than guessed.
    """
    planned: list[PlannedDevice] = []
    for node in graph_nodes:
        if not isinstance(node, dict):
            continue
        device_id = str(node.get("device_id") or "").strip()
        if not device_id:
            continue

        spatial_ref_raw = node.get("spatial_ref_id")
        spatial_ref_id = spatial_ref_raw.strip() if isinstance(spatial_ref_raw, str) else None

        planned.append(
            PlannedDevice(
                device_id=device_id,
                hostname=str(node.get("hostname") or "").strip(),
                device_type=str(node.get("device_type") or "").strip(),
                spatial_ref_id=spatial_ref_id or None,
            )
        )
    return planned


def build_synthetic_topology_plan(graph_nodes: list[dict[str, Any]]) -> SyntheticTopologyPlan:
    """Plan the deterministic synthetic demo topology for the Strathmore dataset.

    The resulting edges are explicitly labelled ``synthetic=True`` with a
    ``dataset=strathmore-demo`` marker. They represent a plausible campus hierarchy for
    demonstration purposes and are NOT discovered Strathmore University infrastructure.
    """
    return plan_synthetic_topology(
        build_planned_devices_from_graph(graph_nodes),
        dataset_label=SYNTHETIC_DATASET_LABEL,
    )


async def _write_synthetic_topology_edges(
    *,
    network_id: str,
    workspace_id: str,
    plan: SyntheticTopologyPlan,
) -> tuple[int, int]:
    """Persist planned edges into Neo4j using the Network module's own writer.

    Uses replace semantics so re-running the seed converges on exactly the planned
    edge set instead of accumulating stale uplinks from earlier partial runs.
    """
    await init_neo4j()
    try:
        service = TopologyQueryService(driver=get_neo4j_driver())
        return await service.replace_synthetic_device_edges(
            network_id=network_id,
            workspace_id=workspace_id,
            edges=plan.edges,
            generator=SYNTHETIC_TOPOLOGY_GENERATOR,
        )
    finally:
        await close_neo4j()


def materialize_synthetic_topology_edges(
    *,
    network_id: str,
    workspace_id: str,
    plan: SyntheticTopologyPlan,
) -> tuple[int, int]:
    """Blocking wrapper so the synchronous seed flow can write topology edges.

    Returns ``(deleted, written)``.
    """
    if not plan.edges:
        return (0, 0)
    return asyncio.run(
        _write_synthetic_topology_edges(
            network_id=network_id,
            workspace_id=workspace_id,
            plan=plan,
        )
    )


def _await_topology_projection(
    *,
    api: NanfoApiClient,
    network_id: str,
    expected_nodes: int,
    graph_limit: int,
    timeout_seconds: float,
    poll_interval_seconds: float = 1.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Poll the topology graph until Neo4j has caught up with device creation.

    Device writes are projected into Neo4j asynchronously by the topology consumer
    (documented eventual-consistency behaviour, design_package risk R5). Planning
    topology from a partially-projected graph would silently leave the missing devices
    without an uplink, so wait for the projection to settle first.

    Returns the last observed ``(nodes, edges)`` even if the timeout is reached, so the
    caller can proceed on a best-effort basis with an explicit warning.
    """
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    attempt = 0

    while True:
        attempt += 1
        graph = api.get_topology_graph(network_id=network_id, limit=graph_limit)
        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []

        if len(nodes) >= expected_nodes:
            if attempt > 1:
                print(
                    f"[strathmore] topology projection settled after {attempt} polls: "
                    f"nodes={len(nodes)}"
                )
            return nodes, edges

        if time.monotonic() >= deadline:
            print(
                "[strathmore] WARNING: topology projection incomplete after "
                f"{timeout_seconds:.0f}s (nodes={len(nodes)} expected={expected_nodes}). "
                "Proceeding; devices missing from Neo4j will not receive an uplink."
            )
            return nodes, edges

        print(
            f"[strathmore] waiting for topology projection: "
            f"nodes={len(nodes)}/{expected_nodes}"
        )
        time.sleep(poll_interval_seconds)


def build_group_scope_intent_request(workspace_id: str, network_id: str) -> dict[str, Any]:
    """Build contract-safe group scope payload for intent validate/execute flow."""
    return {
        "workspace_id": workspace_id,
        "network_id": network_id,
        "intent": {
            "action": "optimize_wireless_capacity",
            "scope": {
                "target": "group",
                "site_prefix": "strathmore/ssc/f02",
                "functional_group": "wireless",
                "operational_group": "student_services",
            },
            "constraints": {
                "max_downtime": 0,
                "simulation_required": True,
            },
        },
    }


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def _json_dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _stable_error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return f"status={response.status_code} body={body}"


class NanfoApiClient:
    """Small envelope-aware client for existing NANFO endpoints only."""

    def __init__(self, *, base_url: str, timeout_seconds: float = 20.0):
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds)
        self._access_token: str | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _request_envelope(
        self,
        *,
        method: str,
        path: str,
        expected_statuses: tuple[int, ...],
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        response = self._client.request(
            method,
            path,
            json=json_body,
            params=params,
            headers=self._headers(idempotency_key=idempotency_key),
        )

        if response.status_code not in expected_statuses:
            raise NanfoApiError(
                f"{method} {path} expected {expected_statuses}, "
                f"got {_stable_error_text(response)}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise NanfoApiError(f"{method} {path} did not return JSON.") from exc

        if not isinstance(payload, dict):
            raise NanfoApiError(f"{method} {path} returned non-object payload.")

        missing = [key for key in ("success", "data", "meta", "errors") if key not in payload]
        if missing:
            raise NanfoApiError(
                f"{method} {path} missing envelope keys: {', '.join(missing)}"
            )

        if payload.get("success") is not True:
            raise NanfoApiError(
                f"{method} {path} returned success=false errors={payload.get('errors')}"
            )

        data = payload.get("data")
        if not isinstance(data, dict):
            raise NanfoApiError(f"{method} {path} returned non-object data payload.")
        return data

    def login(self, *, email: str, password: str) -> dict[str, Any]:
        data = self._request_envelope(
            method="POST",
            path="/api/v1/auth/login",
            expected_statuses=(200,),
            json_body={"email": email, "password": password},
        )
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise NanfoApiError("login response missing access_token")
        self._access_token = access_token
        return data

    def get_profile(self) -> dict[str, Any]:
        return self._request_envelope(
            method="GET",
            path="/api/v1/auth/me",
            expected_statuses=(200,),
        )

    def create_org(self, *, name: str, slug: str) -> dict[str, Any]:
        return self._request_envelope(
            method="POST",
            path="/api/v1/organizations",
            expected_statuses=(201,),
            json_body={"name": name, "slug": slug},
        )

    def add_org_member(self, *, org_id: str, user_id: str, org_role: str) -> dict[str, Any] | None:
        """Ensure the actor is an org member.

        The org creator is already promoted to a member by
        ``POST /api/v1/organizations``, so a follow-up add legitimately returns 409
        CONFLICT. Treat that as success so the seed flow stays idempotent and can be
        re-run without manual cleanup.
        """
        response = self._client.request(
            "POST",
            f"/api/v1/organizations/{org_id}/members",
            json={"user_id": user_id, "org_role": org_role},
            headers=self._headers(),
        )

        if response.status_code == 409:
            print("[strathmore] org membership already present; continuing")
            return None

        if response.status_code != 201:
            raise NanfoApiError(
                f"POST /api/v1/organizations/{org_id}/members expected (201, 409), "
                f"got {_stable_error_text(response)}"
            )

        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None

    def create_workspace(self, *, org_id: str, name: str, description: str | None) -> dict[str, Any]:
        return self._request_envelope(
            method="POST",
            path=f"/api/v1/organizations/{org_id}/workspaces",
            expected_statuses=(201,),
            json_body={"name": name, "description": description},
        )

    def create_network(
        self,
        *,
        workspace_id: str,
        name: str,
        description: str | None,
        cidr: str | None,
    ) -> dict[str, Any]:
        return self._request_envelope(
            method="POST",
            path="/api/v1/networks",
            expected_statuses=(201,),
            json_body={
                "workspace_id": workspace_id,
                "name": name,
                "description": description,
                "cidr": cidr,
            },
        )

    def create_device(self, *, network_id: str, device_payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_envelope(
            method="POST",
            path=f"/api/v1/networks/{network_id}/devices",
            expected_statuses=(201,),
            json_body=device_payload,
        )

    def list_devices(self, *, network_id: str, page: int, page_size: int) -> dict[str, Any]:
        return self._request_envelope(
            method="GET",
            path=f"/api/v1/networks/{network_id}/devices",
            expected_statuses=(200,),
            params={"page": page, "page_size": page_size},
        )

    def list_all_devices(self, *, network_id: str, page_size: int = 200) -> list[dict[str, Any]]:
        page = 1
        collected: list[dict[str, Any]] = []
        total = None
        while True:
            page_data = self.list_devices(network_id=network_id, page=page, page_size=page_size)
            items = page_data.get("items")
            if not isinstance(items, list):
                raise NanfoApiError("list devices response missing items list")
            collected.extend(item for item in items if isinstance(item, dict))

            if total is None:
                raw_total = page_data.get("total")
                if not isinstance(raw_total, int):
                    raise NanfoApiError("list devices response missing integer total")
                total = raw_total

            if len(collected) >= total or not items:
                return collected

            page += 1

    def get_topology_graph(self, *, network_id: str, limit: int = 500) -> dict[str, Any]:
        return self._request_envelope(
            method="GET",
            path="/api/v1/topology/graph",
            expected_statuses=(200,),
            params={"network_id": network_id, "depth": 2, "limit": limit},
        )

    def start_simulation(self, *, network_id: str, scenario_name: str) -> dict[str, Any]:
        return self._request_envelope(
            method="POST",
            path="/api/v1/simulations/start",
            expected_statuses=(202,),
            json_body={
                "network_id": network_id,
                "scenario_name": scenario_name,
                "validation_checks": ["simulation_before_deployment"],
            },
        )

    def get_simulation_detail(self, *, simulation_id: str) -> dict[str, Any]:
        return self._request_envelope(
            method="GET",
            path=f"/api/v1/simulations/{simulation_id}",
            expected_statuses=(200,),
        )

    def validate_intent(
        self,
        *,
        workspace_id: str,
        network_id: str,
        intent_payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request_envelope(
            method="POST",
            path="/api/v1/intents/validate",
            expected_statuses=(200,),
            json_body={
                "workspace_id": workspace_id,
                "network_id": network_id,
                "intent": intent_payload,
            },
            idempotency_key=idempotency_key,
        )

    def execute_intent(self, *, workspace_id: str, intent_id: str, idempotency_key: str) -> dict[str, Any]:
        return self._request_envelope(
            method="POST",
            path="/api/v1/intents/execute",
            expected_statuses=(202,),
            json_body={
                "workspace_id": workspace_id,
                "intent_id": intent_id,
                "idempotency_key": idempotency_key,
            },
            idempotency_key=idempotency_key,
        )

    def get_intent_detail(self, *, workspace_id: str, intent_id: str) -> dict[str, Any]:
        return self._request_envelope(
            method="GET",
            path=f"/api/v1/intents/{intent_id}",
            expected_statuses=(200,),
            params={"workspace_id": workspace_id},
        )

    def get_telemetry_health(self) -> dict[str, Any]:
        return self._request_envelope(
            method="GET",
            path="/api/v1/telemetry/health",
            expected_statuses=(200,),
        )

    def list_alerts(self) -> dict[str, Any]:
        return self._request_envelope(
            method="GET",
            path="/api/v1/alerts",
            expected_statuses=(200,),
        )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dump(payload), encoding="utf-8")


def _print_dataset_summary(summary: dict[str, Any]) -> None:
    print("[strathmore] dataset summary")
    print(f"  total_devices: {summary['total_devices']}")
    print(f"  devices_by_building: {summary['devices_by_building']}")
    print(f"  devices_by_type: {summary['devices_by_type']}")


def _run_apply_mode(args: argparse.Namespace, device_payloads: list[dict[str, Any]]) -> ExecutionContext:
    org_slug = args.org_slug.strip() if args.org_slug else f"strathmore-university-{_now_stamp()}"
    with NanfoApiClient(base_url=args.base_url, timeout_seconds=args.timeout_seconds) as api:
        api.login(email=args.email, password=args.password)
        profile = api.get_profile()

        user_id = profile.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            raise NanfoApiError("profile response missing user_id")

        org = api.create_org(name=args.org_name, slug=org_slug)
        org_id = str(org.get("org_id"))
        api.add_org_member(org_id=org_id, user_id=user_id, org_role="Admin")

        workspace = api.create_workspace(
            org_id=org_id,
            name=args.workspace_name,
            description=args.workspace_description,
        )
        workspace_id = str(workspace.get("workspace_id"))

        network = api.create_network(
            workspace_id=workspace_id,
            name=args.network_name,
            description=args.network_description,
            cidr=args.network_cidr,
        )
        network_id = str(network.get("network_id"))

        created_device_ids: list[str] = []
        for index, payload in enumerate(device_payloads, start=1):
            created = api.create_device(network_id=network_id, device_payload=payload)
            created_device_ids.append(str(created.get("device_id")))
            if index % args.progress_every == 0 or index == len(device_payloads):
                print(f"[strathmore] created devices: {index}/{len(device_payloads)}")

        listed_devices = api.list_all_devices(network_id=network_id, page_size=args.list_page_size)
        print(
            "[strathmore] list-devices verification: "
            f"expected>={len(device_payloads)} actual={len(listed_devices)}"
        )

        graph_nodes, graph_edges = _await_topology_projection(
            api=api,
            network_id=network_id,
            expected_nodes=len(device_payloads),
            graph_limit=min(max(len(device_payloads), 1), 500),
            timeout_seconds=args.topology_sync_timeout_seconds,
        )
        print(
            "[strathmore] topology graph snapshot: "
            f"nodes={len(graph_nodes)} edges={len(graph_edges)}"
        )

        if args.seed_topology_edges:
            plan = build_synthetic_topology_plan(graph_nodes)
            print(
                "[strathmore] synthetic topology plan (DEMO DATA, not discovered "
                f"infrastructure): planned_edges={plan.edge_count} stats={plan.stats}"
            )
            for warning in plan.warnings[:10]:
                print(f"[strathmore]   plan warning: {warning}")

            deleted_edges, written_edges = materialize_synthetic_topology_edges(
                network_id=network_id,
                workspace_id=workspace_id,
                plan=plan,
            )
            print(
                "[strathmore] synthetic topology edges: "
                f"pruned_stale={deleted_edges} written={written_edges}"
            )

            verify_graph = api.get_topology_graph(
                network_id=network_id,
                limit=min(max(len(device_payloads), 1), 500),
            )
            verify_edges = verify_graph.get("edges") if isinstance(verify_graph.get("edges"), list) else []
            print(f"[strathmore] topology graph re-check: edges={len(verify_edges)}")

        telemetry_health = api.get_telemetry_health()
        alerts_list = api.list_alerts()
        telemetry_keys = sorted(telemetry_health.keys())
        alert_total = alerts_list.get("total") if isinstance(alerts_list.get("total"), int) else "unknown"
        print(
            "[strathmore] observability check: "
            f"telemetry_keys={telemetry_keys} alerts_total={alert_total}"
        )

        simulation_id = None
        intent_id = None
        if args.run_control_plane_check:
            simulation = api.start_simulation(
                network_id=network_id,
                scenario_name=args.simulation_scenario_name,
            )
            simulation_id = str(simulation.get("simulation_id"))
            if simulation_id:
                api.get_simulation_detail(simulation_id=simulation_id)

            scope_request = build_group_scope_intent_request(
                workspace_id=workspace_id,
                network_id=network_id,
            )
            validate_idempotency_key = f"{args.idempotency_prefix}-validate-{_now_stamp()}"
            validated = api.validate_intent(
                workspace_id=workspace_id,
                network_id=network_id,
                intent_payload=scope_request["intent"],
                idempotency_key=validate_idempotency_key,
            )
            intent_id = str(validated.get("intent_id"))
            if intent_id:
                execute_idempotency_key = f"{args.idempotency_prefix}-execute-{_now_stamp()}"
                api.execute_intent(
                    workspace_id=workspace_id,
                    intent_id=intent_id,
                    idempotency_key=execute_idempotency_key,
                )
                api.get_intent_detail(workspace_id=workspace_id, intent_id=intent_id)

        return ExecutionContext(
            org_id=org_id,
            workspace_id=workspace_id,
            network_id=network_id,
            created_device_ids=created_device_ids,
            simulation_id=simulation_id,
            intent_id=intent_id,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare Strathmore demo dataset with existing NANFO API contracts"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("NANFO_BASE_URL", "http://127.0.0.1:8000"),
        help="Backend base URL",
    )
    parser.add_argument(
        "--email",
        default=os.getenv("NANFO_BOOTSTRAP_EMAIL", "admin@example.com"),
        help="Login email",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("NANFO_BOOTSTRAP_PASSWORD", "admin123"),
        help="Login password",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute API writes. Omit this flag for dry-run mode.",
    )
    parser.add_argument(
        "--max-devices",
        type=int,
        default=0,
        help="Optional cap for smoke runs (0 means full 339-device dataset).",
    )
    parser.add_argument(
        "--org-name",
        default="Strathmore University",
        help="Organization display name",
    )
    parser.add_argument(
        "--org-slug",
        default="",
        help="Organization slug. If omitted, script generates a unique slug.",
    )
    parser.add_argument(
        "--workspace-name",
        default="Main Campus Operations",
        help="Workspace display name",
    )
    parser.add_argument(
        "--workspace-description",
        default="Centralized campus operations workspace for Strathmore demo",
        help="Workspace description",
    )
    parser.add_argument(
        "--network-name",
        default="strathmore-main-campus",
        help="Network name",
    )
    parser.add_argument(
        "--network-description",
        default="Single-campus control plane context for Strathmore demo",
        help="Network description",
    )
    parser.add_argument(
        "--network-cidr",
        default="10.42.0.0/16",
        help="Network CIDR",
    )
    parser.add_argument(
        "--output-path",
        default="",
        help="Optional JSON path for execution context and summary",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Progress log interval while creating devices",
    )
    parser.add_argument(
        "--list-page-size",
        type=int,
        default=200,
        help="Page size used for list-devices verification",
    )
    parser.add_argument(
        "--run-control-plane-check",
        action="store_true",
        help="Also run one simulation start and one intent validate/execute flow.",
    )
    parser.add_argument(
        "--seed-topology-edges",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Materialize the deterministic SYNTHETIC demo topology hierarchy "
            "(firewall -> core -> distribution -> access -> leaf) as Neo4j "
            "CONNECTED_TO edges. Requires direct Neo4j access. Use "
            "--no-seed-topology-edges to create devices only."
        ),
    )
    parser.add_argument(
        "--topology-sync-timeout-seconds",
        type=float,
        default=90.0,
        help=(
            "Maximum time to wait for Neo4j to finish projecting created devices "
            "before planning synthetic topology edges."
        ),
    )
    parser.add_argument(
        "--simulation-scenario-name",
        default="Strathmore campus baseline simulation",
        help="Scenario name used for --run-control-plane-check",
    )
    parser.add_argument(
        "--idempotency-prefix",
        default="strathmore-demo",
        help="Idempotency key prefix for control-plane checks",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    max_devices = args.max_devices if args.max_devices > 0 else None
    device_payloads = build_strathmore_device_payloads(max_devices=max_devices)
    summary = build_dataset_summary(device_payloads)
    _print_dataset_summary(summary)

    context: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "dataset_summary": summary,
        "sample_payloads": device_payloads[:3],
    }

    if not args.apply:
        print("[strathmore] dry run complete (no API writes).")
        if args.output_path:
            output_path = Path(args.output_path)
            _write_json(output_path, context)
            print(f"[strathmore] wrote dry-run summary to {output_path}")
        return 0

    try:
        execution = _run_apply_mode(args, device_payloads)
    except NanfoApiError as exc:
        print(f"[strathmore] failed: {exc}")
        return 1

    context["execution"] = {
        "org_id": execution.org_id,
        "workspace_id": execution.workspace_id,
        "network_id": execution.network_id,
        "created_device_count": len(execution.created_device_ids),
        "simulation_id": execution.simulation_id,
        "intent_id": execution.intent_id,
    }

    print("[strathmore] apply mode completed successfully.")
    print(
        "[strathmore] created context: "
        f"org_id={execution.org_id} workspace_id={execution.workspace_id} "
        f"network_id={execution.network_id} device_count={len(execution.created_device_ids)}"
    )

    if args.output_path:
        output_path = Path(args.output_path)
        _write_json(output_path, context)
        print(f"[strathmore] wrote execution context to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
