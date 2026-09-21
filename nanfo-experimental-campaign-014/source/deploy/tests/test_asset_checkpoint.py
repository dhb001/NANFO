import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from deploy import verify
from deploy.asset_checkpoint import asset_checkpoint


def test_assets_volume_permissions_and_readonly_checkpoint_composition():
    root = Path(__file__).parents[1]
    compose = yaml.safe_load((root / "compose.yaml").read_text())
    assert (
        "network_assets:/var/lib/nanfo/network-assets"
        in compose["services"]["api"]["volumes"]
    )
    assert (
        "network_assets:/var/lib/nanfo/network-assets:ro"
        in compose["services"]["maintenance"]["volumes"]
    )
    assert (
        "network_assets:/volumes/network_assets"
        in compose["services"]["volume-init"]["volumes"]
    )
    assert '"network_assets"' in (root / "volume_init.py").read_text()


def test_asset_checkpoint_reads_deleted_bodies_and_binds_registration(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "backend"))
    from app.modules.network import asset_io

    row = SimpleNamespace(
        campus_model_asset_id="asset",
        network_id="network",
        registration={"version": 1},
        storage_backend="local_cas",
        mapping_by_device_id={},
        deleted_at="deleted",
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=Mock(scalars=lambda: Mock(all=lambda: [row])))
    )
    reader = Mock(return_value=b"actual bytes")
    monkeypatch.setattr(asset_io, "read_body", reader)
    first = asyncio.run(asset_checkpoint(db))
    assert first["verified_assets"] == 1 and first["verified_bytes"] == 12
    row.registration = {"version": 2}
    assert (
        asyncio.run(asset_checkpoint(db))["receipts_sha256"] != first["receipts_sha256"]
    )
    reader.side_effect = ValueError("corrupt body")
    with pytest.raises(ValueError):
        asyncio.run(asset_checkpoint(db))
    with pytest.raises(ValueError, match="cap"):
        asyncio.run(asset_checkpoint(db, max_rows=0))


def test_verifier_rejects_restored_registration_or_binary_tamper():
    import base64

    body = b"verified asset"
    asset = {
        "campus_model_asset_id": "id",
        "registration": {"version": 1},
        "model_data_base64": base64.b64encode(body).decode(),
        "download_path": "/download",
    }
    expected = {
        "asset": asset,
        "body_bytes": len(body),
        "body_sha256": verify.digest(body),
        "scene": {},
        "history": {"total": 2},
        "revision": {"revision": 1},
    }
    api = Mock()
    api.request.side_effect = [
        {"total": 1, "items": [asset]},
        {},
        {"total": 2},
        {"revision": 1},
    ]
    api.raw.return_value = (
        200,
        {
            "ETag": '"sha256:' + verify.digest(body) + '"',
            "Cache-Control": "private, no-store",
        },
        body,
    )
    assert verify.verify_spatial_assets(api, "network", expected)["bytes"] == len(body)
    api.request.side_effect = [{"total": 1, "items": [{**asset, "registration": None}]}]
    with pytest.raises(verify.VerificationError, match="receipt"):
        verify.verify_spatial_assets(api, "network", expected)
    api.request.side_effect = [{"total": 1, "items": [asset]}]
    api.raw.return_value = (200, {}, b"tampered")
    with pytest.raises(verify.VerificationError, match="bytes"):
        verify.verify_spatial_assets(api, "network", expected)
