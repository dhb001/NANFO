"""Integration tests for plugins REST endpoint contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from tests.auth_support import create_session_access_token as create_access_token


def _make_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="plugins-api@example.com",
        roles=["Admin"],
        permissions=["read:topology", "write:config"],
    )
    return token


def _make_read_only_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="plugins-read@example.com",
        roles=["Admin"],
        permissions=["read:topology"],
    )
    return token


def _make_write_only_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="plugins-write@example.com",
        roles=["Admin"],
        permissions=["write:config"],
    )
    return token


@pytest.fixture
def client(session_auth) -> TestClient:
    fake_r = session_auth.redis
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
    assert body["data"]["registry_only"] is True
    assert body["data"]["execution_supported"] is False
    record = body["data"]["items"][0]
    assert record["signature_status"] == record["dependency_status"] == "declared_unverified"
    assert record["sandbox_status"] == "not_executed"
    assert record["permissions_status"] == "declared_unverified"
    assert record["lifecycle_semantics"] == "registry_flags_only"
    assert record["uninstalled_at"] is None
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


def test_list_plugins_requires_read_topology_permission(client):
    headers = {"Authorization": f"Bearer {_make_write_only_token()}"}
    response = client.get("/api/v1/plugins", headers=headers)
    assert response.status_code == 403


def test_plugin_mutations_require_write_config_permission(client):
    headers = {"Authorization": f"Bearer {_make_read_only_token()}"}
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
        headers=headers,
    )
    enable_response = client.post(f"/api/v1/plugins/{uuid.uuid4()}/enable", headers=headers)
    disable_response = client.post(f"/api/v1/plugins/{uuid.uuid4()}/disable", headers=headers)

    assert install_response.status_code == 403
    assert enable_response.status_code == 403
    assert disable_response.status_code == 403


def test_uninstall_returns_204_and_passes_authority_context(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    plugin_id = uuid.uuid4()
    with patch("app.modules.plugin.service.PluginService.uninstall_plugin", new_callable=AsyncMock) as uninstall:
        response = client.delete(f"/api/v1/plugins/{plugin_id}", headers=headers)
    assert response.status_code == 204
    assert response.content == b""
    assert uninstall.await_args.kwargs["plugin_id"] == plugin_id
    assert uninstall.await_args.kwargs["requested_by_user_id"]
    assert "claim_org_id" in uninstall.await_args.kwargs
    assert "claim_workspace_id" in uninstall.await_args.kwargs


def test_uninstall_requires_auth_and_write_permission(client):
    path = f"/api/v1/plugins/{uuid.uuid4()}"
    with patch("app.modules.plugin.service.PluginService.uninstall_plugin", new_callable=AsyncMock) as uninstall:
        assert client.delete(path).status_code in (401, 403)
        assert client.delete(path, headers={"Authorization": f"Bearer {_make_read_only_token()}"}).status_code == 403
    uninstall.assert_not_awaited()


def test_uninstall_requires_current_global_admin(client, session_auth):
    actor = uuid.uuid4()
    token, _ = create_access_token(user_id=str(actor), email="registry-admin@example.com", roles=["Admin"],
                                   permissions=["write:config"])
    session_auth.roles[actor] = ["Operator"]
    session_auth.permissions[("Operator",)] = ["write:config"]
    with patch("app.modules.plugin.service.PluginService.uninstall_plugin", new_callable=AsyncMock) as uninstall:
        response = client.delete(f"/api/v1/plugins/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    uninstall.assert_not_awaited()


@pytest.mark.parametrize("scoped", [False, True])
def test_uninstall_checks_current_membership_before_registry_access(client, tenant_auth, scoped):
    actor = uuid.uuid4()
    token, _ = create_access_token(
        user_id=str(actor), email="registry-member@example.com", roles=["Admin"], permissions=["write:config"],
        org_id=str(tenant_auth.org_id) if scoped else None,
    )
    tenant_auth.memberships.clear()
    with patch("app.modules.plugin.repository.PluginRepository.get_by_id", new_callable=AsyncMock) as get:
        response = client.delete(f"/api/v1/plugins/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code in (403, 404)
    assert response.json()["success"] is False
    get.assert_not_awaited()


def test_uninstall_missing_record_returns_canonical_error(client, tenant_auth):
    with patch("app.modules.plugin.repository.PluginRepository.get_by_id", new_callable=AsyncMock) as get:
        get.return_value = None
        response = client.delete(f"/api/v1/plugins/{uuid.uuid4()}",
                                 headers={"Authorization": f"Bearer {_make_token()}"})
    assert response.status_code == 404
    assert response.json()["errors"]["code"] == "PLUGIN_NOT_FOUND"
