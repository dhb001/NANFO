"""Owner-only SQL and optimistic concurrency for the spatial scene aggregate.

History storage (ADR-028, persistence F18): when the history table carries the
migration-0030 delta columns, revisions are stored as object-level deltas with a
full checkpoint every ``CHECKPOINT_INTERVAL`` revisions (``spatial_history``);
otherwise every revision is a full copy exactly as before. The capability is probed
from the catalog once per session, so code and schema can be deployed in any order.
History SQL uses a Core table limited to the columns each branch needs, never the
ORM model's column list, so it works before and after the migration.
"""

import uuid

from sqlalchemy import BigInteger, Integer, Text, case, cast, column, func, select, table, text, true, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.network.models import Device, Network
from app.modules.network.spatial_history import (
    SceneHistoryError,
    compute_scene_delta,
    delta_saves_space,
    is_checkpoint,
    reconstruct,
)
from app.modules.network.spatial_models import SpatialSceneRecord
from app.modules.network.spatial_schemas import (
    SpatialHistoryEntry,
    SpatialHistoryList,
    SpatialHistoryQuery,
    SpatialSceneDocument,
    empty_scene,
)

logger = get_logger(__name__)

#: History table as seen by this repository (both schema generations).
_HISTORY = table(
    "network_spatial_scene_revisions",
    column("network_id", PG_UUID(as_uuid=True)), column("revision", BigInteger), column("scene", JSONB),
    column("recorded_at"), column("actor_id", PG_UUID(as_uuid=True)), column("origin", Text),
    column("delta", JSONB), column("base_revision", BigInteger), column("storage_kind", Text),
)
_DELTA_COLUMNS = frozenset({"delta", "base_revision", "storage_kind"})
_CAPABILITY_KEY = "nanfo.network.spatial_history_delta"
_CAPABILITY_PROBE = text("""
    SELECT a.attname AS name, a.attnotnull AS not_null
    FROM pg_catalog.pg_attribute a
    WHERE a.attrelid = to_regclass('network_spatial_scene_revisions')
      AND a.attnum > 0 AND NOT a.attisdropped
""")


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

    # ---------------------------------------------------------------- history

    async def delta_history_enabled(self) -> bool:
        """Whether the history table has the 0030 delta columns and a nullable scene.

        Probed from the catalog once per session (``Session.info``); a session is
        bound to one database/search path, so the answer cannot go stale within it.
        """
        info = getattr(self._db, "info", None)
        if isinstance(info, dict) and isinstance(info.get(_CAPABILITY_KEY), bool):
            return info[_CAPABILITY_KEY]
        columns = {row.name: row.not_null for row in (await self._db.execute(_CAPABILITY_PROBE)).all()}
        enabled = _DELTA_COLUMNS <= columns.keys() and columns.get("scene") is False
        if isinstance(info, dict):
            info[_CAPABILITY_KEY] = enabled
        return enabled

    async def append_revision(self, network_id: uuid.UUID, revision: int, scene: dict, actor_id: uuid.UUID) -> None:
        values = {"network_id": network_id, "revision": revision, "actor_id": actor_id, "origin": "replacement"}
        if not await self.delta_history_enabled():
            await self._db.execute(insert(_HISTORY).values(**values, scene=scene))
            return
        delta = None
        if not is_checkpoint(revision) and revision > 0:
            try:
                base = await self._rebuild(network_id, revision - 1)
            except SceneHistoryError:
                # Never extend a broken chain: this revision becomes a new checkpoint.
                logger.warning("spatial_history_chain_invalid", network_id=str(network_id), revision=revision - 1)
                base = None
            if base is not None:
                candidate = compute_scene_delta(base, scene)
                if delta_saves_space(candidate, scene):
                    delta = candidate
        if delta is None:
            await self._db.execute(insert(_HISTORY).values(**values, scene=scene, storage_kind="full"))
        else:
            await self._db.execute(insert(_HISTORY).values(
                **values, scene=None, delta=delta, base_revision=revision - 1, storage_kind="delta",
            ))

    async def _chain(self, network_id: uuid.UUID, revision: int) -> list:
        """Rows from the nearest full checkpoint at or below ``revision`` up to it (PK range)."""
        history = _HISTORY.c
        checkpoint = select(func.max(history.revision)).where(
            history.network_id == network_id, history.revision <= revision, history.storage_kind == "full",
        ).scalar_subquery()
        return list((await self._db.execute(
            select(history.revision, history.storage_kind, history.scene, history.delta, history.base_revision)
            .where(history.network_id == network_id, history.revision <= revision, history.revision >= checkpoint)
            .order_by(history.revision)
        )).mappings().all())

    async def _rebuild(self, network_id: uuid.UUID, revision: int) -> dict | None:
        """Stored scene of ``revision`` (delta schema); None when it does not exist."""
        rows = await self._chain(network_id, revision)
        if not rows or rows[-1]["revision"] != revision:
            present = await self._db.scalar(select(_HISTORY.c.revision).where(
                _HISTORY.c.network_id == network_id, _HISTORY.c.revision == revision,
            ))
            if present is None:
                return None
            raise SceneHistoryError("stored revision has no reachable checkpoint")
        return reconstruct(rows, revision)

    async def get_revision(self, network_id: uuid.UUID, revision: int) -> SpatialSceneDocument | None:
        if await self.delta_history_enabled():
            try:
                scene = await self._rebuild(network_id, revision)
            except SceneHistoryError:
                logger.error("spatial_history_chain_invalid", network_id=str(network_id), revision=revision)
                raise
        else:
            scene = await self._db.scalar(select(_HISTORY.c.scene).where(
                _HISTORY.c.network_id == network_id, _HISTORY.c.revision == revision,
            ))
        return None if scene is None else SpatialSceneDocument.model_validate({**scene, "revision": revision})

    async def list_history(self, network_id: uuid.UUID, query: SpatialHistoryQuery) -> SpatialHistoryList:
        history = _HISTORY.c
        scope = history.network_id == network_id
        full_count = func.jsonb_array_length(history.scene["objects"])
        if await self.delta_history_enabled():
            # Delta rows carry their object count; no scene is rebuilt to list history.
            object_count = case(
                (history.storage_kind == "delta", cast(history.delta["object_count"].astext, Integer)),
                else_=full_count,
            )
        else:
            object_count = full_count
        page = select(
            history.revision, history.recorded_at, history.actor_id, history.origin,
            object_count.label("object_count"),
        ).where(scope).order_by(history.revision.desc()).offset(
            (query.page - 1) * query.page_size,
        ).limit(query.page_size).subquery()
        total = select(func.count().label("total")).select_from(_HISTORY).where(scope).subquery()
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

