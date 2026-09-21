"""Explicit operator CLI: python -m app.modules.network.asset_backfill --help.

Run with writers stopped and a coordinated DB/volume backup. No physical deletion.
Includes soft-deleted rows; repeated invocations resume via backend selection.
"""

import argparse
import asyncio
import base64
import json
import uuid

from app.modules.network.asset_storage import AssetStorageError, LocalAssetStore, decode_inline
from app.modules.network.repository import CampusModelAssetRepository


async def migrate_batch(db, store, *, direction: str, limit: int, after: uuid.UUID | None = None) -> dict:
    if direction not in {"to-cas", "to-inline"} or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("direction must be to-cas/to-inline and limit must be 1..100")
    backend = "inline" if direction == "to-cas" else "local_cas"
    try:
        rows = await CampusModelAssetRepository(db).migration_batch(backend=backend, limit=limit, after=after)
        last_id = None
        for row in rows:
            if direction == "to-cas":
                data = decode_inline(row.model_data_base64, row.model_sha256, row.model_size_bytes)
                await asyncio.to_thread(store.put, data, row.model_sha256, row.model_size_bytes)
                row.storage_backend = "local_cas"
                row.model_data_base64 = None
            else:
                data = await asyncio.to_thread(store.read, row.model_sha256, row.model_size_bytes)
                row.storage_backend = "inline"
                row.model_data_base64 = base64.b64encode(data).decode("ascii")
            last_id = str(row.campus_model_asset_id)
        await db.commit()
        return {"direction": direction, "processed": len(rows), "last_asset_id": last_id}
    except BaseException:
        await db.rollback()
        raise


async def run(args):
    from app.db.postgres import AsyncSessionLocal, get_engine

    try:
        async with AsyncSessionLocal() as db:
            return await migrate_batch(db, LocalAssetStore(), direction=args.direction, limit=args.limit, after=args.after)
    finally:
        await get_engine().dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direction", choices=["to-cas", "to-inline"])
    parser.add_argument("--limit", type=int, default=10, help="one transaction, 1..100 rows (default 10)")
    parser.add_argument("--after", type=uuid.UUID, help="optional exclusive asset UUID cursor")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be 1..100")
    try:
        result = asyncio.run(run(args))
    except AssetStorageError as exc:
        parser.exit(1, f"{exc.code}: {exc.message}\n")
    except Exception:
        parser.exit(1, "Asset migration failed; current batch rolled back. Check database configuration and availability.\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
