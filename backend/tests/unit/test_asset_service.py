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
def service(mock_db, tmp_path):
    mock_db.expire_all = MagicMock()
    tmp_path.chmod(0o700)
    svc = CampusModelAssetService(mock_db, None, asset_store=LocalAssetStore(AssetSettings(root=tmp_path)))
    svc._network_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(workspace_id=WORKSPACE_ID))
    svc._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=ORG_ID))
    svc._repo = AsyncMock()
    svc._repo.get_latest_for_network.return_value = None
    svc._repo.create.side_effect = lambda **kw: row(**kw)
    return svc


async def upload(svc, **changes):
    return await svc.upsert_asset(network_id=NETWORK_ID, actor_id=str(ACTOR_ID), req=request(**changes))


async def test_new_bytes_outside_db_and_registration(service):
    result = await upload(service, registration=registration())
    saved = service._repo.create.call_args.kwargs
    assert saved["model_data_base64"] is None and saved["storage_backend"] == "local_cas"
    assert saved["registration"] == registration()
    assert result.items[0].model_data_base64 == request().model_data_base64
    assert result.items[0].download_path.endswith("/download")
    assert service._db.commit.await_count == 1


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


async def test_failed_commit_retains_body_and_rolls_back(service):
    service._db.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        await upload(service)
    service._db.rollback.assert_awaited_once()
    assert service._asset_store.read(request().model_sha256, request().model_size_bytes) == b"campus-model"


async def test_legacy_download_and_tamper(service):
    legacy = row()
    service._repo.get_scoped.return_value = legacy
    body, digest = await service.download_asset(network_id=NETWORK_ID, asset_id=legacy.campus_model_asset_id,
                                                actor_user_id=str(ACTOR_ID))
    assert body == b"campus-model" and digest == legacy.model_sha256
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


async def test_revocation_during_final_response_read_prevents_commit(service, monkeypatch):
    original_read = service._asset_store.read
    expires_before_read = None

    def revoke_during_read(digest, size):
        nonlocal expires_before_read
        expires_before_read = service._db.expire_all.call_count
        service._workspace_svc.assert_workspace_membership.side_effect = HTTPException(403, "revoked")
        return original_read(digest, size)

    monkeypatch.setattr(service._asset_store, "read", revoke_during_read)
    with pytest.raises(HTTPException) as error:
        await upload(service)
    assert error.value.status_code == 403
    assert service._db.expire_all.call_count == expires_before_read + 1
    service._db.commit.assert_not_awaited()
    service._db.rollback.assert_awaited_once()


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
    await service.retire_asset(network_id=NETWORK_ID, asset_id=asset.campus_model_asset_id, actor_id=str(ACTOR_ID))
    service._repo.get_scoped.assert_awaited_once_with(NETWORK_ID, asset.campus_model_asset_id)
    service._repo.soft_delete.assert_awaited_once_with(asset)
    service._db.commit.assert_awaited_once()
    assert service._asset_store.read(asset.model_sha256, asset.model_size_bytes) == b"campus-model"


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
