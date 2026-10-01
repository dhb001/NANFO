"""Short, explicit transactions; ownership survives lease expiration and failures.

ADR-028: every lease decision (grant, renewal, ownership, recovery stealing) uses the
database clock (``clock_timestamp()`` read after the row locks are held), so competing
workers/API processes on hosts with skewed clocks agree on lease expiry.
"""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from .models import LabAction, LabReceipt, LabResource, LabRun
from .schemas import contract_digest, utcnow


class LabRepository:
    def __init__(self, db):
        self.db = db
        self.clock = None

    async def now(self):
        """Database clock (not the transaction start and not this host's clock)."""
        value = await self.db.scalar(select(func.clock_timestamp()))
        if value is None or getattr(value, "tzinfo", None) is None:
            raise ValueError("experimental_database_clock_unavailable")
        self.clock = value
        return value

    def renew(self, run, seconds):
        if self.clock is None:
            raise ValueError("experimental_database_clock_unavailable")
        run.lease_until = self.clock + timedelta(seconds=seconds)
        return run.lease_until

    async def lock(self, policy):
        resource = await self.db.scalar(select(LabResource).where(
            LabResource.resource_id == policy.runtime.resource_id).with_for_update())
        run = await self.db.scalar(select(LabRun).where(LabRun.run_id == policy.run_id).with_for_update())
        if run is None or run.policy_sha256 != contract_digest(policy):
            raise ValueError("experimental_run_policy_mismatch")
        await self.now()  # after any lock wait
        return resource, run

    async def create(self, policy, token, *, stopping=False):
        await self.db.execute(insert(LabResource).values(resource_id=policy.runtime.resource_id, fence=0)
                              .on_conflict_do_nothing())
        resource = await self.db.scalar(select(LabResource).where(
            LabResource.resource_id == policy.runtime.resource_id).with_for_update())
        existing = await self.db.get(LabRun, policy.run_id)
        if existing is not None and stopping:
            if existing.policy_sha256 != contract_digest(policy):
                raise ValueError("experimental_run_policy_mismatch")
            return existing
        if existing is not None:
            raise ValueError("experimental_run_exists_recover_required")
        if resource.owner_run_id is not None:
            raise ValueError("experimental_resource_owned_recover_required")
        resource.fence += 1
        resource.owner_run_id = policy.run_id
        now = await self.now()
        run = LabRun(run_id=policy.run_id, resource_id=resource.resource_id, fence=resource.fence,
            policy=policy.model_dump(mode="json"), policy_sha256=contract_digest(policy),
            stopped=False, released=False, phase="observing", action_count=0,
            lease_token=token, lease_until=now + timedelta(seconds=policy.lease_seconds), created_at=now)
        self.db.add(run)
        await self.db.flush()
        self.receipt(run, None, "admitted", {"policy_sha256": run.policy_sha256})
        return run

    def owned(self, resource, run, token):
        if self.clock is None:
            raise ValueError("experimental_database_clock_unavailable")
        if (run.released or resource.owner_run_id != run.run_id or resource.fence != run.fence
                or run.lease_token != token or run.lease_until is None or run.lease_until <= self.clock):
            raise ValueError("experimental_ownership_or_lease_lost")

    async def claim_recovery(self, policy, token):
        resource, run = await self.lock(policy)
        if run.released:
            return run
        if (resource.owner_run_id != run.run_id or resource.fence != run.fence
                or (run.lease_token != token and run.lease_until is not None and run.lease_until > self.clock)):
            raise ValueError("experimental_recovery_busy_or_foreign")
        run.lease_token = token
        self.renew(run, policy.lease_seconds)
        run.stopped = True
        return run

    async def pending(self, run_id):
        return await self.db.scalar(select(LabAction).where(LabAction.run_id == run_id,
            LabAction.phase.not_in(("restored", "rejected"))).with_for_update())

    async def count_window(self, run_id, seconds):
        return await self.db.scalar(select(func.count()).select_from(LabAction).where(
            LabAction.run_id == run_id, LabAction.dispatched_at >= utcnow() - timedelta(seconds=seconds)))

    def receipt(self, run, action, kind, payload):
        self.db.add(LabReceipt(receipt_id=uuid4(), run_id=run.run_id,
            request_id=action.request_id if action else None, kind=kind, payload=payload,
            payload_sha256=contract_digest(payload), created_at=utcnow()))

    def release(self, resource, run):
        resource.owner_run_id = None
        run.released, run.phase = True, "restored"
        run.lease_token, run.lease_until = None, None
        self.receipt(run, None, "released", {"fence": run.fence})
