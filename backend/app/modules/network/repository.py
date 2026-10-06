"""NANFO Backend — Network module repository.

All DB operations for the Network module.
networks.workspace_id is a stored UUID reference — no SQL join to Organization (ADR-004, C5).
Bulk upserts and soft-deletes use single set-based statements against the owning
tables' partial unique indexes (ADR-028); callers reload rows before building responses.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.network.models import (
    CampusBuildingRecord,
    CampusModelAssetRecord,
    Device,
    DeviceGroup,
    DeviceGroupMember,
    Network,
)

#: Mutable campus-building columns written by an upsert (identity columns excluded).
CAMPUS_BUILDING_FIELDS: tuple[str, ...] = (
    "campus_key", "building_key", "label", "geometry", "x", "z", "base_y", "width", "depth",
    "height", "floors", "footprint", "wall_material", "attenuation_db", "source",
)
_BULK_ROWS = 200
#: Upper bound of one owner-trusted batch device read (emulation bindings need <= 320).
MAX_OWNER_DEVICE_READ = 1000


def validate_inventory_page(page: int, page_size: int) -> None:
    """Internal callers retain bounded 500-row batches; REST is capped at 200."""
    if page < 1 or not 1 <= page_size <= 500:
        raise ValueError("Inventory page must be positive and page_size between 1 and 500")


def _chunks(values: Sequence, size: int) -> Iterator[Sequence]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _asset_digest_lock_key(digest: str):
    # Separate advisory key space from inventory locks (text-derived bigint).
    return func.hashtextextended(f"nanfo:campus-model-asset:{digest}", 0)


class NetworkRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(
        self,
        workspace_id: uuid.UUID,
        name: str,
        description: str | None,
        cidr: str | None,
    ) -> Network:
        network = Network(workspace_id=workspace_id, name=name, description=description, cidr=cidr)
        self._db.add(network)
        await self._db.flush()
        return network

    async def get_by_id(self, network_id: uuid.UUID) -> Network | None:
        # Authorization re-checks after lock waits must observe committed state,
        # never a stale identity-map copy (READ COMMITTED + populate_existing).
        result = await self._db.execute(
            select(Network).where(Network.network_id == network_id, Network.deleted_at.is_(None))
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def has_active_for_workspace(self, workspace_id: uuid.UUID) -> bool:
        """One indexed probe (``ix_networks_workspace_id``); no count, no page."""
        return await self._db.scalar(select(Network.network_id).where(
            Network.workspace_id == workspace_id, Network.deleted_at.is_(None),
        ).limit(1)) is not None

    async def lock_active(self, network_id: uuid.UUID) -> None:
        """Shared parent fence used by write-authorized workflow creation."""
        await self._db.execute(select(Network.network_id).where(
            Network.network_id == network_id, Network.deleted_at.is_(None),
        ).with_for_update(read=True))

    async def lock_row(self, network_id: uuid.UUID) -> None:
        """Exclusive parent lock for asset and device-group writers."""
        await self._db.execute(select(Network.network_id).where(
            Network.network_id == network_id,
        ).with_for_update())

    async def update(self, network: Network, fields: dict) -> Network:
        for key, value in fields.items():
            setattr(network, key, value)
        await self._db.flush()
        return network

    async def soft_delete(self, network: Network) -> None:
        network.deleted_at = datetime.now(UTC)
        await self._db.flush()

    async def list_for_workspace(
        self, workspace_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Network], int]:
        validate_inventory_page(page, page_size)
        q = select(Network).where(Network.workspace_id == workspace_id, Network.deleted_at.is_(None))
        total = (await self._db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await self._db.execute(q.order_by(Network.created_at, Network.network_id)
                                      .offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total

    async def get_workspace_ids_for_network_ids(self, network_ids: list[str]) -> dict[str, str]:
        parsed_ids: list[uuid.UUID] = []
        for raw_id in network_ids:
            try:
                parsed_ids.append(uuid.UUID(raw_id))
            except (ValueError, TypeError, AttributeError):
                continue

        if not parsed_ids:
            return {}

        result = await self._db.execute(
            select(Network.network_id, Network.workspace_id).where(
                Network.network_id.in_(parsed_ids),
                Network.deleted_at.is_(None),
            )
        )
        rows = result.all()
        return {str(network_id): str(workspace_id) for network_id, workspace_id in rows}


class DeviceRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(
        self,
        network_id: uuid.UUID,
        hostname: str,
        ip_address: str | None,
        device_type: str,
        vendor: str | None,
        model: str | None,
        location_hint: str | None,
        spatial_ref_id: str | None,
    ) -> Device:
        device = Device(
            network_id=network_id,
            hostname=hostname,
            ip_address=ip_address,
            device_type=device_type,
            vendor=vendor,
            model=model,
            location_hint=location_hint,
            spatial_ref_id=spatial_ref_id,
            status="active",
        )
        self._db.add(device)
        await self._db.flush()
        return device

    async def get_by_id(self, device_id: uuid.UUID) -> Device | None:
        result = await self._db.execute(
            select(Device).where(Device.device_id == device_id, Device.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def lock(self, device_id: uuid.UUID) -> Device | None:
        return await self._db.scalar(select(Device).where(
            Device.device_id == device_id, Device.deleted_at.is_(None),
        ).with_for_update().execution_options(populate_existing=True))

    async def update(self, device: Device, fields: dict) -> Device:
        for key, value in fields.items():
            setattr(device, key, value)
        await self._db.flush()
        return device

    async def soft_delete(self, device: Device) -> None:
        device.deleted_at = datetime.now(UTC)
        device.status = "deleted"
        await self._db.flush()

    async def list_for_network(
        self, network_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Device], int]:
        validate_inventory_page(page, page_size)
        q = select(Device).where(Device.network_id == network_id, Device.deleted_at.is_(None))
        total = (await self._db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await self._db.execute(q.order_by(Device.created_at, Device.device_id)
                                      .offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total

    async def list_active_for_network(self, network_id: uuid.UUID) -> list[Device]:
        result = await self._db.execute(
            select(Device)
            .where(Device.network_id == network_id, Device.deleted_at.is_(None))
            .order_by(Device.device_id.asc())
        )
        return list(result.scalars().all())

    async def list_projection_page(
        self, network_id: uuid.UUID, *, after: uuid.UUID | None = None, limit: int = 500,
    ) -> list[dict]:
        """Keyset page of active devices as plain graph-projection values."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Projection page limit must be between 1 and 1000")
        query = select(
            Device.device_id, Device.hostname, Device.device_type, Device.ip_address, Device.vendor,
            Device.model, Device.location_hint, Device.spatial_ref_id,
        ).where(Device.network_id == network_id, Device.deleted_at.is_(None))
        if after is not None:
            query = query.where(Device.device_id > after)
        result = await self._db.execute(query.order_by(Device.device_id.asc()).limit(limit))
        return [dict(row) for row in result.mappings().all()]

    async def list_device_ids_for_network(
        self,
        *,
        network_id: uuid.UUID,
        device_ids: list[uuid.UUID] | None = None,
    ) -> set[uuid.UUID]:
        query = select(Device.device_id).where(
            Device.network_id == network_id,
            Device.deleted_at.is_(None),
        )

        if device_ids is not None:
            if not device_ids:
                return set()
            query = query.where(Device.device_id.in_(device_ids))

        rows = (await self._db.execute(query)).scalars().all()
        return {row for row in rows}

    async def list_active_by_ids(self, network_id: uuid.UUID, device_ids: Iterable[uuid.UUID]) -> list[Device]:
        """Active devices of ``network_id`` among ``device_ids`` (bounded, current state)."""
        ids = sorted(set(device_ids))
        if not ids:
            return []
        if len(ids) > MAX_OWNER_DEVICE_READ:
            raise ValueError(f"At most {MAX_OWNER_DEVICE_READ} devices may be read at once")
        result = await self._db.execute(
            select(Device).where(
                Device.network_id == network_id, Device.device_id.in_(ids), Device.deleted_at.is_(None),
            ).order_by(Device.device_id).execution_options(populate_existing=True)
        )
        return list(result.scalars().all())


class CampusBuildingRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_for_network(self, network_id: uuid.UUID) -> list[CampusBuildingRecord]:
        result = await self._db.execute(
            select(CampusBuildingRecord)
            .where(
                CampusBuildingRecord.network_id == network_id,
                CampusBuildingRecord.deleted_at.is_(None),
            )
            .order_by(CampusBuildingRecord.building_id.asc())
        )
        return list(result.scalars().all())

    async def active_building_ids(self, network_id: uuid.UUID) -> set[str]:
        rows = await self._db.scalars(select(CampusBuildingRecord.building_id).where(
            CampusBuildingRecord.network_id == network_id, CampusBuildingRecord.deleted_at.is_(None),
        ))
        return set(rows.all())

    async def upsert_many(self, *, network_id: uuid.UUID, buildings: Sequence[dict]) -> None:
        """Insert or update in place on unique active ``(network_id, building_id)``.

        Callers pass unique building identifiers (PostgreSQL rejects a statement
        that would update the same conflicting row twice).
        """
        table = CampusBuildingRecord.__table__
        for chunk in _chunks(list(buildings), _BULK_ROWS):
            statement = insert(table).values([
                {"campus_building_id": uuid.uuid4(), "network_id": network_id, **building}
                for building in chunk
            ])
            statement = statement.on_conflict_do_update(
                index_elements=[table.c.network_id, table.c.building_id],
                index_where=table.c.deleted_at.is_(None),
                set_={**{name: statement.excluded[name] for name in CAMPUS_BUILDING_FIELDS},
                      "updated_at": func.now()},
            )
            await self._db.execute(statement)

    async def soft_delete_absent(self, network_id: uuid.UUID, keep_building_ids: Iterable[str]) -> int:
        """Soft-delete active buildings not named in ``keep_building_ids`` (one UPDATE)."""
        table = CampusBuildingRecord.__table__
        keep = sorted(set(keep_building_ids))
        statement = update(table).where(table.c.network_id == network_id, table.c.deleted_at.is_(None))
        if keep:
            statement = statement.where(table.c.building_id.not_in(keep))
        result = await self._db.execute(
            statement.values(deleted_at=func.now(), updated_at=func.now()).returning(table.c.campus_building_id)
        )
        return len(result.scalars().all())

    async def list_active_by_building_ids(
        self, network_id: uuid.UUID, building_ids: Sequence[str],
    ) -> dict[str, CampusBuildingRecord]:
        if not building_ids:
            return {}
        result = await self._db.execute(
            select(CampusBuildingRecord).where(
                CampusBuildingRecord.network_id == network_id,
                CampusBuildingRecord.building_id.in_(list(building_ids)),
                CampusBuildingRecord.deleted_at.is_(None),
            ).execution_options(populate_existing=True)
        )
        return {row.building_id: row for row in result.scalars().all()}


class CampusModelAssetRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def lock_digest(self, digest: str) -> None:
        """Transaction lock fencing blob publication/reference against collection."""
        await self._db.execute(select(func.pg_advisory_xact_lock(_asset_digest_lock_key(digest))))

    async def digest_referenced(self, digest: str) -> bool:
        """Whether *any* asset row (active, retired or inline) names ``digest``."""
        return await self._db.scalar(select(CampusModelAssetRecord.campus_model_asset_id).where(
            CampusModelAssetRecord.model_sha256 == digest,
        ).limit(1)) is not None

    async def referenced_digests(self, digests: Sequence[str]) -> set[str]:
        if not digests:
            return set()
        rows = await self._db.scalars(select(CampusModelAssetRecord.model_sha256).where(
            CampusModelAssetRecord.model_sha256.in_(list(digests)),
        ).distinct())
        return set(rows.all())

    async def active_usage(self, network_id: uuid.UUID) -> tuple[int, int]:
        """(bytes, rows) of the network's ACTIVE assets — the per-network quota basis."""
        row = (await self._db.execute(select(
            func.coalesce(func.sum(CampusModelAssetRecord.model_size_bytes), 0), func.count(),
        ).where(
            CampusModelAssetRecord.network_id == network_id, CampusModelAssetRecord.deleted_at.is_(None),
        ))).one()
        return int(row[0]), int(row[1])

    async def get_scoped(self, network_id: uuid.UUID, asset_id: uuid.UUID) -> CampusModelAssetRecord | None:
        result = await self._db.execute(select(CampusModelAssetRecord).where(
            CampusModelAssetRecord.network_id == network_id,
            CampusModelAssetRecord.campus_model_asset_id == asset_id,
            CampusModelAssetRecord.deleted_at.is_(None),
        ))
        return result.scalar_one_or_none()

    async def soft_delete(self, row: CampusModelAssetRecord) -> None:
        row.deleted_at = datetime.now(UTC)
        await self._db.flush()

    async def migration_batch(
        self, *, backend: str, limit: int, after: uuid.UUID | None = None,
    ) -> list[CampusModelAssetRecord]:
        query = select(CampusModelAssetRecord).where(CampusModelAssetRecord.storage_backend == backend)
        if after is not None:
            query = query.where(CampusModelAssetRecord.campus_model_asset_id > after)
        result = await self._db.execute(query.order_by(CampusModelAssetRecord.campus_model_asset_id)
                                        .limit(limit).with_for_update())
        return list(result.scalars().all())

    async def list_for_network(self, network_id: uuid.UUID) -> list[CampusModelAssetRecord]:
        result = await self._db.execute(
            select(CampusModelAssetRecord)
            .where(
                CampusModelAssetRecord.network_id == network_id,
                CampusModelAssetRecord.deleted_at.is_(None),
            )
            .order_by(CampusModelAssetRecord.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_page_for_network(
        self, network_id: uuid.UUID, *, page: int, page_size: int,
    ) -> tuple[list[CampusModelAssetRecord], int]:
        """Bounded page of full rows (legacy inline bodies included) for include_data."""
        if page < 1 or not 1 <= page_size <= 10:
            raise ValueError("Inline asset page must be positive and page_size between 1 and 10")
        scope = (CampusModelAssetRecord.network_id == network_id, CampusModelAssetRecord.deleted_at.is_(None))
        total = await self._db.scalar(select(func.count()).select_from(CampusModelAssetRecord).where(*scope))
        result = await self._db.execute(
            select(CampusModelAssetRecord).where(*scope)
            .order_by(CampusModelAssetRecord.created_at.asc(), CampusModelAssetRecord.campus_model_asset_id.asc())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().all()), total

    async def list_metadata_for_network(self, network_id: uuid.UUID, *, page: int, page_size: int):
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("Asset page must be positive and page_size between 1 and 100")
        table = CampusModelAssetRecord.__table__
        scope = (table.c.network_id == network_id, table.c.deleted_at.is_(None))
        total = await self._db.scalar(select(func.count()).select_from(table).where(*scope))
        # Explicit projection avoids loading even legacy inline bodies into the identity map.
        columns = [column for column in table.c if column.name != "model_data_base64"]
        result = await self._db.execute(
            select(*columns).where(*scope)
            .order_by(table.c.created_at.asc(), table.c.campus_model_asset_id.asc())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.mappings().all()), total

    async def get_latest_for_network(self, network_id: uuid.UUID) -> CampusModelAssetRecord | None:
        result = await self._db.execute(
            select(CampusModelAssetRecord)
            .where(
                CampusModelAssetRecord.network_id == network_id,
                CampusModelAssetRecord.deleted_at.is_(None),
            )
            .order_by(CampusModelAssetRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def soft_delete_for_network(self, network_id: uuid.UUID) -> int:
        """Retire every active asset of the network in one UPDATE (bytes are retained)."""
        table = CampusModelAssetRecord.__table__
        result = await self._db.execute(
            update(table).where(table.c.network_id == network_id, table.c.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now()).returning(table.c.campus_model_asset_id)
        )
        return len(result.scalars().all())

    async def create(
        self,
        *,
        network_id: uuid.UUID,
        model_file_name: str,
        model_mime_type: str,
        model_data_base64: str | None,
        model_sha256: str,
        model_size_bytes: int,
        mapping_by_device_id: dict[str, str],
        source: str | None,
        storage_backend: str = "inline",
        registration: dict | None = None,
    ) -> CampusModelAssetRecord:
        row = CampusModelAssetRecord(
            network_id=network_id,
            model_file_name=model_file_name,
            model_mime_type=model_mime_type,
            model_data_base64=model_data_base64,
            storage_backend=storage_backend,
            registration=registration,
            model_sha256=model_sha256,
            model_size_bytes=model_size_bytes,
            mapping_by_device_id=mapping_by_device_id,
            source=source,
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def update(
        self,
        row: CampusModelAssetRecord,
        *,
        model_file_name: str,
        model_mime_type: str,
        model_data_base64: str | None,
        model_sha256: str,
        model_size_bytes: int,
        mapping_by_device_id: dict[str, str],
        source: str | None,
        storage_backend: str = "inline",
        registration: dict | None = None,
    ) -> CampusModelAssetRecord:
        if row.model_sha256 != model_sha256 or row.model_size_bytes != model_size_bytes:
            raise ValueError("asset content identity is immutable")
        row.model_file_name = model_file_name
        row.model_mime_type = model_mime_type
        row.model_data_base64 = model_data_base64
        row.storage_backend = storage_backend
        row.registration = registration
        row.model_sha256 = model_sha256
        row.model_size_bytes = model_size_bytes
        row.mapping_by_device_id = mapping_by_device_id
        row.source = source
        row.deleted_at = None
        await self._db.flush()
        return row


class DeviceGroupRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_groups_for_network(self, network_id: uuid.UUID) -> list[DeviceGroup]:
        result = await self._db.execute(
            select(DeviceGroup)
            .where(
                DeviceGroup.network_id == network_id,
                DeviceGroup.deleted_at.is_(None),
            )
            .order_by(DeviceGroup.group_key.asc())
        )
        return list(result.scalars().all())

    async def list_members_for_group_ids(
        self,
        group_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        if not group_ids:
            return {}

        result = await self._db.execute(
            select(DeviceGroupMember.device_group_id, DeviceGroupMember.device_id)
            .where(
                DeviceGroupMember.device_group_id.in_(group_ids),
                DeviceGroupMember.deleted_at.is_(None),
            )
            .order_by(DeviceGroupMember.device_group_id.asc(), DeviceGroupMember.device_id.asc())
        )
        rows = result.all()

        members: dict[uuid.UUID, list[uuid.UUID]] = {}
        for group_id, device_id in rows:
            bucket = members.get(group_id)
            if bucket is None:
                members[group_id] = [device_id]
            else:
                bucket.append(device_id)
        return members

    async def get_active_by_keys(self, network_id: uuid.UUID, group_keys: Sequence[str]) -> dict[str, DeviceGroup]:
        if not group_keys:
            return {}
        result = await self._db.execute(
            select(DeviceGroup).where(
                DeviceGroup.network_id == network_id,
                DeviceGroup.group_key.in_(list(group_keys)),
                DeviceGroup.deleted_at.is_(None),
            ).execution_options(populate_existing=True)
        )
        return {row.group_key: row for row in result.scalars().all()}

    async def get_groups_by_ids(self, group_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, DeviceGroup]:
        if not group_ids:
            return {}
        result = await self._db.execute(
            select(DeviceGroup).where(DeviceGroup.device_group_id.in_(list(group_ids)))
            .execution_options(populate_existing=True)
        )
        return {row.device_group_id: row for row in result.scalars().all()}

    async def upsert_group(
        self,
        *,
        network_id: uuid.UUID,
        group_key: str,
        name: str,
        group_type: str,
        description: str | None,
        selector: dict[str, str],
    ) -> uuid.UUID:
        """Create (or, on a concurrent-create race, update) the active group key."""
        table = DeviceGroup.__table__
        statement = insert(table).values(
            device_group_id=uuid.uuid4(), network_id=network_id, group_key=group_key, name=name,
            group_type=group_type, description=description, selector=selector,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.network_id, table.c.group_key],
            index_where=table.c.deleted_at.is_(None),
            set_={"name": statement.excluded.name, "group_type": statement.excluded.group_type,
                  "description": statement.excluded.description, "selector": statement.excluded.selector,
                  "updated_at": func.clock_timestamp()},
        ).returning(table.c.device_group_id)
        return (await self._db.execute(statement)).scalar_one()

    async def update_group(
        self,
        group_id: uuid.UUID,
        *,
        name: str,
        group_type: str,
        description: str | None,
        selector: dict[str, str],
    ) -> None:
        # clock_timestamp() (not transaction now()) keeps C8 versions strictly
        # increasing across serialized writers that started in the same instant.
        table = DeviceGroup.__table__
        await self._db.execute(update(table).where(table.c.device_group_id == group_id).values(
            name=name, group_type=group_type, description=description, selector=selector,
            updated_at=func.clock_timestamp(),
        ))

    async def apply_member_diff(
        self, group_id: uuid.UUID, *, add: Sequence[uuid.UUID], remove: Sequence[uuid.UUID],
    ) -> None:
        """Soft-delete removed memberships and insert only the missing ones."""
        members = DeviceGroupMember.__table__
        if remove:
            await self._db.execute(update(members).where(
                members.c.device_group_id == group_id, members.c.device_id.in_(list(remove)),
                members.c.deleted_at.is_(None),
            ).values(deleted_at=func.now()))
        for chunk in _chunks(list(add), 1000):
            statement = insert(members).values([
                {"device_group_member_id": uuid.uuid4(), "device_group_id": group_id, "device_id": device_id}
                for device_id in chunk
            ])
            await self._db.execute(statement.on_conflict_do_nothing(
                index_elements=[members.c.device_group_id, members.c.device_id],
                index_where=members.c.deleted_at.is_(None),
            ))

    async def soft_delete_absent(self, network_id: uuid.UUID, keep_group_keys: Iterable[str]) -> list[uuid.UUID]:
        """Soft-delete active groups (and their memberships) not named in ``keep_group_keys``."""
        table = DeviceGroup.__table__
        keep = sorted(set(keep_group_keys))
        statement = update(table).where(table.c.network_id == network_id, table.c.deleted_at.is_(None))
        if keep:
            statement = statement.where(table.c.group_key.not_in(keep))
        result = await self._db.execute(
            statement.values(deleted_at=func.now(), updated_at=func.clock_timestamp())
            .returning(table.c.device_group_id)
        )
        group_ids = list(result.scalars().all())
        if group_ids:
            members = DeviceGroupMember.__table__
            await self._db.execute(update(members).where(
                members.c.device_group_id.in_(group_ids), members.c.deleted_at.is_(None),
            ).values(deleted_at=func.now()))
        return group_ids
