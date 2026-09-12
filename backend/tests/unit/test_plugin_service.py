"""Unit tests for metadata registry lifecycle and declaration admission."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.plugin.repository import PluginRepository
from app.modules.plugin.schemas import PluginInstallRequest, PluginRecordResponse
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
    assert result.registry_only is True and result.execution_supported is False
    assert service._repo.create.await_args.kwargs["signature_status"] == "declared_unverified"
    assert service._repo.create.await_args.kwargs["dependency_status"] == "declared_unverified"
    assert service._repo.create.await_args.kwargs["sandbox_status"] == "not_executed"
    assert mock_publish.await_args.kwargs["event_type"] == "plugin.installed"
    assert mock_db.commit.await_count == 1
    mock_db.refresh.assert_awaited_with(row)


@pytest.mark.asyncio
async def test_install_plugin_returns_replay_when_same_key_and_version(mock_db, fake_redis):
    row = _make_plugin_row(status="installed", enabled=False, version="1.0.0")
    row.manifest = _install_request().model_dump()
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
async def test_enable_plugin_rejects_declarations_without_claiming_isolation(mock_db, fake_redis):
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
    assert row.sandbox_status == "isolated"  # Historical stored claim is not rewritten.
    assert mock_publish.await_args.kwargs["event_type"] == "plugin.failed"
    assert mock_publish.await_args.kwargs["payload"]["sandbox_status"] == "not_executed"


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


def test_historical_claims_are_masked_without_mutating_manifest_or_row():
    row = _make_plugin_row()
    result = PluginRecordResponse.model_validate(row).model_dump(mode="json")
    assert result["registry_only"] is True
    assert result["execution_supported"] is False
    assert result["lifecycle_semantics"] == "registry_flags_only"
    assert result["signature_status"] == result["dependency_status"] == "declared_unverified"
    assert result["permissions_status"] == "declared_unverified"
    assert result["sandbox_status"] == "not_executed"
    assert result["manifest"] == row.manifest
    assert (row.signature_status, row.dependency_status, row.sandbox_status) == ("verified", "compatible", "isolated")


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"name": "Other"}, {"signer": "other-signer"}, {"signature": "sig:changed1234567890"},
    {"dependencies": {"requires": ["core:other"]}},
    {"sandbox": {"permissions": ["read:topology"], "isolation_mode": "process"}},
    {"metadata": {"digest": "sha256:changed"}},
])
@pytest.mark.parametrize("stored_status", ["installed", "uninstalled"])
async def test_same_version_conflicting_manifest_is_409(mock_db, fake_redis, overrides, stored_status):
    row = _make_plugin_row(status=stored_status)
    row.manifest = _install_request().model_dump()
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_plugin_key = AsyncMock(return_value=row)
    with patch("app.modules.plugin.service.publish_event", new_callable=AsyncMock) as publish:
        with pytest.raises(HTTPException) as exc:
            await service.install_plugin(req=_install_request(**overrides), correlation_id=str(uuid.uuid4()),
                                         requested_by_user_id=str(uuid.uuid4()))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PLUGIN_MANIFEST_CONFLICT"
    mock_db.commit.assert_not_awaited()
    publish.assert_not_awaited()


def test_canonical_manifest_ignores_object_order_not_json_types():
    manifest = _install_request().model_dump()
    assert PluginService._canonical_manifest(manifest) == PluginService._canonical_manifest(
        dict(reversed(list(manifest.items())))
    )
    assert PluginService._canonical_manifest(_install_request(metadata={"flag": True}).model_dump()) != (
        PluginService._canonical_manifest(_install_request(metadata={"flag": 1}).model_dump())
    )


@pytest.mark.parametrize("overrides", [
    {"plugin_key": "   "}, {"signer": " "}, {"name": 42}, {"entrypoint": "remote.py"},
    {"metadata": {"watts": float("nan")}}, {"metadata": {"oversized": "x" * 65_537}},
])
def test_manifest_schema_rejects_invalid_metadata(overrides):
    with pytest.raises(ValidationError):
        _install_request(**overrides)


@pytest.mark.asyncio
async def test_uninstall_and_identical_reinstall_preserve_id_and_history(mock_db, fake_redis):
    row = _make_plugin_row(status="enabled", enabled=True)
    row.manifest = _install_request().model_dump()
    row.uninstalled_at = None
    original_id, original_install = row.plugin_id, row.installed_at
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)
    service._repo.get_by_plugin_key = AsyncMock(return_value=row)
    service._repo.create = AsyncMock()
    actor = str(uuid.uuid4())
    correlation = str(uuid.uuid4())
    with patch("app.modules.identity.service.AuditLogRepository.append", new_callable=AsyncMock) as audit:
        with patch("app.modules.plugin.service.publish_event", new_callable=AsyncMock) as publish:
            await service.uninstall_plugin(plugin_id=row.plugin_id, correlation_id=correlation,
                                           requested_by_user_id=actor)
            first_removed_at = row.uninstalled_at
            assert first_removed_at is not None
            assert row.status == "uninstalled" and row.enabled is False
            await service.uninstall_plugin(plugin_id=row.plugin_id, correlation_id=correlation,
                                           requested_by_user_id=actor)
            assert row.uninstalled_at == first_removed_at
            assert audit.await_count == 1
            assert audit.await_args.kwargs["event_type"] == "plugin.registry.removed"
            assert audit.await_args.kwargs["actor_id"] == uuid.UUID(actor)
            assert audit.await_args.kwargs["resource_id"] == original_id
            publish.assert_not_awaited()
            publish.return_value = "900-0"
            response = await service.install_plugin(req=_install_request(), correlation_id=correlation,
                                                    requested_by_user_id=actor)
    assert response.status == "installed" and response.enabled is False
    assert response.idempotent_replay is False
    assert row.plugin_id == original_id and row.installed_at == original_install
    assert row.uninstalled_at is None
    assert row.signature_status == "verified"
    service._repo.create.assert_not_awaited()
    assert mock_db.commit.await_count == 2


@pytest.mark.asyncio
async def test_uninstall_audit_failure_does_not_commit(mock_db, fake_redis):
    row = _make_plugin_row()
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)
    with patch("app.modules.plugin.service.append_audit_log", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError):
            await service.uninstall_plugin(plugin_id=row.plugin_id, correlation_id=str(uuid.uuid4()),
                                           requested_by_user_id=str(uuid.uuid4()))
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["enable_plugin", "disable_plugin"])
async def test_uninstalled_flags_cannot_be_changed_without_reinstall(mock_db, fake_redis, action):
    service = PluginService(db=mock_db, redis=fake_redis)
    row = _make_plugin_row(status="uninstalled")
    service._repo.get_by_id = AsyncMock(return_value=row)
    with pytest.raises(HTTPException) as exc:
        await getattr(service, action)(plugin_id=row.plugin_id, correlation_id=str(uuid.uuid4()),
                                       requested_by_user_id=str(uuid.uuid4()))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PLUGIN_UNINSTALLED"
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_uninstall_missing_record_is_404(mock_db, fake_redis):
    service = PluginService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.uninstall_plugin(plugin_id=uuid.uuid4(), correlation_id=str(uuid.uuid4()),
                                       requested_by_user_id=str(uuid.uuid4()))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_repository_serializes_mutations_and_excludes_uninstalled_by_default(mock_db):
    from unittest.mock import MagicMock

    from sqlalchemy.dialects import postgresql

    mock_db.execute.return_value = MagicMock()
    repo = PluginRepository(mock_db)
    await repo.get_by_plugin_key("safe-plugin")
    assert "pg_advisory_xact_lock" in str(mock_db.execute.await_args_list[0].args[0])
    assert "FOR UPDATE" in str(mock_db.execute.await_args.args[0])
    await repo.get_by_id(uuid.uuid4())
    assert "FOR UPDATE" in str(mock_db.execute.await_args.args[0])
    for status_filter, operator in [(None, "!="), ("uninstalled", "=")]:
        await repo.list_plugins(status=status_filter, enabled=None, search=None, limit=20)
        sql = str(mock_db.execute.await_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
        ))
        assert f"plugins.status {operator} 'uninstalled'" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides,code", [
    ({"dependencies": {"requires": [42]}}, "PLUGIN_DEPENDENCY_INVALID"),
    ({"dependencies": {"platform_version": True}}, "PLUGIN_DEPENDENCY_INVALID"),
    ({"sandbox": {"permissions": [42]}}, "PLUGIN_SANDBOX_INVALID"),
    ({"sandbox": {"isolation_mode": True}}, "PLUGIN_SANDBOX_INVALID"),
])
async def test_invalid_declaration_types_rejected(mock_db, fake_redis, overrides, code):
    service = PluginService(db=mock_db, redis=None)
    service._repo.get_by_plugin_key = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.install_plugin(req=_install_request(**overrides), correlation_id=str(uuid.uuid4()),
                                     requested_by_user_id=str(uuid.uuid4()))
    assert exc.value.detail["code"] == code


@pytest.mark.asyncio
async def test_disable_installed_record_sets_explicit_disabled_status(mock_db):
    service = PluginService(db=mock_db, redis=None)
    row = _make_plugin_row()
    service._repo.get_by_id = AsyncMock(return_value=row)
    response = await service.disable_plugin(plugin_id=row.plugin_id, correlation_id=str(uuid.uuid4()),
                                            requested_by_user_id=str(uuid.uuid4()))
    assert response.status == "disabled" and response.idempotent_replay is False


@pytest.mark.asyncio
async def test_enable_revalidates_historical_manifest_schema(mock_db):
    service = PluginService(db=mock_db, redis=None)
    row = _make_plugin_row()
    row.manifest["sandbox"] = "process"
    service._repo.get_by_id = AsyncMock(return_value=row)
    with pytest.raises(HTTPException) as exc:
        await service.enable_plugin(plugin_id=row.plugin_id, correlation_id=str(uuid.uuid4()),
                                    requested_by_user_id=str(uuid.uuid4()))
    assert exc.value.detail["code"] == "PLUGIN_MANIFEST_INVALID"
    assert row.status == "failed"
