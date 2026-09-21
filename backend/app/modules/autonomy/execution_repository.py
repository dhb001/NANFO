"""Transactional acceptance, durable uncertainty exclusion and leased recovery."""

import uuid
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.modules.autonomy.execution_contract import AutonomousCommand
from app.modules.autonomy.execution_models import AutonomousExecution, AutonomousResource


class ExecutionRepository:
    def __init__(self, db):
        self.db = db

    async def now(self):
        return await self.db.scalar(select(func.clock_timestamp()))

    async def get(self, execution_id, *, lock=False):
        query = select(AutonomousExecution).where(AutonomousExecution.execution_id == execution_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(query)

    async def stage(self, authorization, installation, resource_id):
        previous = await self.get(authorization.execution_id)
        if previous:
            if (previous.command["authorization"] != authorization.model_dump(mode="json")
                    or previous.resource_id != resource_id
                    or previous.command["installation_sha256"] != installation.sha256):
                raise ValueError("execution_identity_conflict")
            return previous
        await self.db.execute(insert(AutonomousResource).values(resource_id=resource_id, fence=0)
                              .on_conflict_do_nothing())
        resource = await self.db.scalar(select(AutonomousResource).where(
            AutonomousResource.resource_id == resource_id).with_for_update())
        previous = await self.get(authorization.execution_id)
        if previous:
            if (previous.command["authorization"] != authorization.model_dump(mode="json")
                    or previous.resource_id != resource_id
                    or previous.command["installation_sha256"] != installation.sha256):
                raise ValueError("execution_identity_conflict")
            return previous
        # A lease timeout is never proof that no device mutation occurred.
        busy = await self.db.scalar(select(AutonomousExecution.execution_id).where(
            AutonomousExecution.resource_id == resource_id, AutonomousExecution.released.is_(False)))
        if busy:
            raise ValueError("autonomous_resource_owned")
        resource.fence += 1
        from app.modules.autonomy.schemas import SafetyAssessment

        safety = SafetyAssessment.model_validate_json(authorization.safety_evidence_json)
        action = installation.action(safety.action_id)
        command = AutonomousCommand(**{key: getattr(authorization, key) for key in (
            "execution_id", "intent_id", "decision_id", "network_id", "workspace_id")},
            resource_id=resource_id, fence=resource.fence, authorization=authorization,
            installation_sha256=installation.sha256, plan=action.plan)
        row = AutonomousExecution(execution_id=authorization.execution_id, decision_id=authorization.decision_id,
            network_id=authorization.network_id, workspace_id=authorization.workspace_id,
            resource_id=resource_id, fence=resource.fence, command=command.model_dump(mode="json"),
            phase="accepted", released=False, cancel_requested=False)
        self.db.add(row)
        await self.db.flush()
        return row

    async def claim(self, resource_id, *, seconds=30, execution_id=None, recovery_only=False):
        query = select(AutonomousExecution).where(
            AutonomousExecution.resource_id == resource_id, AutonomousExecution.released.is_(False),
            or_(AutonomousExecution.lease_until.is_(None), AutonomousExecution.lease_until <= func.clock_timestamp()),
        )
        if execution_id is not None:
            query = query.where(AutonomousExecution.execution_id == execution_id)
        if recovery_only:
            if execution_id is None:
                raise ValueError("exact_recovery_execution_required")
            query = query.where(AutonomousExecution.cancel_requested.is_(True))
        row = await self.db.scalar(query.order_by(AutonomousExecution.updated_at).with_for_update(skip_locked=True).limit(1))
        if row:
            row.lease_token = uuid.uuid4()
            row.lease_until = await self.now() + timedelta(seconds=seconds)
        return row

    async def owned(self, command, token):
        row = await self.get(command.execution_id, lock=True)
        expected = command.model_copy(update={"operation": "execute"}).model_dump(mode="json")
        now = await self.now()
        if (row is None or row.command != expected or row.released or row.lease_token != token
                or row.lease_until is None or row.lease_until <= now):
            raise ValueError("receiver_ownership_or_lease_lost")
        resource = await self.db.get(AutonomousResource, row.resource_id)
        if resource is None or resource.fence != row.fence:
            raise ValueError("receiver_fence_changed")
        row.lease_until = now + timedelta(seconds=30)
        row.updated_at = now
        return row

    async def reference(self, reference, *, lock=False):
        row = await self.get(reference.execution_id, lock=lock)
        if row is None or any(str(row.command[key]) != str(getattr(reference, key)) for key in (
                "network_id", "workspace_id", "intent_id", "decision_id", "execution_id")):
            raise ValueError("owned_execution_identity_mismatch")
        # Current control revision/claim may change after STOP; not recovery capabilities.
        return row
