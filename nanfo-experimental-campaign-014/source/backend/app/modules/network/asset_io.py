"""Asset service I/O adapter: bounded worker-thread storage and safe API errors."""

import asyncio
import base64

from fastapi import HTTPException

from app.modules.network.asset_storage import AssetIntegrityError, AssetStorageError, decode_inline
from app.modules.network.schemas import CampusModelAssetResponse


async def storage_call(operation, *args):
    try:
        return await asyncio.to_thread(operation, *args)
    except AssetStorageError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


def read_body(store, row) -> bytes:
    if row.storage_backend == "inline":
        return decode_inline(row.model_data_base64, row.model_sha256, row.model_size_bytes)
    if row.storage_backend == "local_cas" and row.model_data_base64 is None:
        return store.read(row.model_sha256, row.model_size_bytes)
    raise AssetIntegrityError()


async def asset_response(store, row) -> CampusModelAssetResponse:
    body = await storage_call(read_body, store, row)
    values = {name: getattr(row, name) for name in CampusModelAssetResponse.model_fields
              if name not in {"download_path", "model_data_base64"}}
    return CampusModelAssetResponse(**values, model_data_base64=base64.b64encode(body).decode("ascii"),
                                    download_path=download_path(row))


def download_path(row) -> str:
    return f"/api/v1/networks/{row.network_id}/campus-model-assets/{row.campus_model_asset_id}/download"
