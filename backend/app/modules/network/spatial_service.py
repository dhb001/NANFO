"""Public Network spatial service: authorization, owner persistence, atomic audit."""

import hashlib
import json
import uuid

import redis.asyncio as aioredis
from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.service import append_audit_log
from app.modules.network.service import NetworkService
from app.modules.network.spatial_repository import SpatialSceneRepository
from app.modules.network.spatial_schemas import (
    MAX_REVISION,
    ReplaceSpatialSceneRequest,
    Revision,
    SpatialHistoryList,
    SpatialHistoryQuery,
    SpatialSceneDocument,
)
from app.modules.network.spatial_transforms import world_geometry


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


def _correlation_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, value)


class SpatialSceneService:
    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._repo = SpatialSceneRepository(db)
        self._network = NetworkService(db=db, redis=redis)

    async def get_scene(
        self, *, network_id: uuid.UUID, actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
    ) -> SpatialSceneDocument:
        await self._network.assert_network_workspace_access(
            network_id=network_id, actor_user_id=actor_user_id,
            requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
        )
        return await self._repo.get(network_id)

    async def list_history(
        self, *, network_id: uuid.UUID, actor_user_id: str, page: int = 1, page_size: int = 20,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
    ) -> SpatialHistoryList:
        query = SpatialHistoryQuery(page=page, page_size=page_size)
        self._db.expire_all()
        await self._network.assert_network_workspace_access(
            network_id=network_id, actor_user_id=actor_user_id,
            requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
        )
        return await self._repo.list_history(network_id, query)

    async def get_revision(
        self, *, network_id: uuid.UUID, revision: int, actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
    ) -> SpatialSceneDocument:
        revision = TypeAdapter(Revision).validate_python(revision)
        self._db.expire_all()
        await self._network.assert_network_workspace_access(
            network_id=network_id, actor_user_id=actor_user_id,
            requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
        )
        result = await self._repo.get_revision(network_id, revision)
        if result is None:
            raise HTTPException(status_code=404, detail={
                "code": "SPATIAL_REVISION_NOT_FOUND", "message": "Spatial scene revision not found.",
            })
        return result

    async def replace_scene(
        self, *, network_id: uuid.UUID, req: ReplaceSpatialSceneRequest,
        actor_user_id: str, correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
    ) -> SpatialSceneDocument:
        # Revalidate internal callers as well as router inputs before touching storage.
        req = ReplaceSpatialSceneRequest.model_validate(req.model_dump())
        try:
            world_geometry(req.scene)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={
                "code": "SPATIAL_GEOMETRY_INVALID",
                "message": "Geometry exceeds supported world bounds or numerical resolution.",
            }) from exc
        try:
            await self._network.assert_network_workspace_access(
                network_id=network_id, actor_user_id=actor_user_id, require_write=True,
                requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
            )
            if not await self._repo.lock_active_network(network_id):
                raise HTTPException(status_code=404, detail="Network not found.")
            if req.expected_revision == MAX_REVISION:
                raise _conflict("SPATIAL_REVISION_EXHAUSTED", "Spatial scene revision limit reached.")
            devices = {obj.device_id for obj in req.scene.objects if obj.device_id is not None}
            if devices != await self._repo.active_device_ids(network_id, devices):
                raise HTTPException(status_code=422, detail={
                    "code": "SPATIAL_DEVICE_SCOPE_INVALID",
                    "message": "Every associated device must be active in this network.",
                })
            scene = req.scene.model_dump(mode="json")
            result = SpatialSceneDocument(**scene, revision=req.expected_revision + 1)
            digest = hashlib.sha256(json.dumps(
                scene, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
            ).encode("utf-8")).hexdigest()
            await self._repo.lock_scene_for_write(network_id)
            # All owner locks (including first-insert/scene contention) precede this
            # check. READ COMMITTED queries must reload any retained ORM identities
            # so a membership downgrade during a lock wait cannot authorize a write.
            self._db.expire_all()
            network = await self._network.assert_network_workspace_access(
                network_id=network_id, actor_user_id=actor_user_id, require_write=True,
                requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
            )
            if not await self._repo.replace(network_id, req.expected_revision, scene):
                raise _conflict("SPATIAL_REVISION_CONFLICT", "Scene changed; fetch it and reconcile before retrying.")
            await self._repo.append_revision(network_id, result.revision, scene, uuid.UUID(actor_user_id))
            await append_audit_log(
                db=self._db, event_type="network.spatial_scene.replaced", actor_id=uuid.UUID(actor_user_id),
                resource_type="network_spatial_scene", resource_id=network_id,
                correlation_id=_correlation_uuid(correlation_id), metadata={
                    "network_id": str(network_id), "workspace_id": str(network.workspace_id),
                    "previous_revision": req.expected_revision, "revision": result.revision,
                    "object_count": len(scene["objects"]), "scene_sha256": digest,
                },
            )
            await self._db.commit()
            return result
        except BaseException:
            # Cancellation must also release locks and discard a pending owner/audit write.
            await self._db.rollback()
            raise
