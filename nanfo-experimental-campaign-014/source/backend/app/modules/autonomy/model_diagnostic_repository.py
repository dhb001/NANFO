"""Only diagnostics-owned INSERT and bounded scoped SELECT; no lifecycle events."""

from sqlalchemy import select

from app.modules.autonomy.model_diagnostic_models import ModelDiagnostic
from app.modules.autonomy.model_diagnostic_schemas import ModelDiagnosticRecord


class ModelDiagnosticRepository:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def response(row):
        return ModelDiagnosticRecord.model_validate({name: getattr(row, name)
            for name in ModelDiagnosticRecord.model_fields})

    async def history(self, network_id, workspace_id, limit):
        rows = await self.db.scalars(select(ModelDiagnostic).where(
            ModelDiagnostic.network_id == network_id, ModelDiagnostic.workspace_id == workspace_id,
        ).order_by(ModelDiagnostic.created_at.desc(), ModelDiagnostic.diagnostic_id.desc()).limit(limit))
        return [self.response(row) for row in rows]

    async def insert(self, *, network_id, workspace_id, actor_id, result):
        row = ModelDiagnostic(network_id=network_id, workspace_id=workspace_id,
                              actor_id=actor_id, result=result.model_dump(mode="json"))
        self.db.add(row)
        await self.db.flush()
        return self.response(row)
