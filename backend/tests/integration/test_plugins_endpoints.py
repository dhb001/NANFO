"""Integration tests for plugins REST endpoint contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.core.security import create_access_token
from app.main import app


def _make_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="plugins-api@example.com",
        roles=["Admin"],
        permissions=["read:topology", "write:config"],
    )
    return token


@pytest.fixture
def client() -> TestClient:
    fake_r = fakeredis.FakeAsyncRedis(decode_responses=True)
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    async def _redis():
        yield fake_r

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_list_plugins_returns_envelope_with_status_counts(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    plugin_id = uuid.uuid4()
    now = datetime.now(UTC)
    list_payload = {
        "items": [
            {
                "plugin_id": plugin_id,
                "plugin_key": "safe-plugin",
                "name": "Safe Plugin",
                "version": "1.0.0",
                "manifest": {
                    "plugin_key": "safe-plugin",
                    "name": "Safe Plugin",
                    "version": "1.0.0",
                    "signer": "nanfo-labs",
                    "signature": "sig:abcdef1234567890",
                    "dependencies": {"platform_version": "0.1.0", "requires": ["core:telemetry"]},
                    "sandbox": {"isolation_mode": "process", "permissions": ["read:telemetry"]},
                    "metadata": {},
                },
                "signature_status": "verified",
                "dependency_status": "compatible",
                "sandbox_status": "isolated",
                "status": "installed",
                "enabled": False,
                "failure_reason": None,
                "queue_status": "queued",
                "stream_entry_id": "700-0",
                "warning": None,
                "installed_at": now,
                "updated_at": now,
            }
        ],
        "total": 1,
        "status_counts": {
            "installed": 1,
            "enabled": 0,
            "disabled": 0,
            "failed": 0,
        },
    }

    with patch(
        "app.modules.plugin.service.PluginService.list_plugins",
        new=AsyncMock(return_value=list_payload),
    ) as mock_list:
        response = client.get(
            "/api/v1/plugins",
            params={
                "status": "installed",
                "enabled": "false",
                "search": "safe",
                "limit": 50,
            },
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["total"] == 1
    assert body["data"]["status_counts"]["installed"] == 1
    call_kwargs = mock_list.await_args.kwargs
    assert call_kwargs["status_filter"] == "installed"
    assert call_kwargs["enabled_filter"] == "false"
    assert call_kwargs["search_filter"] == "safe"
    assert call_kwargs["limit"] == 50


def test_list_plugins_invalid_status_returns_400_with_error_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.plugin.service.PluginService.list_plugins",
        new=AsyncMock(
            side_effect=HTTPException(
                status_code=400,
                detail={
                    "code": "PLUGIN_STATUS_INVALID",
                    "message": "status must be one of: installed, enabled, disabled, failed.",
                },
            )
        ),
    ):
        response = client.get("/api/v1/plugins", params={"status": "queued"}, headers=headers)

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["errors"]["code"] == "PLUGIN_STATUS_INVALID"


def test_install_plugin_returns_created_envelope_with_queue_metadata(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    plugin_id = uuid.uuid4()
    now = datetime.now(UTC)
    response_payload = {
        "plugin_id": plugin_id,
        "plugin_key": "safe-plugin",
        "name": "Safe Plugin",
        "version": "1.0.0",
        "manifest": {
            "plugin_key": "safe-plugin",
            "name": "Safe Plugin",
            "version": "1.0.0",
            "signer": "nanfo-labs",
            "signature": "sig:abcdef1234567890",
            "dependencies": {"platform_version": "0.1.0", "requires": ["core:telemetry"]},
            "sandbox": {"isolation_mode": "process", "permissions": ["read:telemetry"]},
            "metadata": {},
        },
        "signature_status": "verified",
        "dependency_status": "compatible",
        "sandbox_status": "isolated",
        "status": "installed",
        "enabled": False,
        "failure_reason": None,
        "queue_status": "queued",
        "stream_entry_id": "701-0",
        "warning": None,
        "installed_at": now,
        "updated_at": now,
        "idempotent_replay": False,
    }

    with patch(
        "app.modules.plugin.service.PluginService.install_plugin",
        new=AsyncMock(return_value=response_payload),
    ) as mock_install:
        response = client.post(
            "/api/v1/plugins/install",
            json={
                "plugin_key": "safe-plugin",
                "name": "Safe Plugin",
                "version": "1.0.0",
                "signer": "nanfo-labs",
                "signature": "sig:abcdef1234567890",
                "dependencies": {"platform_version": "0.1.0", "requires": ["core:telemetry"]},
                "sandbox": {"isolation_mode": "process", "permissions": ["read:telemetry"]},
                "metadata": {},
            },
            headers=headers,
        )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["plugin_id"] == str(plugin_id)
    assert body["data"]["queue_status"] == "queued"
    assert body["data"]["idempotent_replay"] is False
    assert mock_install.await_args.kwargs["req"].plugin_key == "safe-plugin"


def test_install_plugin_signature_invalid_returns_400_error_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.plugin.service.PluginService.install_plugin",
        new=AsyncMock(
            side_effect=HTTPException(
                status_code=400,
                detail={
                    "code": "PLUGIN_SIGNATURE_INVALID",
                    "message": "Plugin signature format is invalid.",
                },
            )
        ),
    ):
        response = client.post(
            "/api/v1/plugins/install",
            json={
                "plugin_key": "unsafe-plugin",
                "name": "Unsafe Plugin",
                "version": "1.0.0",
                "signer": "nanfo-labs",
                "signature": "bad-signature-value",
                "dependencies": {},
                "sandbox": {"isolation_mode": "process", "permissions": ["read:telemetry"]},
                "metadata": {},
            },
            headers=headers,
        )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["errors"]["code"] == "PLUGIN_SIGNATURE_INVALID"


def test_enable_plugin_returns_envelope_with_enabled_state(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    plugin_id = uuid.uuid4()
    now = datetime.now(UTC)
    response_payload = {
        "plugin_id": plugin_id,
        "plugin_key": "safe-plugin",
        "name": "Safe Plugin",
        "version": "1.0.0",
        "manifest": {
            "plugin_key": "safe-plugin",
            "name": "Safe Plugin",
            "version": "1.0.0",
            "signer": "nanfo-labs",
            "signature": "sig:abcdef1234567890",
            "dependencies": {"platform_version": "0.1.0", "requires": ["core:telemetry"]},
            "sandbox": {"isolation_mode": "process", "permissions": ["read:telemetry"]},
            "metadata": {},
        },
        "signature_status": "verified",
        "dependency_status": "compatible",
        "sandbox_status": "isolated",
        "status": "enabled",
        "enabled": True,
        "failure_reason": None,
        "queue_status": "queued",
        "stream_entry_id": "702-0",
        "warning": None,
        "installed_at": now,
        "updated_at": now,
        "idempotent_replay": False,
    }

    with patch(
        "app.modules.plugin.service.PluginService.enable_plugin",
        new=AsyncMock(return_value=response_payload),
    ) as mock_enable:
        response = client.post(f"/api/v1/plugins/{plugin_id}/enable", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["status"] == "enabled"
    assert body["data"]["enabled"] is True
    assert mock_enable.await_args.kwargs["plugin_id"] == plugin_id


def test_enable_plugin_dependency_incompatible_returns_409_error_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.plugin.service.PluginService.enable_plugin",
        new=AsyncMock(
            side_effect=HTTPException(
                status_code=409,
                detail={
                    "code": "PLUGIN_DEPENDENCY_INCOMPATIBLE",
                    "message": "Plugin dependency requirements are incompatible with this runtime.",
                },
            )
        ),
    ):
        response = client.post(f"/api/v1/plugins/{uuid.uuid4()}/enable", headers=headers)

    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert body["errors"]["code"] == "PLUGIN_DEPENDENCY_INCOMPATIBLE"


def test_disable_plugin_returns_envelope_with_disabled_state(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    plugin_id = uuid.uuid4()
    now = datetime.now(UTC)
    response_payload = {
        "plugin_id": plugin_id,
        "plugin_key": "safe-plugin",
        "name": "Safe Plugin",
        "version": "1.0.0",
        "manifest": {
            "plugin_key": "safe-plugin",
            "name": "Safe Plugin",
            "version": "1.0.0",
            "signer": "nanfo-labs",
            "signature": "sig:abcdef1234567890",
            "dependencies": {"platform_version": "0.1.0", "requires": ["core:telemetry"]},
            "sandbox": {"isolation_mode": "process", "permissions": ["read:telemetry"]},
            "metadata": {},
        },
        "signature_status": "verified",
        "dependency_status": "compatible",
        "sandbox_status": "isolated",
        "status": "disabled",
        "enabled": False,
        "failure_reason": None,
        "queue_status": "queued",
        "stream_entry_id": "703-0",
        "warning": None,
        "installed_at": now,
        "updated_at": now,
        "idempotent_replay": False,
    }

    with patch(
        "app.modules.plugin.service.PluginService.disable_plugin",
        new=AsyncMock(return_value=response_payload),
    ) as mock_disable:
        response = client.post(f"/api/v1/plugins/{plugin_id}/disable", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["status"] == "disabled"
    assert body["data"]["enabled"] is False
    assert mock_disable.await_args.kwargs["plugin_id"] == plugin_id


def test_plugin_routes_require_auth(client):
    list_response = client.get("/api/v1/plugins")
    install_response = client.post(
        "/api/v1/plugins/install",
        json={
            "plugin_key": "safe-plugin",
            "name": "Safe Plugin",
            "version": "1.0.0",
            "signer": "nanfo-labs",
            "signature": "sig:abcdef1234567890",
            "dependencies": {},
            "sandbox": {"isolation_mode": "process", "permissions": ["read:telemetry"]},
            "metadata": {},
        },
    )
    enable_response = client.post(f"/api/v1/plugins/{uuid.uuid4()}/enable")
    disable_response = client.post(f"/api/v1/plugins/{uuid.uuid4()}/disable")

    assert list_response.status_code in (401, 403)
    assert install_response.status_code in (401, 403)
    assert enable_response.status_code in (401, 403)
    assert disable_response.status_code in (401, 403)
