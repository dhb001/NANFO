"""Unit tests for plugin service lifecycle and safety behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.plugin.schemas import PluginInstallRequest
from app.modules.plugin.service import PluginService


@pytest.fixture(autouse=True)
def active_membership():
    org = SimpleNamespace(org_id=uuid.UUID(int=1), name="Test", slug="test", created_at=datetime.now(UTC))
    with patch("app.modules.organization.repository.OrganizationRepository.list_for_user", return_value=([org], 1)):
        yield


def _make_plugin_row(
    *,
    plugin_id: uuid.UUID | None = None,
    plugin_key: str = "safe-plugin",
    name: str = "Safe Plugin",
    version: str = "1.0.0",
    status: str = "installed",
    enabled: bool = False,
    signature_status: str = "verified",
    dependency_status: str = "compatible",
    sandbox_status: str = "isolated",
    failure_reason: str | None = None,
):
    now = datetime.now(UTC)
    row_plugin_id = plugin_id or uuid.uuid4()
    manifest = {
        "plugin_key": plugin_key,
        "name": name,
        "version": version,
        "signer": "nanfo-labs",
        "signature": "sig:abcdef1234567890",
        "dependencies": {
            "platform_version": "0.1.0",
            "requires": ["core:telemetry"],
        },
        "sandbox": {
            "isolation_mode": "process",
            "permissions": ["read:telemetry"],
        },
        "metadata": {},
    }
    return SimpleNamespace(
        plugin_id=row_plugin_id,
        plugin_key=plugin_key,
        name=name,
        version=version,
        manifest=manifest,
        signature_status=signature_status,
        dependency_status=dependency_status,
        sandbox_status=sandbox_status,
        status=status,
        enabled=enabled,
        failure_reason=failure_reason,
        queue_status="queued",
        stream_entry_id="600-0",
        warning=None,
        installed_at=now,
        updated_at=now,
    )


def _install_request(**overrides) -> PluginInstallRequest:
    payload = {
        "plugin_key": "safe-plugin",
        "name": "Safe Plugin",
        "version": "1.0.0",
        "signer": "nanfo-labs",
        "signature": "sig:abcdef1234567890",
        "dependencies": {
            "platform_version": "0.1.0",
            "requires": ["core:telemetry", "core:topology"],
        },
        "sandbox": {
            "isolation_mode": "process",
            "permissions": ["read:telemetry", "read:topology"],
        },
        "metadata": {"category": "collector"},
    }
    payload.update(overrides)
    return PluginInstallRequest.model_validate(payload)


@pytest.mark.asyncio
async def test_list_plugins_normalizes_filters_and_counts_statuses(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.list_plugins = AsyncMock(
        return_value=[
            _make_plugin_row(status="installed", enabled=False),
            _make_plugin_row(status="enabled", enabled=True),
            _make_plugin_row(status="failed", enabled=False, failure_reason="PLUGIN_SIGNATURE_INVALID"),
        ]
    )

    result = await service.list_plugins(
        actor_user_id=str(uuid.UUID(int=10)),
        status_filter="ENABLED",
        enabled_filter="true",
        search_filter="  telemetry  ",
        limit=999,
    )

    assert result.total == 3
    assert result.status_counts["installed"] == 1
    assert result.status_counts["enabled"] == 1
    assert result.status_counts["failed"] == 1
    assert service._repo.list_plugins.await_args.kwargs["status"] == "enabled"
    assert service._repo.list_plugins.await_args.kwargs["enabled"] is True
    assert service._repo.list_plugins.await_args.kwargs["search"] == "telemetry"
    assert service._repo.list_plugins.await_args.kwargs["limit"] == 500


@pytest.mark.asyncio
async def test_list_plugins_rejects_invalid_status_filter(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)

    with pytest.raises(HTTPException) as exc_info:
        await service.list_plugins(
            actor_user_id=str(uuid.UUID(int=10)),
            status_filter="queued",
            enabled_filter=None,
            search_filter=None,
            limit=20,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "PLUGIN_STATUS_INVALID"


@pytest.mark.asyncio
async def test_list_plugins_rejects_invalid_enabled_filter(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)

    with pytest.raises(HTTPException) as exc_info:
        await service.list_plugins(
            actor_user_id=str(uuid.UUID(int=10)),
            status_filter=None,
            enabled_filter="not-bool",
            search_filter=None,
            limit=20,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "PLUGIN_ENABLED_FILTER_INVALID"


@pytest.mark.asyncio
async def test_install_plugin_creates_record_and_publishes_installed_event(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)
    row = _make_plugin_row(status="installed", enabled=False)
    service._repo.get_by_plugin_key = AsyncMock(return_value=None)
    service._repo.create = AsyncMock(return_value=row)

    async def _update(target, **kwargs):
        target.queue_status = kwargs["queue_status"]
        target.stream_entry_id = kwargs["stream_entry_id"]
        target.warning = kwargs["warning"]
        target.status = kwargs["status"]
        target.enabled = kwargs["enabled"]
        target.failure_reason = kwargs["failure_reason"]
        return target

    service._repo.update_lifecycle = AsyncMock(side_effect=_update)

    with patch("app.modules.plugin.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "700-0"
        result = await service.install_plugin(
            req=_install_request(),
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result.idempotent_replay is False
    assert result.status == "installed"
    assert result.enabled is False
    assert result.queue_status == "queued"
    assert result.stream_entry_id == "700-0"
    assert mock_publish.await_args.kwargs["event_type"] == "plugin.installed"
    assert mock_db.commit.await_count == 2
    mock_db.refresh.assert_awaited_with(row)


@pytest.mark.asyncio
async def test_install_plugin_returns_replay_when_same_key_and_version(mock_db, fake_redis):
    row = _make_plugin_row(status="installed", enabled=False, version="1.0.0")
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_plugin_key = AsyncMock(return_value=row)

    result = await service.install_plugin(
        req=_install_request(version="1.0.0"),
        correlation_id=str(uuid.uuid4()),
        requested_by_user_id=str(uuid.uuid4()),
    )

    assert result.idempotent_replay is True
    assert result.queue_status == "replayed"


@pytest.mark.asyncio
async def test_install_plugin_rejects_conflicting_version(mock_db, fake_redis):
    row = _make_plugin_row(status="installed", enabled=False, version="1.0.0")
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_plugin_key = AsyncMock(return_value=row)

    with pytest.raises(HTTPException) as exc_info:
        await service.install_plugin(
            req=_install_request(version="2.0.0"),
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PLUGIN_VERSION_CONFLICT"


@pytest.mark.asyncio
async def test_install_plugin_rejects_invalid_signature_and_publishes_failed_event(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_plugin_key = AsyncMock(return_value=None)

    with patch("app.modules.plugin.service.publish_event", new_callable=AsyncMock) as mock_publish, pytest.raises(
        HTTPException
    ) as exc_info:
        await service.install_plugin(
            req=_install_request(signature="bad-signature"),
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "PLUGIN_SIGNATURE_INVALID"
    assert mock_publish.await_args.kwargs["event_type"] == "plugin.failed"


@pytest.mark.asyncio
async def test_install_plugin_rejects_dependency_mismatch_and_publishes_failed_event(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_plugin_key = AsyncMock(return_value=None)

    with patch("app.modules.plugin.service.publish_event", new_callable=AsyncMock) as mock_publish, pytest.raises(
        HTTPException
    ) as exc_info:
        await service.install_plugin(
            req=_install_request(dependencies={"platform_version": "9.9.9", "requires": []}),
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PLUGIN_DEPENDENCY_INCOMPATIBLE"
    assert mock_publish.await_args.kwargs["event_type"] == "plugin.failed"


@pytest.mark.asyncio
async def test_install_plugin_rejects_sandbox_permission_scope(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_plugin_key = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.install_plugin(
            req=_install_request(
                sandbox={
                    "isolation_mode": "process",
                    "permissions": ["write:config"],
                }
            ),
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "PLUGIN_PERMISSION_SCOPE_INVALID"


@pytest.mark.asyncio
async def test_install_plugin_publish_failure_is_fail_open(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)
    row = _make_plugin_row(status="installed", enabled=False)
    service._repo.get_by_plugin_key = AsyncMock(return_value=None)
    service._repo.create = AsyncMock(return_value=row)

    async def _update(target, **kwargs):
        target.queue_status = kwargs["queue_status"]
        target.warning = kwargs["warning"]
        target.stream_entry_id = kwargs["stream_entry_id"]
        target.status = kwargs["status"]
        target.enabled = kwargs["enabled"]
        target.failure_reason = kwargs["failure_reason"]
        return target

    service._repo.update_lifecycle = AsyncMock(side_effect=_update)

    with patch("app.modules.plugin.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.side_effect = RuntimeError("stream unavailable")
        result = await service.install_plugin(
            req=_install_request(),
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result.queue_status == "deferred"
    assert result.warning == "event_queue_unavailable"


@pytest.mark.asyncio
async def test_enable_plugin_returns_404_when_not_found(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.enable_plugin(
            plugin_id=uuid.uuid4(),
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "PLUGIN_NOT_FOUND"


@pytest.mark.asyncio
async def test_enable_plugin_replay_when_already_enabled(mock_db, fake_redis):
    row = _make_plugin_row(status="enabled", enabled=True)
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)

    result = await service.enable_plugin(
        plugin_id=row.plugin_id,
        correlation_id=str(uuid.uuid4()),
        requested_by_user_id=str(uuid.uuid4()),
    )

    assert result.idempotent_replay is True
    assert result.queue_status == "replayed"


@pytest.mark.asyncio
async def test_enable_plugin_fails_isolated_and_publishes_plugin_failed_event(mock_db, fake_redis):
    row = _make_plugin_row(status="installed", enabled=False)
    row.manifest["sandbox"]["permissions"] = ["write:config"]
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)

    async def _update(target, **kwargs):
        target.status = kwargs["status"]
        target.enabled = kwargs["enabled"]
        target.failure_reason = kwargs["failure_reason"]
        target.queue_status = kwargs["queue_status"]
        target.stream_entry_id = kwargs["stream_entry_id"]
        target.warning = kwargs["warning"]
        target.signature_status = kwargs.get("signature_status", target.signature_status)
        target.dependency_status = kwargs.get("dependency_status", target.dependency_status)
        target.sandbox_status = kwargs.get("sandbox_status", target.sandbox_status)
        return target

    service._repo.update_lifecycle = AsyncMock(side_effect=_update)

    with patch("app.modules.plugin.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "800-0"
        with pytest.raises(HTTPException) as exc_info:
            await service.enable_plugin(
                plugin_id=row.plugin_id,
                correlation_id=str(uuid.uuid4()),
                requested_by_user_id=str(uuid.uuid4()),
            )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "PLUGIN_PERMISSION_SCOPE_INVALID"
    assert row.status == "failed"
    assert row.enabled is False
    assert row.sandbox_status == "blocked"
    assert mock_publish.await_args.kwargs["event_type"] == "plugin.failed"


@pytest.mark.asyncio
async def test_enable_plugin_success_transitions_and_publishes_enabled_event(mock_db, fake_redis):
    row = _make_plugin_row(status="installed", enabled=False)
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)

    async def _update(target, **kwargs):
        target.status = kwargs["status"]
        target.enabled = kwargs["enabled"]
        target.failure_reason = kwargs["failure_reason"]
        target.queue_status = kwargs["queue_status"]
        target.stream_entry_id = kwargs["stream_entry_id"]
        target.warning = kwargs["warning"]
        if "signature_status" in kwargs and kwargs["signature_status"] is not None:
            target.signature_status = kwargs["signature_status"]
        if "dependency_status" in kwargs and kwargs["dependency_status"] is not None:
            target.dependency_status = kwargs["dependency_status"]
        if "sandbox_status" in kwargs and kwargs["sandbox_status"] is not None:
            target.sandbox_status = kwargs["sandbox_status"]
        return target

    service._repo.update_lifecycle = AsyncMock(side_effect=_update)

    with patch("app.modules.plugin.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "801-0"
        result = await service.enable_plugin(
            plugin_id=row.plugin_id,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result.status == "enabled"
    assert result.enabled is True
    assert result.queue_status == "queued"
    assert result.stream_entry_id == "801-0"
    assert mock_publish.await_args.kwargs["event_type"] == "plugin.enabled"


@pytest.mark.asyncio
async def test_disable_plugin_returns_404_when_not_found(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.disable_plugin(
            plugin_id=uuid.uuid4(),
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "PLUGIN_NOT_FOUND"


@pytest.mark.asyncio
async def test_disable_plugin_replay_when_already_disabled(mock_db, fake_redis):
    row = _make_plugin_row(status="disabled", enabled=False)
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)

    result = await service.disable_plugin(
        plugin_id=row.plugin_id,
        correlation_id=str(uuid.uuid4()),
        requested_by_user_id=str(uuid.uuid4()),
    )

    assert result.idempotent_replay is True
    assert result.queue_status == "replayed"


@pytest.mark.asyncio
async def test_disable_plugin_success_transitions_and_publishes_disabled_event(mock_db, fake_redis):
    row = _make_plugin_row(status="enabled", enabled=True)
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)

    async def _update(target, **kwargs):
        target.status = kwargs["status"]
        target.enabled = kwargs["enabled"]
        target.failure_reason = kwargs["failure_reason"]
        target.queue_status = kwargs["queue_status"]
        target.stream_entry_id = kwargs["stream_entry_id"]
        target.warning = kwargs["warning"]
        return target

    service._repo.update_lifecycle = AsyncMock(side_effect=_update)

    with patch("app.modules.plugin.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "802-0"
        result = await service.disable_plugin(
            plugin_id=row.plugin_id,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result.status == "disabled"
    assert result.enabled is False
    assert result.queue_status == "queued"
    assert result.stream_entry_id == "802-0"
    assert mock_publish.await_args.kwargs["event_type"] == "plugin.disabled"
