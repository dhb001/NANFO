"""Unreferenced campus-model object collector: python -m app.modules.network.asset_gc --help.

Removes only published objects that NO campus_model_assets row (active, retired or
inline) references, re-checked per digest under that digest's advisory lock (the
same lock uploads hold from publication until commit), plus abandoned single-link
``.upload-*`` temporaries older than ``NETWORK_ASSET_STALE_UPLOAD_SECONDS``.
Retired assets keep their bytes (Network.md §3.4). Safe to run while serving.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from app.modules.network.asset_storage import AssetStorageError, LocalAssetStore
from app.modules.network.repository import CampusModelAssetRepository

_BATCH = 200


async def collect_garbage(sessions, store: LocalAssetStore, *, dry_run: bool = False) -> dict:
    """Collect unreferenced objects; ``sessions`` is an async session factory."""
    stale_uploads = 0 if dry_run else await asyncio.to_thread(store.remove_stale_uploads)
    digests = await asyncio.to_thread(store.list_objects)
    removed = retained = candidates = 0
    for start in range(0, len(digests), _BATCH):
        chunk = digests[start:start + _BATCH]
        async with sessions() as db:
            referenced = await CampusModelAssetRepository(db).referenced_digests(chunk)
        for digest in chunk:
            if digest in referenced:
                retained += 1
                continue
            candidates += 1
            if dry_run:
                continue
            async with sessions() as db:
                repository = CampusModelAssetRepository(db)
                try:
                    await repository.lock_digest(digest)
                    if await repository.digest_referenced(digest):
                        retained += 1
                    elif await asyncio.to_thread(store.remove_unreferenced, digest):
                        removed += 1
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
    return {"objects": len(digests), "retained": retained, "unreferenced": candidates,
            "removed": removed, "stale_uploads_removed": stale_uploads, "dry_run": dry_run}


async def run(args):
    from app.db.postgres import AsyncSessionLocal, get_engine

    try:
        return await collect_garbage(AsyncSessionLocal, LocalAssetStore(), dry_run=args.dry_run)
    finally:
        await get_engine().dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report unreferenced objects without removing")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except AssetStorageError as exc:
        parser.exit(1, f"{exc.code}: {exc.message}\n")
    except Exception:
        parser.exit(1, "Asset collection failed; no unverified object was removed. Check database availability.\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
