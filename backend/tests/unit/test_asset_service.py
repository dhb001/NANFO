from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.network.asset_backfill import migrate_batch
from app.modules.network.asset_settings import AssetSettings
from app.modules.network.asset_storage import LocalAssetStore
from app.modules.network.service import CampusModelAssetService
from tests.asset_support import ACTOR_ID, NETWORK_ID, ORG_ID, WORKSPACE_ID, registration, request, row


@pytest.fixture
def service(mock_db, tmp_path, monkeypatch):
    mock_db.expire_all = MagicMock()
    tmp_path.chmod(0o700)
    svc = CampusModelAssetService(mock_db, None, asset_store=LocalAssetStore(AssetSettings(root=tmp_path)))
    svc._network_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(workspace_id=WORKSPACE_ID))
    svc._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=ORG_ID))
    svc._repo = AsyncMock()
    svc._repo.get_latest_for_network.return_value = None
    svc._repo.active_usage.return_value = (0, 0)
    svc._repo.digest_referenced.return_value = False
    svc._repo.soft_delete_for_network.return_value = 0
    svc._repo.create.side_effect = lambda **kw: row(**kw)
    svc.audit = AsyncMock()
    monkeypatch.setattr("app.modules.network.service.append_audit_log", svc.audit)
    return svc


async def upload(svc, **changes):
    return await svc.upsert_asset(network_id=NETWORK_ID, actor_id=str(ACTOR_ID), req=request(**changes))


async def test_new_bytes_outside_db_and_registration(service):
    result = await upload(service, registration=registration())
    saved = service._repo.create.call_args.kwargs
    assert saved["model_data_base64"] is None and saved["storage_backend"] == "local_cas"
    assert saved["registration"] == registration()
    # C4: the upload response is metadata only (never an echo of the body).
    assert result.items[0].model_data_base64 is None
    assert "model_data_base64" not in result.model_dump()["items"][0]
    assert result.items[0].download_path.endswith("/download")
    assert service._db.commit.await_count == 1
    assert service._asset_store.read(request().model_sha256, request().model_size_bytes) == b"campus-model"
    service._repo.lock_digest.assert_awaited_once_with(request().model_sha256)
    audit = service.audit.await_args.kwargs
    assert audit["event_type"] == "network.campus_model_asset.uploaded" and audit["org_id"] == ORG_ID
    assert audit["metadata"]["model_sha256"] == request().model_sha256 and audit["metadata"]["new_object"] is True


async def test_body_decoded_and_hashed_once_off_the_event_loop(service, monkeypatch):
    import threading

    from app.modules.network import asset_storage

    calls = []
    original = asset_storage.decode_inline

    def tracked(*args):
        calls.append(threading.current_thread() is threading.main_thread())
        return original(*args)

    hashed = []
    original_verify = asset_storage.verify_body

    def tracked_verify(*args, **kwargs):
        hashed.append(1)
        return original_verify(*args, **kwargs)

    monkeypatch.setattr("app.modules.network.asset_io.decode_inline", tracked)
    monkeypatch.setattr(asset_storage, "verify_body", tracked_verify)
    await upload(service)
    # Exactly one decode and one SHA-256, on a worker thread; publication trusts it.
    assert calls == [False]
    assert hashed == [1]


async def test_payload_integrity_mismatch_is_422_before_any_lock(service):
    with pytest.raises(HTTPException) as error:
        await service.upsert_asset(network_id=NETWORK_ID, actor_id=str(ACTOR_ID),
                                   req=request(model_sha256="0" * 64))
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "CAMPUS_MODEL_ASSET_PAYLOAD_INVALID"
    service._repo.lock_digest.assert_not_awaited()
    service._repo.create.assert_not_awaited()
    assert list(service._asset_store.settings.root.iterdir()) == []


async def test_changed_body_allocates_new_identity_and_same_body_preserves_registration(service):
    existing = row(registration=registration())
    service._repo.get_latest_for_network.return_value = existing
    service._repo.update.side_effect = lambda current, **kw: row(campus_model_asset_id=current.campus_model_asset_id, **kw)
    result = await upload(service, replace_existing=False)
    assert result.items[0].campus_model_asset_id == existing.campus_model_asset_id
    assert result.items[0].registration.model_dump() == registration()
    cleared = await upload(service, replace_existing=False, registration=None)
    assert cleared.items[0].registration is None
    changed = await upload(service, body=b"changed", replace_existing=False)
    assert changed.items[0].campus_model_asset_id != existing.campus_model_asset_id
    assert existing.model_sha256 == request().model_sha256


async def test_failed_commit_removes_unreferenced_orphan_blob(service):
    service._db.commit.side_effect = [RuntimeError("commit failed"), None]
    with pytest.raises(RuntimeError, match="commit failed"):
        await upload(service)
    service._db.rollback.assert_awaited_once()
    # Orphan cleanup re-checks references under the digest lock after rollback.
    assert service._repo.lock_digest.await_count == 2
    service._repo.digest_referenced.assert_awaited_once_with(request().model_sha256)
    assert list(service._asset_store.settings.root.iterdir()) == []


async def test_failed_commit_keeps_blob_referenced_by_another_row(service):
    service._db.commit.side_effect = [RuntimeError("commit failed"), None]
    service._repo.digest_referenced.return_value = True
    with pytest.raises(RuntimeError, match="commit failed"):
        await upload(service)
    assert service._asset_store.read(request().model_sha256, request().model_size_bytes) == b"campus-model"


async def test_failed_commit_never_removes_preexisting_blob(service):
    service._asset_store.put(b"campus-model", request().model_sha256, request().model_size_bytes)
    service._db.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        await upload(service)
    service._repo.digest_referenced.assert_not_awaited()
    assert service._asset_store.read(request().model_sha256, request().model_size_bytes) == b"campus-model"


async def test_orphan_cleanup_failure_never_masks_the_original_error(service, monkeypatch):
    service._db.commit.side_effect = RuntimeError("commit failed")
    service._repo.digest_referenced.side_effect = ConnectionError("database gone")
    with pytest.raises(RuntimeError, match="commit failed"):
        await upload(service)


async def test_legacy_download_and_tamper(service):
    legacy = row()
    service._repo.get_scoped.return_value = legacy
    body, digest = await service.download_asset(network_id=NETWORK_ID, asset_id=legacy.campus_model_asset_id,
                                                actor_user_id=str(ACTOR_ID))
    assert body == b"campus-model" and digest == legacy.model_sha256
    not_modified, same = await service.download_asset(
        network_id=NETWORK_ID, asset_id=legacy.campus_model_asset_id, actor_user_id=str(ACTOR_ID),
        if_none_match=f'W/"other", "sha256:{legacy.model_sha256}"',
    )
    assert not_modified is None and same == legacy.model_sha256
    legacy.model_data_base64 = "dGFtcGVy"
    with pytest.raises(HTTPException) as error:
        await service.download_asset(network_id=NETWORK_ID, asset_id=legacy.campus_model_asset_id,
                                     actor_user_id=str(ACTOR_ID))
    assert error.value.status_code == 503


async def test_current_scope_before_storage_and_after_lock(service):
    service._workspace_svc.assert_workspace_membership.side_effect = [SimpleNamespace(org_id=ORG_ID),
                                                                     HTTPException(403, "revoked")]
    with pytest.raises(HTTPException) as error:
        await upload(service)
    assert error.value.status_code == 403
    service._repo.create.assert_not_awaited()
    assert list(service._asset_store.settings.root.iterdir()) == []


async def test_revocation_during_blob_publication_prevents_commit_and_discards_orphan(service, monkeypatch):
    original_put = service._asset_store.put

    def revoke_during_put(*args, **kwargs):
        service._workspace_svc.assert_workspace_membership.side_effect = HTTPException(403, "revoked")
        return original_put(*args, **kwargs)

    monkeypatch.setattr(service._asset_store, "put", revoke_during_put)
    with pytest.raises(HTTPException) as error:
        await upload(service)
    assert error.value.status_code == 403
    service._repo.create.assert_not_awaited()
    service.audit.assert_not_awaited()
    service._db.rollback.assert_awaited_once()
    # Only the orphan-cleanup transaction commits; the upload itself never does.
    assert service._db.commit.await_count == 1
    assert list(service._asset_store.settings.root.iterdir()) == []


async def test_same_body_reupload_refreshes_before_serializing(service):
    existing = row(registration=registration())
    service._repo.get_latest_for_network.return_value = existing
    service._repo.update.side_effect = lambda current, **kw: current
    refreshed = []
    service._db.refresh.side_effect = lambda target: refreshed.append(target)
    result = await upload(service, replace_existing=False, model_file_name="renamed.glb")
    assert refreshed == [existing]
    assert result.items[0].campus_model_asset_id == existing.campus_model_asset_id


@pytest.mark.parametrize("name", ["../model.glb", "dir/model.glb", "dir\\model.glb", "model\r\n.glb"])
def test_filename_controls_rejected(name):
    with pytest.raises(ValidationError):
        request(model_file_name=name)


async def test_backfill_and_reverse_are_bounded_keep_registration_and_soft_deleted(service, monkeypatch):
    original = row(registration=registration(), deleted_at=row().created_at)
    repo = AsyncMock()
    repo.migration_batch.return_value = [original]
    monkeypatch.setattr("app.modules.network.asset_backfill.CampusModelAssetRepository", lambda db: repo)
    result = await migrate_batch(service._db, service._asset_store, direction="to-cas", limit=1)
    assert result["processed"] == 1 and original.model_data_base64 is None
    assert original.registration == registration() and original.deleted_at is not None
    await migrate_batch(service._db, service._asset_store, direction="to-inline", limit=1)
    assert original.model_data_base64 == request().model_data_base64
    assert len(list(service._asset_store.settings.root.iterdir())) == 1
    with pytest.raises(ValueError):
        await migrate_batch(service._db, service._asset_store, direction="to-cas", limit=101)


async def test_retirement_preserves_bytes_and_targets_exact_record(service):
    asset = row()
    service._repo.get_scoped.return_value = asset
    service._asset_store.put(b"campus-model", asset.model_sha256, asset.model_size_bytes)
    await service.retire_asset(network_id=NETWORK_ID, asset_id=asset.campus_model_asset_id, actor_id=str(ACTOR_ID),
                               correlation_id="retire-request")
    service._repo.get_scoped.assert_awaited_once_with(NETWORK_ID, asset.campus_model_asset_id)
    service._repo.soft_delete.assert_awaited_once_with(asset)
    service._db.commit.assert_awaited_once()
    assert service._asset_store.read(asset.model_sha256, asset.model_size_bytes) == b"campus-model"
    audit = service.audit.await_args.kwargs
    assert audit["event_type"] == "network.campus_model_asset.retired"
    assert audit["resource_id"] == asset.campus_model_asset_id and audit["org_id"] == ORG_ID
    assert audit["correlation_id"] == "retire-request"


@pytest.mark.parametrize("case", ["missing", "claim", "revoked_after_lock", "revoked_after_flush", "commit"])
async def test_retirement_denials_and_rollback(service, case):
    asset = row()
    service._repo.get_scoped.return_value = asset
    kwargs = {}
    if case == "missing":
        service._repo.get_scoped.return_value = None
    elif case == "claim":
        kwargs["claim_org_id"] = NETWORK_ID
    elif case.startswith("revoked"):
        valid_checks = 1 if case == "revoked_after_lock" else 2
        service._workspace_svc.assert_workspace_membership.side_effect = (
            [SimpleNamespace(org_id=ORG_ID)] * valid_checks + [HTTPException(403, "revoked")]
        )
    else:
        service._db.commit.side_effect = RuntimeError("failed")
    with pytest.raises((HTTPException, RuntimeError)) as error:
        await service.retire_asset(network_id=NETWORK_ID, asset_id=asset.campus_model_asset_id,
                                   actor_id=str(ACTOR_ID), **kwargs)
    if case != "commit":
        assert error.value.status_code == (404 if case == "missing" else 403)
        service._db.commit.assert_not_awaited()
    service._db.rollback.assert_awaited_once()


async def test_metadata_empty_page_and_final_authority_recheck(service):
    service._repo.list_metadata_for_network.return_value = ([], 41)
    result = await service.list_assets(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID),
                                       include_data=False, page=4, page_size=20)
    assert result.model_dump() == {"items": [], "total": 41, "page": 4, "page_size": 20}
    service._repo.list_for_network.assert_not_awaited()
    service._workspace_svc.assert_workspace_membership.side_effect = [SimpleNamespace(org_id=ORG_ID), HTTPException(403, "revoked")]
    with pytest.raises(HTTPException) as error:
        await service.list_assets(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), include_data=False)
    assert error.value.status_code == 403


def _metadata(size):
    return {"model_size_bytes": size}


async def test_include_data_aggregate_cap_rejects_before_any_body_is_loaded(service):
    """C4: include_data pages are capped at 32 MiB of bodies; sized from metadata first."""
    service._repo.list_metadata_for_network.return_value = ([_metadata(8 * 1024 * 1024)] * 4 + [_metadata(1)], 5)
    with pytest.raises(HTTPException) as error:
        await service.list_assets(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), include_data=True,
                                  page_size=10)
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "CAMPUS_MODEL_ASSET_INLINE_LIMIT_EXCEEDED"
    service._repo.list_page_for_network.assert_not_awaited()


async def test_include_data_rechecks_the_loaded_page_and_bounds_page_size(service):
    service._repo.list_metadata_for_network.return_value = ([_metadata(1)], 1)
    grown = row(model_size_bytes=33 * 1024 * 1024)  # page shifted between the two reads
    service._repo.list_page_for_network.return_value = ([grown], 1)
    with pytest.raises(HTTPException) as error:
        await service.list_assets(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), include_data=True,
                                  page_size=10)
    assert error.value.detail["code"] == "CAMPUS_MODEL_ASSET_INLINE_LIMIT_EXCEEDED"
    service._repo.list_metadata_for_network.reset_mock()
    with pytest.raises(HTTPException) as error:
        await service.list_assets(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), include_data=True,
                                  page_size=11)
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "CAMPUS_MODEL_ASSET_INLINE_PAGE_TOO_LARGE"
    service._repo.list_metadata_for_network.assert_not_awaited()


async def test_include_data_within_budget_returns_verified_bodies(service):
    asset = row()
    service._repo.list_metadata_for_network.return_value = ([_metadata(asset.model_size_bytes)], 1)
    service._repo.list_page_for_network.return_value = ([asset], 1)
    result = await service.list_assets(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), include_data=True,
                                       page_size=10)
    assert result.items[0].model_data_base64 == asset.model_data_base64 and result.total == 1
