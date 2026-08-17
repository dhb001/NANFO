"""Run a detailed local NANFO flow check and print actionable diagnostics.

This script validates the common developer flow end-to-end:
1) health + CORS preflight
2) login + profile
3) organization/workspace/member/network/device lifecycle baseline
4) telemetry + alerts read paths
5) websocket subscription handshake checks

Run from backend/:
    poetry run python scripts/run_local_flow_check.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import websockets

CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class FlowCheckError(RuntimeError):
    """Raised when a flow step fails validation."""


@dataclass
class StepResult:
    name: str
    status: str
    detail: str


@dataclass
class FlowState:
    user_id: str | None = None
    org_id: str | None = None
    workspace_id: str | None = None
    network_id: str | None = None
    device_id: str | None = None


def _now_suffix() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def _json_or_none(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _short_response_details(response: httpx.Response) -> str:
    payload = _json_or_none(response)
    if payload is not None:
        if isinstance(payload.get("errors"), dict):
            return f"status={response.status_code} errors={json.dumps(payload['errors'], ensure_ascii=True)}"
        return f"status={response.status_code} body={json.dumps(payload, ensure_ascii=True)}"
    text = response.text.strip().replace("\n", " ")
    return f"status={response.status_code} body={text[:300]}"


def _require_envelope(payload: dict[str, Any], *, step: str) -> None:
    missing = [key for key in ("success", "data", "meta", "errors") if key not in payload]
    if missing:
        raise FlowCheckError(f"{step}: response missing envelope keys: {', '.join(missing)}")


class LocalFlowChecker:
    def __init__(self, args: argparse.Namespace):
        self._base_url: str = args.base_url.rstrip("/")
        self._ws_base_url: str = args.ws_base_url.rstrip("/")
        self._email: str = args.email
        self._password: str = args.password
        self._timeout_seconds: float = max(args.timeout_seconds, 1.0)
        self._report_path: Path | None = Path(args.report_path) if args.report_path else None
        self._access_token: str | None = None
        self._results: list[StepResult] = []
        self._state = FlowState()

    def run(self) -> int:
        with httpx.Client(base_url=self._base_url, timeout=self._timeout_seconds) as client:
            self._run_http_flow(client)

        if self._access_token and self._state.network_id:
            self._run_step("ws-alerts-subscribe", self._check_ws_alerts)
            self._run_step("ws-topology-subscribe", self._check_ws_topology)
            self._run_step("ws-telemetry-subscribe", self._check_ws_telemetry)
            self._run_step("ws-digital-twin-subscribe", self._check_ws_digital_twin)
        else:
            self._skip_step(
                "ws-handshake-suite",
                "Skipped because login/network prerequisites did not complete.",
            )

        self._print_summary()
        self._write_report_if_needed()

        has_failures = any(result.status == "FAIL" for result in self._results)
        return 1 if has_failures else 0

    def _run_http_flow(self, client: httpx.Client) -> None:
        self._run_step("health", lambda: self._check_health(client))
        self._run_step(
            "cors-preflight-localhost",
            lambda: self._check_preflight(client, origin="http://localhost:5173"),
        )
        self._run_step(
            "cors-preflight-127001",
            lambda: self._check_preflight(client, origin="http://127.0.0.1:5173"),
        )

        login_ok = self._run_step("auth-login", lambda: self._check_login(client))
        if not login_ok:
            self._skip_remaining_after_auth_failure()
            return

        self._run_step("auth-me", lambda: self._check_profile(client))
        self._run_step("organizations-validation-422", lambda: self._check_org_validation_shape(client))
        self._run_step("organizations-create", lambda: self._create_org(client))
        self._run_step("organizations-add-self-member", lambda: self._add_self_member(client))
        self._run_step("organizations-list", lambda: self._list_orgs(client))
        self._run_step("workspaces-create", lambda: self._create_workspace(client))
        self._run_step("workspaces-list", lambda: self._list_workspaces(client))
        self._run_step("networks-create", lambda: self._create_network(client))
        self._run_step("networks-list", lambda: self._list_networks(client))
        self._run_step("devices-create", lambda: self._create_device(client))
        self._run_step("devices-list", lambda: self._list_devices(client))
        self._run_step("telemetry-health", lambda: self._check_telemetry_health(client))
        self._run_step("alerts-list", lambda: self._check_alerts_list(client))

    def _skip_remaining_after_auth_failure(self) -> None:
        for step in (
            "auth-me",
            "organizations-validation-422",
            "organizations-create",
            "organizations-add-self-member",
            "organizations-list",
            "workspaces-create",
            "workspaces-list",
            "networks-create",
            "networks-list",
            "devices-create",
            "devices-list",
            "telemetry-health",
            "alerts-list",
        ):
            self._skip_step(step, "Skipped because login failed.")

    def _run_step(self, name: str, fn) -> bool:
        try:
            detail = fn()
            detail_text = str(detail) if detail is not None else "ok"
            self._results.append(StepResult(name=name, status="PASS", detail=detail_text))
            print(f"[PASS] {name}: {detail_text}")
            return True
        except Exception as exc:  # noqa: BLE001
            detail_text = f"{type(exc).__name__}: {exc}"
            self._results.append(StepResult(name=name, status="FAIL", detail=detail_text))
            print(f"[FAIL] {name}: {detail_text}")
            return False

    def _skip_step(self, name: str, reason: str) -> None:
        self._results.append(StepResult(name=name, status="SKIP", detail=reason))
        print(f"[SKIP] {name}: {reason}")

    def _auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            raise FlowCheckError("Access token is not available.")
        return {"Authorization": f"Bearer {self._access_token}"}

    def _check_health(self, client: httpx.Client) -> str:
        response = client.get("/health")
        if response.status_code != 200:
            raise FlowCheckError(_short_response_details(response))
        payload = _json_or_none(response)
        if payload is None or payload.get("status") != "ok":
            raise FlowCheckError("Health endpoint did not return {status: ok}.")
        return "GET /health -> 200 ok"

    def _check_preflight(self, client: httpx.Client, *, origin: str) -> str:
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        if response.status_code != 200:
            raise FlowCheckError(_short_response_details(response))
        allowed_origin = response.headers.get("access-control-allow-origin")
        if allowed_origin != origin:
            raise FlowCheckError(
                f"Expected access-control-allow-origin={origin}, got {allowed_origin!r}",
            )
        allow_methods = response.headers.get("access-control-allow-methods", "")
        if "POST" not in allow_methods:
            raise FlowCheckError(f"CORS allow methods missing POST: {allow_methods!r}")
        return f"OPTIONS /api/v1/auth/login allows {origin}"

    def _check_login(self, client: httpx.Client) -> str:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": self._email, "password": self._password},
        )
        if response.status_code != 200:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Login response is not valid JSON.")
        _require_envelope(payload, step="login")
        if payload.get("success") is not True:
            raise FlowCheckError(f"Login returned success={payload.get('success')!r}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise FlowCheckError("Login response data is missing.")

        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise FlowCheckError("Login tokens are missing from response.")

        self._access_token = access_token
        return "POST /api/v1/auth/login -> 200 and token pair returned"

    def _check_profile(self, client: httpx.Client) -> str:
        response = client.get("/api/v1/auth/me", headers=self._auth_headers())
        if response.status_code != 200:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Profile response is not valid JSON.")
        _require_envelope(payload, step="auth-me")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise FlowCheckError("Profile data is missing.")

        user_id = data.get("user_id")
        if not isinstance(user_id, str):
            raise FlowCheckError("Profile user_id is missing.")

        self._state.user_id = user_id
        roles = data.get("roles")
        return f"GET /api/v1/auth/me -> user_id={user_id} roles={roles}"

    def _check_org_validation_shape(self, client: httpx.Client) -> str:
        response = client.post(
            "/api/v1/organizations",
            headers=self._auth_headers(),
            json={"name": "x", "slug": "x"},
        )
        if response.status_code != 422:
            raise FlowCheckError(
                "Expected 422 for short slug (<3 chars). "
                + _short_response_details(response)
            )

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("422 response is not valid JSON.")
        _require_envelope(payload, step="organizations-validation-422")
        return "Expected validation: slug must be 3-63 chars and match [a-z0-9-]"

    def _create_org(self, client: httpx.Client) -> str:
        slug = f"flow-{_now_suffix()}-{uuid.uuid4().hex[:6]}"
        name = f"Flow Check {_now_suffix()}"

        response = client.post(
            "/api/v1/organizations",
            headers=self._auth_headers(),
            json={"name": name, "slug": slug},
        )
        if response.status_code != 201:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Organization create response is not valid JSON.")
        _require_envelope(payload, step="organizations-create")

        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("org_id"), str):
            raise FlowCheckError("Organization create response missing org_id.")

        self._state.org_id = data["org_id"]
        return f"Created org_id={self._state.org_id} slug={slug}"

    def _add_self_member(self, client: httpx.Client) -> str:
        if not self._state.org_id or not self._state.user_id:
            raise FlowCheckError("org_id/user_id prerequisites missing.")

        response = client.post(
            f"/api/v1/organizations/{self._state.org_id}/members",
            headers=self._auth_headers(),
            json={"user_id": self._state.user_id, "org_role": "Admin"},
        )
        if response.status_code != 201:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Add member response is not valid JSON.")
        _require_envelope(payload, step="organizations-add-self-member")
        return f"Added self member user_id={self._state.user_id}"

    def _list_orgs(self, client: httpx.Client) -> str:
        if not self._state.org_id:
            raise FlowCheckError("org_id prerequisite missing.")

        response = client.get("/api/v1/organizations", headers=self._auth_headers())
        if response.status_code != 200:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Organization list response is not valid JSON.")
        _require_envelope(payload, step="organizations-list")

        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise FlowCheckError("Organization list payload missing items.")

        org_ids = {item.get("org_id") for item in data["items"] if isinstance(item, dict)}
        if self._state.org_id not in org_ids:
            raise FlowCheckError(
                f"Created org_id={self._state.org_id} is not visible in list response.",
            )
        return f"Listed organizations includes org_id={self._state.org_id}"

    def _create_workspace(self, client: httpx.Client) -> str:
        if not self._state.org_id:
            raise FlowCheckError("org_id prerequisite missing.")

        workspace_name = f"Flow Workspace {_now_suffix()}"
        response = client.post(
            f"/api/v1/organizations/{self._state.org_id}/workspaces",
            headers=self._auth_headers(),
            json={"name": workspace_name, "description": "Generated by flow checker"},
        )
        if response.status_code != 201:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Create workspace response is not valid JSON.")
        _require_envelope(payload, step="workspaces-create")

        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("workspace_id"), str):
            raise FlowCheckError("Create workspace response missing workspace_id.")

        self._state.workspace_id = data["workspace_id"]
        return f"Created workspace_id={self._state.workspace_id}"

    def _list_workspaces(self, client: httpx.Client) -> str:
        if not self._state.org_id or not self._state.workspace_id:
            raise FlowCheckError("org_id/workspace_id prerequisites missing.")

        response = client.get(
            f"/api/v1/organizations/{self._state.org_id}/workspaces",
            headers=self._auth_headers(),
        )
        if response.status_code != 200:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Workspace list response is not valid JSON.")
        _require_envelope(payload, step="workspaces-list")

        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise FlowCheckError("Workspace list payload missing items.")

        workspace_ids = {item.get("workspace_id") for item in data["items"] if isinstance(item, dict)}
        if self._state.workspace_id not in workspace_ids:
            raise FlowCheckError(
                f"Created workspace_id={self._state.workspace_id} is not visible in list response.",
            )
        return f"Listed workspaces includes workspace_id={self._state.workspace_id}"

    def _create_network(self, client: httpx.Client) -> str:
        if not self._state.workspace_id:
            raise FlowCheckError("workspace_id prerequisite missing.")

        network_name = f"flow-net-{_now_suffix()}"
        response = client.post(
            "/api/v1/networks",
            headers=self._auth_headers(),
            json={
                "workspace_id": self._state.workspace_id,
                "name": network_name,
                "description": "Generated by flow checker",
                "cidr": "10.250.0.0/24",
            },
        )
        if response.status_code != 201:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Network create response is not valid JSON.")
        _require_envelope(payload, step="networks-create")

        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("network_id"), str):
            raise FlowCheckError("Network create response missing network_id.")

        self._state.network_id = data["network_id"]
        return f"Created network_id={self._state.network_id}"

    def _list_networks(self, client: httpx.Client) -> str:
        if not self._state.workspace_id or not self._state.network_id:
            raise FlowCheckError("workspace_id/network_id prerequisites missing.")

        response = client.get(
            "/api/v1/networks",
            headers=self._auth_headers(),
            params={"workspace_id": self._state.workspace_id},
        )
        if response.status_code != 200:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Network list response is not valid JSON.")
        _require_envelope(payload, step="networks-list")

        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise FlowCheckError("Network list payload missing items.")

        network_ids = {item.get("network_id") for item in data["items"] if isinstance(item, dict)}
        if self._state.network_id not in network_ids:
            raise FlowCheckError(
                f"Created network_id={self._state.network_id} is not visible in list response.",
            )
        return f"Listed networks includes network_id={self._state.network_id}"

    def _create_device(self, client: httpx.Client) -> str:
        if not self._state.network_id:
            raise FlowCheckError("network_id prerequisite missing.")

        hostname = f"flow-device-{_now_suffix()}"
        response = client.post(
            f"/api/v1/networks/{self._state.network_id}/devices",
            headers=self._auth_headers(),
            json={
                "hostname": hostname,
                "device_type": "router",
                "ip_address": "10.250.0.10",
                "vendor": "NANFO",
                "model": "LAB-1",
            },
        )
        if response.status_code != 201:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Device create response is not valid JSON.")
        _require_envelope(payload, step="devices-create")

        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("device_id"), str):
            raise FlowCheckError("Device create response missing device_id.")

        self._state.device_id = data["device_id"]
        return f"Created device_id={self._state.device_id}"

    def _list_devices(self, client: httpx.Client) -> str:
        if not self._state.network_id or not self._state.device_id:
            raise FlowCheckError("network_id/device_id prerequisites missing.")

        response = client.get(
            f"/api/v1/networks/{self._state.network_id}/devices",
            headers=self._auth_headers(),
        )
        if response.status_code != 200:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Device list response is not valid JSON.")
        _require_envelope(payload, step="devices-list")

        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise FlowCheckError("Device list payload missing items.")

        device_ids = {item.get("device_id") for item in data["items"] if isinstance(item, dict)}
        if self._state.device_id not in device_ids:
            raise FlowCheckError(
                f"Created device_id={self._state.device_id} is not visible in list response.",
            )
        return f"Listed devices includes device_id={self._state.device_id}"

    def _check_telemetry_health(self, client: httpx.Client) -> str:
        response = client.get("/api/v1/telemetry/health", headers=self._auth_headers())
        if response.status_code != 200:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Telemetry health response is not valid JSON.")
        _require_envelope(payload, step="telemetry-health")
        return "GET /api/v1/telemetry/health -> 200"

    def _check_alerts_list(self, client: httpx.Client) -> str:
        response = client.get("/api/v1/alerts", headers=self._auth_headers())
        if response.status_code != 200:
            raise FlowCheckError(_short_response_details(response))

        payload = _json_or_none(response)
        if payload is None:
            raise FlowCheckError("Alerts list response is not valid JSON.")
        _require_envelope(payload, step="alerts-list")
        return "GET /api/v1/alerts -> 200"

    def _check_ws_alerts(self) -> str:
        asyncio.run(self._ws_subscribe(path="/ws/alerts", channel="alerts", filters={}))
        return "alerts websocket subscription acknowledged"

    def _check_ws_topology(self) -> str:
        if not self._state.network_id:
            raise FlowCheckError("network_id prerequisite missing.")
        asyncio.run(
            self._ws_subscribe(
                path="/ws/topology",
                channel="topology",
                filters={"network_id": self._state.network_id},
            ),
        )
        return "topology websocket subscription acknowledged"

    def _check_ws_telemetry(self) -> str:
        if not self._state.network_id:
            raise FlowCheckError("network_id prerequisite missing.")
        asyncio.run(
            self._ws_subscribe(
                path="/ws/telemetry",
                channel="telemetry",
                filters={"network_id": self._state.network_id},
            ),
        )
        return "telemetry websocket subscription acknowledged"

    def _check_ws_digital_twin(self) -> str:
        if not self._state.network_id:
            raise FlowCheckError("network_id prerequisite missing.")
        asyncio.run(
            self._ws_subscribe(
                path="/ws/digital-twin",
                channel="digital-twin",
                filters={"network_id": self._state.network_id},
            ),
        )
        return "digital-twin websocket subscription acknowledged"

    async def _ws_subscribe(self, *, path: str, channel: str, filters: dict[str, Any]) -> None:
        if not self._access_token:
            raise FlowCheckError("Access token is missing for websocket check.")

        ws_url = f"{self._ws_base_url}{path}?token={quote(self._access_token)}"

        async with websockets.connect(
            ws_url,
            open_timeout=self._timeout_seconds,
            close_timeout=self._timeout_seconds,
        ) as websocket:
            frame = {"action": "subscribe", "channel": channel, "filters": filters}
            await websocket.send(json.dumps(frame))

            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=self._timeout_seconds)
            except TimeoutError as exc:
                raise FlowCheckError(f"Timed out waiting for subscribe ack on {path}") from exc

            try:
                ack = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise FlowCheckError(f"WebSocket ack is not JSON on {path}: {raw!r}") from exc

            if ack.get("event") != "subscribed" or ack.get("channel") != channel:
                raise FlowCheckError(f"Unexpected websocket ack on {path}: {ack!r}")

    def _print_summary(self) -> None:
        pass_count = sum(1 for result in self._results if result.status == "PASS")
        fail_count = sum(1 for result in self._results if result.status == "FAIL")
        skip_count = sum(1 for result in self._results if result.status == "SKIP")

        print("\n== Flow Summary ==")
        print(f"PASS: {pass_count} | FAIL: {fail_count} | SKIP: {skip_count}")

        if fail_count:
            print("\nFailed Steps:")
            for result in self._results:
                if result.status == "FAIL":
                    print(f"- {result.name}: {result.detail}")

        print("\nNotes:")
        print("- Browser favicon 404 at /favicon.ico is non-blocking for API/login flow.")
        print("- A 422 on POST /api/v1/organizations is expected for invalid slug payloads.")
        print("- WebSocket failures usually indicate backend process restart needed or auth token issues.")

    def _write_report_if_needed(self) -> None:
        if self._report_path is None:
            return

        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "base_url": self._base_url,
            "ws_base_url": self._ws_base_url,
            "state": asdict(self._state),
            "results": [asdict(result) for result in self._results],
        }
        self._report_path.parent.mkdir(parents=True, exist_ok=True)
        self._report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Detailed report written to {self._report_path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a detailed local NANFO flow check")
    parser.add_argument(
        "--base-url",
        default=os.getenv("NANFO_BASE_URL", "http://127.0.0.1:8000"),
        help="Backend API base URL",
    )
    parser.add_argument(
        "--ws-base-url",
        default=os.getenv("NANFO_WS_BASE_URL", "ws://127.0.0.1:8000"),
        help="Backend WebSocket base URL",
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
        default=10.0,
        help="HTTP/WebSocket timeout in seconds",
    )
    parser.add_argument(
        "--report-path",
        default="",
        help="Optional JSON output file path for detailed results",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    checker = LocalFlowChecker(args)
    return checker.run()


if __name__ == "__main__":
    raise SystemExit(main())
