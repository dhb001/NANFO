"""ADR-018 exact-enrolled compensation contract, never a new execution authority."""

import asyncio
import json
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException

from app.core.config import get_settings
from app.modules.intent.execution import project_execution
from app.modules.intent.lab import (
    LabCommand,
    LabResult,
    Mailbox,
    digest,
    read_bounded_file,
    verified_completion,
    verified_no_mutation,
    verified_rollback,
)
from app.modules.intent.repository import ExecutionRepository, IntentRepository

ENROLLMENT_MAX_AGE_SECONDS = 30


class IntentOverrideService:
    def __init__(self, db, redis, *, mailbox=None):
        self.db, self.redis = db, redis
        self.repo = ExecutionRepository(db)
        self.mailbox = mailbox

    def transport(self):
        return self.mailbox or Mailbox(get_settings())

    async def inspect_override_execution(self, *, network_id, workspace_id, intent_id, execution_id, actor_id, override_id):
        """Read-only enrollment evidence. No command publication, including replay."""
        from app.modules.identity.service import AuthService
        from app.modules.network.service import NetworkService

        profile = await AuthService(self.db, self.redis).get_profile(actor_id)
        if not {"write:config", "execute:rollback"}.issubset(profile.permissions):
            raise HTTPException(403, detail="Execution permissions required.")
        await NetworkService(self.db, self.redis).assert_network_workspace_access(
            network_id=network_id, requested_workspace_id=workspace_id, actor_user_id=actor_id, require_write=True)
        job = await self.repo.get_execution(execution_id)
        intent = await IntentRepository(self.db).get_by_id(intent_id)
        if (job is None or intent is None or job.intent_id != intent_id or job.workspace_id != workspace_id
                or intent.workspace_id != workspace_id or intent.network_id != network_id or job.actor_id != actor_id):
            raise HTTPException(404, detail="Owned manual execution not found.")
        if job.phase != "completed" or job.blocks_lab or job.cancel_requested or job.dispatched_at is None:
            raise HTTPException(409, detail="Verified current manual execution required.")
        try:
            command = LabCommand.model_validate_json(json.dumps(job.command))
            if command.operation != "execute" or command.plan.operation == "restore":
                raise ValueError("not an active policy")
            mailbox = self.transport()
            result = await mailbox.read(execution_id)
            # A completion receipt alone may outlive the policy. The operator journal
            # is read-only here; if not accessible enrollment fails closed.
            journal = json.loads(await asyncio.to_thread(read_bounded_file, mailbox.results / ".journal.json", 1024 * 1024))
            record = journal["records"][str(execution_id)]
            recorded = LabResult.model_validate_json(json.dumps(record["result"]))
            now = datetime.now(UTC)
            if (journal["active"] != str(execution_id) or journal["blocked"] is not False
                    or record["phase"] != "terminal" or record.get("restored_by") or record.get("recovered_obsolete")
                    or record["command"] != command.model_dump(mode="json") or result is None
                    or result.model_dump() != recorded.model_dump() or not result.matches(command)
                    or result.status != "completed" or result.rollback is not None
                    or result.completed_at < job.approved_at
                    or not 0 <= (now - result.completed_at).total_seconds() <= ENROLLMENT_MAX_AGE_SECONDS
                    or not verified_completion(result.verification)
                    or result.verification["probe"].get("source_host") != command.plan.source_host
                    or result.verification["probe"].get("destination_host") != command.plan.destination_host):
                raise ValueError("stale or inactive execution")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(409, detail="Fresh current journal ownership and verified receipt required.") from exc
        return {"override_id": str(override_id), "network_id": str(network_id), "workspace_id": str(workspace_id),
            "intent_id": str(intent_id), "execution_id": str(execution_id), "actor_id": actor_id,
            "command_sha256": digest(job.command), "plan_hash": command.plan_hash,
            "binding_digest": command.binding_digest, "run_id": str(command.run_id),
            "configuration_verified_at": result.completed_at.isoformat(), "capability": secrets.token_hex(32)}

    async def restore_override(self, reference):
        """Only an exact persisted restoring enrollment can request durable cancel.

        No actor impersonation or arbitrary command input. Intent owns all SQL and
        cancellation projection; Autonomy proves enrollment through its public read.
        """
        from app.modules.autonomy.overrides import verify_override_enrollment

        if not await verify_override_enrollment(self.db, reference):
            raise HTTPException(403, detail="Exact restoring enrollment required.")
        execution_id = uuid.UUID(reference["execution_id"])
        job = await self.repo.get_execution(execution_id, lock=True)
        intent = await IntentRepository(self.db).get_by_id(uuid.UUID(reference["intent_id"]))
        if (job is None or intent is None or str(job.intent_id) != reference["intent_id"]
                or str(job.workspace_id) != reference["workspace_id"] or str(intent.workspace_id) != reference["workspace_id"]
                or str(intent.network_id) != reference["network_id"] or job.actor_id != reference["actor_id"]
                or digest(job.command) != reference["command_sha256"]):
            raise HTTPException(409, detail="Enrolled execution identity changed.")
        command = LabCommand.model_validate_json(json.dumps(job.command))
        # Repeated cancelled-but-unverified outcomes must reacquire the Intent
        # worker gate, not become a permanent no-op through request_cancel's CAS.
        try:
            result = LabResult.model_validate_json(json.dumps(job.result)) if job.result else None
        except (ValueError, TypeError):
            result = None
        safe = bool(result and result.matches(command) and result.status == "cancelled"
                    and result.completed_at >= job.approved_at and result.completed_at <= datetime.now(UTC)
                    and result.completed_at >= datetime.fromisoformat(reference["configuration_verified_at"])
                    and (verified_rollback(result.rollback) or (result.rollback is None and verified_no_mutation(result.verification))))
        if safe and job.phase == "cancelled" and not job.blocks_lab:
            return {"execution_id": str(execution_id), "status": "cancelled", "safe_to_release": True,
                    "evidence": ["intent:verified_cancellation:" + digest(result.model_dump(mode="json"))],
                    "result": result.model_dump(mode="json")}
        changed = not job.cancel_requested
        job.cancel_requested, job.blocks_lab, job.phase = True, True, "cancelling"
        if changed:
            job.cancelled_by_user_id = None
            job.cancellation_requested_at = datetime.now(UTC)
        project_execution(intent, job, event=changed, db=self.db)
        await self.db.commit()
        return {"execution_id": str(execution_id), "status": "pending", "safe_to_release": False,
                "evidence": [], "reasons": ["awaiting_verified_cancellation"]}

    async def validate_override_reference(self, reference):
        """Fence a manual cancellation racing enrollment until the caller commits."""
        job = await self.repo.get_execution(uuid.UUID(reference["execution_id"]), lock=True)
        if (job is None or job.phase != "completed" or job.blocks_lab or job.cancel_requested
                or str(job.intent_id) != reference["intent_id"] or str(job.workspace_id) != reference["workspace_id"]
                or job.actor_id != reference["actor_id"] or digest(job.command) != reference["command_sha256"]):
            raise HTTPException(409, detail="Manual execution changed before enrollment.")
