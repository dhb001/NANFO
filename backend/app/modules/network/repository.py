"""NANFO Backend — Network module repository.

All DB operations for the Network module.
networks.workspace_id is a stored UUID reference — no SQL join to Organization (ADR-004, C5).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.network.models import CampusBuildingRecord, Device, Network


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
        result = await self._db.execute(
            select(Network).where(Network.network_id == network_id, Network.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_for_workspace(
        self, workspace_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Network], int]:
        q = select(Network).where(Network.workspace_id == workspace_id, Network.deleted_at.is_(None))
        total = (await self._db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await self._db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
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

    async def update_spatial_ref_id(
        self,
        *,
        network_id: uuid.UUID,
        device_id: uuid.UUID,
        spatial_ref_id: str | None,
    ) -> Device | None:
        device = await self.get_by_id(device_id)
        if device is None:
            return None
        if device.network_id != network_id:
            return None

        device.spatial_ref_id = spatial_ref_id
        await self._db.flush()
        return device

    async def list_for_network(
        self, network_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Device], int]:
        q = select(Device).where(Device.network_id == network_id, Device.deleted_at.is_(None))
        total = (await self._db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await self._db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total


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

    async def get_active_by_network_and_building_id(
        self,
        *,
        network_id: uuid.UUID,
        building_id: str,
    ) -> CampusBuildingRecord | None:
        result = await self._db.execute(
            select(CampusBuildingRecord).where(
                CampusBuildingRecord.network_id == network_id,
                CampusBuildingRecord.building_id == building_id,
                CampusBuildingRecord.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def soft_delete_for_network(self, network_id: uuid.UUID) -> int:
        rows = await self.list_for_network(network_id)
        now = datetime.now(UTC)
        for row in rows:
            row.deleted_at = now
        await self._db.flush()
        return len(rows)

    async def create(
        self,
        *,
        network_id: uuid.UUID,
        building_id: str,
        campus_key: str,
        building_key: str,
        label: str,
        geometry: str,
        x: float,
        z: float,
        base_y: float,
        width: float,
        depth: float,
        height: float,
        floors: int,
        footprint: list,
        wall_material: str | None,
        attenuation_db: float | None,
        source: str | None,
    ) -> CampusBuildingRecord:
        row = CampusBuildingRecord(
            network_id=network_id,
            building_id=building_id,
            campus_key=campus_key,
            building_key=building_key,
            label=label,
            geometry=geometry,
            x=x,
            z=z,
            base_y=base_y,
            width=width,
            depth=depth,
            height=height,
            floors=floors,
            footprint=footprint,
            wall_material=wall_material,
            attenuation_db=attenuation_db,
            source=source,
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def update(
        self,
        row: CampusBuildingRecord,
        *,
        campus_key: str,
        building_key: str,
        label: str,
        geometry: str,
        x: float,
        z: float,
        base_y: float,
        width: float,
        depth: float,
        height: float,
        floors: int,
        footprint: list,
        wall_material: str | None,
        attenuation_db: float | None,
        source: str | None,
    ) -> CampusBuildingRecord:
        row.campus_key = campus_key
        row.building_key = building_key
        row.label = label
        row.geometry = geometry
        row.x = x
        row.z = z
        row.base_y = base_y
        row.width = width
        row.depth = depth
        row.height = height
        row.floors = floors
        row.footprint = footprint
        row.wall_material = wall_material
        row.attenuation_db = attenuation_db
        row.source = source
        row.deleted_at = None
        await self._db.flush()
        return row
