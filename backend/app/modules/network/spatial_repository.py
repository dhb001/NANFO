"""Owner-only SQL and optimistic concurrency for the spatial scene aggregate."""

import uuid

from sqlalchemy import func, select, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.network.models import Device, Network
from app.modules.network.spatial_models import SpatialSceneRecord, SpatialSceneRevision
from app.modules.network.spatial_schemas import (
    SpatialHistoryEntry,
    SpatialHistoryList,
    SpatialHistoryQuery,
    SpatialSceneDocument,
    empty_scene,
)


class SpatialSceneRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def get(self, network_id: uuid.UUID) -> SpatialSceneDocument:
        row = (await self._db.execute(
            select(SpatialSceneRecord.revision, SpatialSceneRecord.scene)
            .where(SpatialSceneRecord.network_id == network_id)
        )).one_or_none()
        if row is None:
            return empty_scene()
        return SpatialSceneDocument.model_validate({**row.scene, "revision": row.revision})

    async def lock_active_network(self, network_id: uuid.UUID) -> bool:
        # Prevent network deletion racing the replacement. This is an owner-table lock.
        return (await self._db.scalar(
            select(Network.network_id).where(Network.network_id == network_id, Network.deleted_at.is_(None))
            .with_for_update(read=True)
        )) is not None

    async def active_device_ids(self, network_id: uuid.UUID, device_ids: set[uuid.UUID]) -> set[uuid.UUID]:
        if not device_ids:
            return set()
        rows = await self._db.scalars(
            select(Device.device_id).where(
                Device.network_id == network_id, Device.device_id.in_(device_ids), Device.deleted_at.is_(None),
            ).order_by(Device.device_id).with_for_update(read=True)
        )
        return set(rows.all())

    async def lock_scene_for_write(self, network_id: uuid.UUID) -> None:
        # The unique owning-network key fences simultaneous first writers, including
        # uncommitted inserts. The subsequent predicate is rechecked after row waits.
        initial = empty_scene().model_dump(mode="json", exclude={"revision"})
        await self._db.execute(
            insert(SpatialSceneRecord).values(network_id=network_id, revision=0, scene=initial)
            .on_conflict_do_nothing(index_elements=[SpatialSceneRecord.network_id])
        )
        await self._db.scalar(
            select(SpatialSceneRecord.network_id).where(SpatialSceneRecord.network_id == network_id)
            .with_for_update()
        )

    async def replace(self, network_id: uuid.UUID, expected_revision: int, scene: dict) -> bool:
        # Caller holds the scene write lock before its final authority check.
        revision = await self._db.scalar(
            update(SpatialSceneRecord).where(
                SpatialSceneRecord.network_id == network_id, SpatialSceneRecord.revision == expected_revision,
            ).values(revision=expected_revision + 1, scene=scene)
            .returning(SpatialSceneRecord.revision)
        )
        return revision is not None

    async def append_revision(self, network_id: uuid.UUID, revision: int, scene: dict, actor_id: uuid.UUID) -> None:
        await self._db.execute(insert(SpatialSceneRevision).values(
            network_id=network_id, revision=revision, scene=scene, actor_id=actor_id, origin="replacement",
        ))

    async def get_revision(self, network_id: uuid.UUID, revision: int) -> SpatialSceneDocument | None:
        row = (await self._db.execute(select(SpatialSceneRevision.scene).where(
            SpatialSceneRevision.network_id == network_id, SpatialSceneRevision.revision == revision,
        ))).one_or_none()
        return None if row is None else SpatialSceneDocument.model_validate({**row.scene, "revision": revision})

    async def list_history(self, network_id: uuid.UUID, query: SpatialHistoryQuery) -> SpatialHistoryList:
        history = SpatialSceneRevision
        scope = history.network_id == network_id
        page = select(
            history.revision, history.recorded_at, history.actor_id, history.origin,
            func.jsonb_array_length(history.scene["objects"]).label("object_count"),
        ).where(scope).order_by(history.revision.desc()).offset(
            (query.page - 1) * query.page_size,
        ).limit(query.page_size).subquery()
        total = select(func.count().label("total")).select_from(history).where(scope).subquery()
        # One statement gives page + count the same READ COMMITTED snapshot and
        # retains the actual total even for empty/out-of-range pages.
        rows = (await self._db.execute(
            select(total.c.total, *page.c).select_from(total.outerjoin(page, true())).order_by(page.c.revision.desc())
        )).mappings().all()
        return SpatialHistoryList(
            items=[SpatialHistoryEntry(**{key: row[key] for key in SpatialHistoryEntry.model_fields})
                   for row in rows if row["revision"] is not None],
            total=rows[0]["total"], page=query.page, page_size=query.page_size,
        )
