"""Read-only, owner-local simulation history (ADR026)."""

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select, true

from app.modules.network.service import NetworkService
from app.modules.organization.service import WorkspaceService
from app.modules.simulation.models import Simulation


class SimulationSummary(BaseModel):
    simulation_id: uuid.UUID
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    scenario_name: str
    status: str
    created_at: datetime
    updated_at: datetime


class SimulationHistoryPage(BaseModel):
    items: list[SimulationSummary]
    total: int
    page: int
    page_size: int


class SimulationHistoryRepository:
    def __init__(self, db):
        self.db = db

    async def list_page(self, workspace_id, network_id, page, page_size):
        filters = [Simulation.workspace_id == workspace_id]
        if network_id is not None:
            filters.append(Simulation.network_id == network_id)
        # One statement keeps count and page on the same database snapshot, even
        # for an empty page. Project summaries only, never large run outputs.
        count = select(func.count()).select_from(Simulation).where(*filters).subquery()
        rows = select(*[getattr(Simulation, field) for field in SimulationSummary.model_fields]).where(
            *filters,
        ).order_by(Simulation.created_at.desc(), Simulation.simulation_id.desc()).offset(
            (page - 1) * page_size,
        ).limit(page_size).subquery()
        result = (await self.db.execute(select(count, rows).select_from(
            count.outerjoin(rows, true()),
        ).order_by(rows.c.created_at.desc(), rows.c.simulation_id.desc()))).all()
        return SimulationHistoryPage(
            items=[SimulationSummary.model_validate(dict(row._mapping)) for row in result
                   if row._mapping["simulation_id"] is not None],
            total=result[0][0], page=page, page_size=page_size,
        )


class SimulationHistoryService:
    def __init__(self, db, redis):
        self.repository = SimulationHistoryRepository(db)
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
