"""Asset service I/O adapter: worker-thread storage/codec work and safe API errors.

CPU-heavy base64/SHA-256 work and blocking disk I/O never run on the event loop.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping

from fastapi import HTTPException

from app.modules.network.asset_storage import AssetIntegrityError, AssetStorageError, decode_inline
from app.modules.network.schemas import CampusModelAssetResponse

_METADATA_FIELDS = tuple(name for name in CampusModelAssetResponse.model_fields
                         if name not in {"download_path", "model_data_base64"})


async def storage_call(operation, *args, **kwargs):
    try:
        return await asyncio.to_thread(operation, *args, **kwargs)
    except AssetStorageError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


async def decode_upload(req) -> bytes:
    """Decode and verify an upload body exactly once, in a worker thread (422 on mismatch)."""
    try:
        return await asyncio.to_thread(decode_inline, req.model_data_base64, req.model_sha256, req.model_size_bytes)
    except AssetIntegrityError as exc:
        raise HTTPException(status_code=422, detail={
            "code": "CAMPUS_MODEL_ASSET_PAYLOAD_INVALID",
            "message": "model_data_base64 must be valid base64 matching model_size_bytes and model_sha256.",
        }) from exc


def read_body(store, row) -> bytes:
    if row.storage_backend == "inline":
        return decode_inline(row.model_data_base64, row.model_sha256, row.model_size_bytes)
    if row.storage_backend == "local_cas" and row.model_data_base64 is None:
        return store.read(row.model_sha256, row.model_size_bytes)
    raise AssetIntegrityError()


def _encoded_body(store, row) -> str:
    return base64.b64encode(read_body(store, row)).decode("ascii")


def _values(row) -> dict:
    if isinstance(row, Mapping):
        return {name: row[name] for name in _METADATA_FIELDS}
    return {name: getattr(row, name) for name in _METADATA_FIELDS}


def download_path(row) -> str:
    network_id = row["network_id"] if isinstance(row, Mapping) else row.network_id
    asset_id = row["campus_model_asset_id"] if isinstance(row, Mapping) else row.campus_model_asset_id
    return f"/api/v1/networks/{network_id}/campus-model-assets/{asset_id}/download"


def metadata_response(row) -> CampusModelAssetResponse:
    """Metadata-only representation (C4): never carries body bytes."""
    return CampusModelAssetResponse(**_values(row), download_path=download_path(row))


async def asset_response(store, row) -> CampusModelAssetResponse:
    """Explicit ``include_data`` representation; verified body read/encoded off-loop."""
    encoded = await storage_call(_encoded_body, store, row)
    return CampusModelAssetResponse(**_values(row), model_data_base64=encoded, download_path=download_path(row))
