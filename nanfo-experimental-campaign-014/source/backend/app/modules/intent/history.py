"""Read-only, owner-local intent history (ADR026)."""

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select, true

from app.modules.intent.models import Intent
from app.modules.network.service import NetworkService
from app.modules.organization.service import WorkspaceService


class IntentSummary(BaseModel):
    intent_id: uuid.UUID
    network_id: uuid.UUID | None
    workspace_id: uuid.UUID
    action: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class IntentHistoryPage(BaseModel):
    items: list[IntentSummary]
    total: int
    page: int
    page_size: int


class IntentHistoryRepository:
    def __init__(self, db):
        self.db = db

    async def list_page(self, workspace_id, network_id, page, page_size):
        filters = [Intent.workspace_id == workspace_id]
        if network_id is not None:
            filters.append(Intent.network_id == network_id)
        count = select(func.count()).select_from(Intent).where(*filters).subquery()
        columns = [getattr(Intent, field) for field in IntentSummary.model_fields if field != "action"]
        columns.append(func.substr(Intent.intent_payload["action"].astext, 1, 120).label("action"))
        rows = select(*columns).where(*filters).order_by(
            Intent.created_at.desc(), Intent.intent_id.desc(),
        ).offset((page - 1) * page_size).limit(page_size).subquery()
        result = (await self.db.execute(select(count, rows).select_from(
            count.outerjoin(rows, true()),
        ).order_by(rows.c.created_at.desc(), rows.c.intent_id.desc()))).all()
        return IntentHistoryPage(
            items=[IntentSummary.model_validate(dict(row._mapping)) for row in result
                   if row._mapping["intent_id"] is not None],
            total=result[0][0], page=page, page_size=page_size,
        )


class IntentHistoryService:
    def __init__(self, db, redis):
        self.repository = IntentHistoryRepository(db)
        self.workspaces = WorkspaceService(db=db, redis=redis)
        self.networks = NetworkService(db=db, redis=redis)

    async def list_page(self, *, workspace_id, network_id, user_id, claim_org_id, page, page_size):
        await self.workspaces.get_active_workspace(
            workspace_id, user_id=user_id, claim_org_id=claim_org_id,
        )
        if network_id is not None:
            await self.networks.assert_network_workspace_access(
                network_id=network_id, requested_workspace_id=workspace_id,
                actor_user_id=user_id, claim_org_id=claim_org_id,
            )
        return await self.repository.list_page(workspace_id, network_id, page, page_size)
