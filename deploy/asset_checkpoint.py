"""Read-only bounded Network asset receipt inspection with owning storage validation."""

import asyncio
import hashlib
import json


async def asset_checkpoint(db, *, max_rows=10000):
    from app.modules.network.asset_io import read_body
    from app.modules.network.asset_storage import LocalAssetStore
    from app.modules.network.models import CampusModelAssetRecord
    from sqlalchemy import select

    rows = (
        (
            await db.execute(
                select(CampusModelAssetRecord)
                .order_by(CampusModelAssetRecord.campus_model_asset_id)
                .limit(max_rows + 1)
            )
        )
        .scalars()
        .all()
    )
    if len(rows) > max_rows:
        raise ValueError("Asset checkpoint row cap exceeded")
    store, receipts, total = LocalAssetStore(), [], 0
    # Includes soft-deleted rows: retained identities must still have valid bytes.
    for row in rows:
        body = await asyncio.to_thread(read_body, store, row)
        total += len(body)
        receipts.append(
            {
                "id": str(row.campus_model_asset_id),
                "network_id": str(row.network_id),
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
                "registration": row.registration,
                "storage_backend": row.storage_backend,
                "mapping": row.mapping_by_device_id,
                "deleted": row.deleted_at is not None,
            }
        )
    raw = json.dumps(
        receipts, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return {
        "verified_assets": len(rows),
        "verified_bytes": total,
        "receipts_sha256": hashlib.sha256(raw).hexdigest(),
    }
