"""ADR-012 fail-closed pipeline, persistence transitions and provider boundary tests."""

import asyncio
import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.modules.autonomy.providers import (
    TelemetryObserver,
    UnavailableRecovery,
    installed_providers,
)
from app.modules.autonomy.repository import AutonomyRepository
from app.modules.autonomy.schemas import (
    SafetyAssessment,
    SetAutonomyRequest,
    Verification,
    contract_digest,
)
from app.modules.autonomy.service import AutonomyService, approval_reasons, readiness
from app.modules.autonomy.worker import AutonomyWorker, validate_safety
from tests.autonomy_support import (
    HASH,
    MemoryRepository,
    certified_assessment,
    control_record,
    qualified_providers,
    sessions_for,
)


@pytest.fixture
def setup(monkeypatch, mock_db, fake_redis):
    control = control_record()
    repo = MemoryRepository(control)
    providers = qualified_providers(control)
    monkeypatch.setattr("app.modules.autonomy.worker.AutonomyRepository", lambda db: repo)
    monkeypatch.setattr("app.modules.autonomy.service.AutonomyRepository", lambda db: repo)
    auth = AsyncMock(return_value=(control, ["read:telemetry", "write:config", "execute:rollback"]))
    monkeypatch.setattr("app.modules.autonomy.worker.authorize", auth)
    monkeypatch.setattr("app.modules.autonomy.service.authorize", auth)
    # Organization-service lookups are covered by governance/endpoint tests; here the actor is Admin.
    audit = AsyncMock()
    monkeypatch.setattr("app.modules.autonomy.governance.audit", audit)
    monkeypatch.setattr("app.modules.autonomy.governance.caller_org_role", AsyncMock(return_value="Admin"))
    monkeypatch.setattr("app.modules.autonomy.governance.require_distinct_approver", lambda: False)
    worker = AutonomyWorker(sessions=sessions_for(mock_db), redis=fake_redis, providers=providers)
    service = AutonomyService(mock_db, fake_redis, providers=providers)
    claims = SimpleNamespace(user_id=control.approved_by_user_id, workspace_id=None, org_id=None)
    return SimpleNamespace(control=control, repo=repo, providers=providers, worker=worker,
                           service=service, claims=claims, auth=auth, db=mock_db, audit=audit)


async def test_installed_readiness_never_qualifies_or_infers(mock_db, fake_redis):
    providers = installed_providers(sessions_for(mock_db), fake_redis)
    reasons, qualification = await readiness(providers, HASH)
    assert {"qualified_checkpoint_unavailable", "observation_contract_incompatible",
            "calibrated_safety_unavailable", "autonomous_executor_unavailable"} <= set(reasons)
    assert not qualification.qualified
    with pytest.raises(RuntimeError):
        await providers.executor.accept(None, None)


async def test_default_autonomous_put_rejects_without_mutation(setup, fake_redis):
    setup.service.providers = installed_providers(sessions_for(setup.db), fake_redis)
    before = setup.control.revision
    with pytest.raises(HTTPException) as error:
        await setup.service.set_mode(claims=setup.claims, request=SetAutonomyRequest(
            network_id=setup.control.network_id, expected_revision=setup.control.revision, mode="autonomous", checkpoint_sha256=HASH,
            approval_expires_at=datetime.now(UTC) + timedelta(minutes=5)))
    assert error.value.status_code == 409
    assert setup.control.revision == before
    assert not setup.repo.rows


@pytest.mark.parametrize("mode", ["monitor", "recommend"])
async def test_non_actuating_modes(setup, mode):
    setup.control.mode = mode
    assert await setup.worker.run_one()
    setup.providers.executor.accept.assert_not_awaited()
    assert setup.repo.rows[-1].status == ("observed" if mode == "monitor" else "recommended")
    if mode == "monitor":
        setup.providers.model.infer.assert_not_awaited()


async def test_monitor_does_not_depend_on_model_readiness(setup):
    setup.control.mode = "monitor"
    setup.providers.model.qualify.side_effect = RuntimeError("uninstalled")
    await setup.worker.run_one()
    assert setup.repo.rows[-1].status == "observed"
    setup.providers.model.qualify.assert_not_awaited()


async def test_recommend_does_not_require_executor(setup, fake_redis):
    setup.control.mode = "recommend"
    object.__setattr__(setup.providers, "executor", installed_providers(sessions_for(setup.db), fake_redis).executor)
    await setup.worker.run_one()
    assert setup.repo.rows[-1].status == "recommended"


@pytest.mark.parametrize("field", ["model", "safety", "observer", "executor"])
async def test_each_missing_gate_refuses_acceptance(setup, field, fake_redis):
    installed = installed_providers(sessions_for(setup.db), fake_redis)
    providers = setup.providers
    object.__setattr__(providers, field, getattr(installed, field))
    if field == "observer":
        providers.observer.observe = AsyncMock(return_value=qualified_providers(setup.control).observer.observe.return_value)
    await setup.worker.run_one()
    assert setup.repo.rows[-1].status == "blocked"
    if field != "executor":
        providers.executor.accept.assert_not_awaited()
    assert setup.control.active_execution_id is None


@pytest.mark.parametrize("mutation,reason", [
    ({"observed_at": datetime.now(UTC) - timedelta(minutes=2)}, "observation_stale_or_missing"),
    ({"collected_at": datetime.now(UTC) - timedelta(minutes=2)}, "observation_delayed"),
    ({"compatible": False}, "observation_contract_incompatible"),
    ({"evidence": []}, "observation_evidence_missing"),
    ({"network_id": uuid.uuid4()}, "observation_scope_mismatch"),
])
async def test_observation_validation(setup, mutation, reason):
    setup.providers.observer.observe.return_value = setup.providers.observer.observe.return_value.model_copy(update=mutation)
    await setup.worker.run_one()
    assert reason in setup.repo.rows[-1].reasons
    setup.providers.model.infer.assert_not_awaited()
    setup.providers.executor.accept.assert_not_awaited()
    if reason == "observation_scope_mismatch":
        assert setup.repo.rows[-1].observation is None


async def test_safety_refusal_records_evidence(setup):
    setup.providers.safety.assess.return_value = setup.providers.safety.assess.return_value.model_copy(
        update={"admissible": False, "reasons": ["overload"]})
    await setup.worker.run_one()
    row = setup.repo.rows[-1]
    assert row.status == "blocked" and row.reasons == ["overload"]
    assert row.checkpoint_sha256 == HASH and row.safety and row.observation and row.proposal
    setup.providers.executor.accept.assert_not_awaited()


@pytest.mark.parametrize("expired", [True, False])
async def test_stop_or_expired_approval_blocks_before_observation(setup, expired):
    if expired:
        setup.control.approval_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        setup.control.emergency_stopped = True
    await setup.worker.run_one()
    assert setup.repo.rows[-1].status == "blocked"
    setup.providers.observer.observe.assert_not_awaited()
    setup.providers.executor.accept.assert_not_awaited()


async def test_revocation_immediately_before_acceptance(setup):
    setup.auth.side_effect = [(setup.control, []), HTTPException(403, "revoked")]
    await setup.worker.run_one()
    assert setup.repo.rows[-1].status == "blocked"
    setup.providers.executor.accept.assert_not_awaited()


async def test_stop_race_invalidates_cycle_claim(setup):
    async def stop_during_safety(*args):
        setup.control.emergency_stopped = True
        setup.control.revision += 1
        setup.control.claim_token = None
        return setup.providers.safety.assess.return_value
    setup.providers.safety.assess.side_effect = stop_during_safety
    await setup.worker.run_one()
    setup.providers.executor.accept.assert_not_awaited()


async def test_lease_loss_prevents_stale_result_overwrite(setup):
    decision = setup.repo.record(setup.control, status="observing", reasons=[])
    old = copy.copy(setup.control)
    setup.control.claim_token = uuid.uuid4()
    await setup.worker.finish(old, decision, status="verified", reasons=[])
    assert decision.status == "observing"


async def test_acceptance_is_not_completion_and_retains_owned_identity(setup):
    await setup.worker.run_one()
    setup.providers.executor.accept.assert_awaited_once()
    authorization = setup.providers.executor.accept.call_args.args[1]
    assert setup.control.active_execution_id == authorization.execution_id
    assert setup.control.active_intent_id == authorization.intent_id
    assert setup.repo.rows[-1].status == "uncertain"
    assert "execution_unresolved" in setup.repo.rows[-1].reasons
    assert "manual_approval" not in type(authorization).model_fields


async def test_verified_executor_evidence_required(setup):
    setup.providers.executor.verify.side_effect = lambda identity: Verification(
        execution_id=identity.execution_id, status="verified", safe_to_release=True, evidence=[])
    await setup.worker.run_one()
    assert setup.repo.rows[-1].status == "uncertain"
    assert setup.control.active_execution_id


async def test_test_provider_verified_path_is_reusable(setup):
    setup.providers.executor.verify.side_effect = lambda identity: Verification(
        execution_id=identity.execution_id, status="verified", safe_to_release=True, evidence=["test:readback"])
    await setup.worker.run_one()
    assert setup.repo.rows[-1].status == "verified"
    assert setup.control.active_execution_id is None


async def test_replayed_observation_cannot_execute_twice(setup):
    setup.providers.executor.verify.side_effect = lambda identity: Verification(
        execution_id=identity.execution_id, status="verified", safe_to_release=True, evidence=["test:readback"])
    await setup.worker.run_one()
    await setup.worker.run_one()
    assert "observation_replayed" in setup.repo.rows[-1].reasons
    setup.providers.executor.accept.assert_awaited_once()


async def test_rejected_older_observation_cannot_lower_replay_watermark(setup):
    setup.providers.executor.verify.side_effect = lambda identity: Verification(
        execution_id=identity.execution_id, status="verified", safe_to_release=True, evidence=["test:readback"])
    observation = setup.providers.observer.observe.return_value
    await setup.worker.run_one()
    setup.providers.observer.observe.return_value = observation.model_copy(
        update={"observed_at": observation.observed_at - timedelta(seconds=1)})
    setup.providers.safety.assess.return_value = certified_assessment(
        setup.providers.observer.observe.return_value, setup.providers.model.infer.return_value)
    await setup.worker.run_one()
    setup.providers.observer.observe.return_value = observation
    setup.providers.safety.assess.return_value = certified_assessment(observation, setup.providers.model.infer.return_value)
    await setup.worker.run_one()
    assert setup.repo.rows[-1].status == "blocked"
    assert setup.control.last_accepted_observed_at == observation.observed_at
    setup.providers.executor.accept.assert_awaited_once()


async def test_pending_execution_is_reconciled_never_resubmitted(setup):
    await setup.worker.run_one()
    identity = setup.control.active_execution_id
    await setup.worker.run_one()
    assert setup.control.active_execution_id == identity
    setup.providers.executor.accept.assert_awaited_once()
    assert setup.providers.executor.verify.await_count == 2


@pytest.mark.parametrize("expired", ["approval", "lease"])
async def test_executor_callback_cannot_outlive_authority(setup, expired):
    async def accept(*args):
        field = "approval_expires_at" if expired == "approval" else "lease_expires_at"
        setattr(setup.control, field, datetime.now(UTC) - timedelta(seconds=1))
    setup.providers.executor.accept.side_effect = accept
    await setup.worker.run_one()
    assert setup.control.active_execution_id is None
    setup.db.rollback.assert_awaited()
    setup.providers.executor.verify.assert_not_awaited()


async def test_revocation_during_executor_callback_prevents_commit(setup):
    setup.auth.side_effect = [(setup.control, []), (setup.control, []), HTTPException(403, "revoked")]
    await setup.worker.run_one()
    assert setup.control.active_execution_id is None
    assert "approval_actor_unauthorized" in setup.repo.rows[-1].reasons
    setup.providers.executor.verify.assert_not_awaited()


async def test_expiry_during_verification_cannot_release_execution(setup):
    def verify(identity):
        setup.control.approval_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        return Verification(execution_id=identity.execution_id, status="verified", safe_to_release=True, evidence=["test:readback"])
    setup.providers.executor.verify.side_effect = verify
    await setup.worker.run_one()
    assert setup.control.active_execution_id
    assert setup.repo.rows[-1].status == "uncertain"


async def test_stop_during_verification_fences_completion(setup):
    async def verify(identity):
        setup.providers.recovery.cancel.side_effect = None
        setup.providers.recovery.cancel.return_value = Verification(execution_id=identity.execution_id, status="pending")
        await setup.service.stop(claims=setup.claims, network_id=setup.control.network_id)
        return Verification(execution_id=identity.execution_id, status="verified", safe_to_release=True, evidence=["test:readback"])
    setup.providers.executor.verify.side_effect = verify
    await setup.worker.run_one()
    assert setup.control.emergency_stopped and setup.control.active_execution_id
    assert not any(row.status == "verified" for row in setup.repo.rows)


async def test_repeated_safety_rejection_does_not_dispatch(setup):
    setup.providers.safety.assess.return_value = setup.providers.safety.assess.return_value.model_copy(
        update={"admissible": False, "reasons": ["hold_down"]})
    for _ in range(3):
        await setup.worker.run_one()
    assert all(row.reasons == ["hold_down"] for row in setup.repo.rows)
    setup.providers.executor.accept.assert_not_awaited()


async def test_stop_commits_before_failed_cancellation_and_blocks_mode_change(setup):
    setup.control.active_execution_id, setup.control.active_intent_id = uuid.uuid4(), uuid.uuid4()
    setup.control.active_decision_id = uuid.uuid4()
    async def cancel(reference):
        assert setup.control.emergency_stopped
        setup.db.commit.assert_awaited()
        assert reference.execution_id == setup.control.active_execution_id
        raise RuntimeError("sensitive internal error")
    setup.providers.recovery.cancel.side_effect = cancel
    result = await setup.service.stop(claims=setup.claims, network_id=setup.control.network_id)
    assert result.emergency_stopped and result.cancellation_status == "uncertain"
    assert result.active_execution_id
    assert "sensitive" not in result.model_dump_json()
    with pytest.raises(HTTPException) as error:
        await setup.service.set_mode(claims=setup.claims, request=SetAutonomyRequest(
            network_id=setup.control.network_id, expected_revision=setup.control.revision, mode="monitor"))
    assert error.value.status_code == 409


async def test_stop_without_owned_execution_does_not_cancel_manual_jobs(setup):
    result = await setup.service.stop(claims=setup.claims, network_id=setup.control.network_id)
    assert result.emergency_stopped
    setup.providers.recovery.cancel.assert_not_awaited()
    result = await setup.service.set_mode(claims=setup.claims, request=SetAutonomyRequest(
        network_id=setup.control.network_id, expected_revision=setup.control.revision, mode="monitor"))
    assert not result.emergency_stopped
    assert result.approval_expires_at is None


async def test_late_cancellation_response_cannot_override_newer_stop(setup):
    identity = uuid.uuid4()
    setup.control.active_execution_id, setup.control.active_intent_id = identity, uuid.uuid4()
    setup.control.active_decision_id = uuid.uuid4()
    async def cancel(reference):
        # A newer stop owns the unresolved cancellation state.
        setup.control.revision += 1
        setup.control.cancellation_status = "uncertain"
        return Verification(execution_id=identity, status="cancelled", safe_to_release=True, evidence=["test:old_result"])
    setup.providers.recovery.cancel.side_effect = cancel
    result = await setup.service.stop(claims=setup.claims, network_id=setup.control.network_id)
    assert result.active_execution_id == identity
    assert result.cancellation_status == "uncertain"


async def test_stopping_actor_can_reconcile_after_approver_revocation(setup):
    identity = uuid.uuid4()
    setup.control.active_execution_id, setup.control.active_intent_id = identity, uuid.uuid4()
    setup.control.emergency_stopped = True
    setup.control.stopped_by_user_id = str(uuid.uuid4())
    setup.providers.recovery.cancel.side_effect = None
    setup.providers.recovery.cancel.return_value = Verification(
        execution_id=identity, status="cancelled", safe_to_release=True, evidence=["test:compensation"])
    await setup.worker.run_one()
    setup.providers.executor.verify.assert_awaited_once()
    setup.providers.recovery.cancel.assert_awaited_once()
    assert setup.control.active_execution_id is None


async def test_changed_qualification_manifest_blocks_acceptance(setup):
    qualification = setup.providers.model.qualify.return_value
    setup.providers.model.qualify.side_effect = [qualification, qualification.model_copy(update={"manifest_sha256": "c" * 64})]
    await setup.worker.run_one()
    assert "qualification_changed_before_acceptance" in setup.repo.rows[-1].reasons
    setup.providers.executor.accept.assert_not_awaited()


async def test_readiness_refuses_self_asserted_qualification_without_manifest(setup):
    setup.providers.model.qualify.return_value = setup.providers.model.qualify.return_value.model_copy(
        update={"manifest_sha256": None})
    reasons, _ = await readiness(setup.providers, HASH)
    assert "qualified_checkpoint_unavailable" in reasons


@pytest.mark.parametrize("value", [None, -1, 3601])
async def test_approval_expiry_bounded(setup, value):
    expiry = datetime.now(UTC) + timedelta(seconds=value) if value is not None else None
    with pytest.raises(HTTPException) as error:
        await setup.service.set_mode(claims=setup.claims, request=SetAutonomyRequest(
            network_id=setup.control.network_id, expected_revision=setup.control.revision, mode="autonomous", checkpoint_sha256=HASH,
            approval_expires_at=expiry))
    assert error.value.status_code == 409


def test_requests_reject_paths_manual_approval_and_naive_dates():
    for extra in ({"checkpoint_path": "/tmp/best.json"}, {"manual_approval": True},
                  {"approval_expires_at": "2026-09-09T12:00:00"}, {"checkpoint_sha256": "../best.json"}):
        with pytest.raises(ValidationError):
            SetAutonomyRequest(network_id=uuid.uuid4(), expected_revision=0, mode="autonomous", **extra)


async def test_observer_uses_scoped_real_telemetry_only(monkeypatch, mock_db):
    control = control_record()
    def sample(synthetic):
        return SimpleNamespace(network_id=control.network_id, workspace_id=control.workspace_id,
            record_id=uuid.uuid4(), device_id=uuid.uuid4(), metric="queue_backlog_bytes", value=19., unit="bytes",
            observed_at=datetime.now(UTC), source="emulation", tags={"synthetic": synthetic, "execution_mode": "emulation"})
    query = AsyncMock(return_value=SimpleNamespace(items=[sample(False), sample(True)]))
    monkeypatch.setattr("app.modules.autonomy.providers.TelemetryQueryService.get_history", query)
    result = await TelemetryObserver(sessions_for(mock_db)).observe(control.network_id, control.workspace_id)
    assert len(result.samples) == 1 and result.fresh and not result.compatible
    assert result.reasons == ["observation_contract_incompatible"]
    assert query.call_args.kwargs["workspace_id"] == control.workspace_id
    assert query.call_args.kwargs["network_id"] == control.network_id
    assert "vector" not in result.model_dump()


@pytest.mark.parametrize("released", [True, False])
async def test_stop_cancels_through_real_journal_recovery_not_intent(setup, monkeypatch, released):
    """ADR-028 fix 2: STOP requests exact journal cancellation; the Intent module is never consulted."""
    from app.modules.autonomy.execution_client import JournalRecovery

    identity, intent, decision = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    setup.control.active_execution_id, setup.control.active_intent_id, setup.control.active_decision_id = identity, intent, decision
    command = {key: str(value) for key, value in dict(network_id=setup.control.network_id,
        workspace_id=setup.control.workspace_id, intent_id=intent, decision_id=decision, execution_id=identity).items()}
    result = ({"execution_id": str(identity), "status": "cancelled", "safe_to_release": True,
               "evidence": ["persisted_no_dispatch:" + str(identity)], "reasons": []} if released else None)
    journal = SimpleNamespace(command=command, cancel_requested=False, result=result)
    looked_up = []
    async def reference(self, reference, *, lock=False):
        looked_up.append((reference, lock))
        if any(str(getattr(reference, key)) != value for key, value in command.items()):
            raise ValueError("owned_execution_identity_mismatch")
        return journal
    monkeypatch.setattr("app.modules.autonomy.execution_repository.ExecutionRepository.reference", reference)
    intent_detail = AsyncMock(side_effect=AssertionError("Intent must not be used for autonomous STOP"))
    monkeypatch.setattr("app.modules.intent.service.IntentExecutionService.get_intent_detail", intent_detail)
    object.__setattr__(setup.providers, "recovery", JournalRecovery(sessions_for(setup.db)))
    response = await setup.service.stop(claims=setup.claims, network_id=setup.control.network_id)
    assert journal.cancel_requested is True
    assert looked_up[0][1] is True and looked_up[0][0].execution_id == identity
    intent_detail.assert_not_awaited()
    assert response.emergency_stopped
    assert response.cancellation_status == ("verified" if released else "requested")
    assert (response.active_execution_id is None) == released
    assert setup.control.next_cycle_at <= datetime.now(UTC)
    stopped = next(row for row in setup.repo.rows if row.status == "stopped")
    assert stopped.execution_id == identity and stopped.verification["status"] == ("cancelled" if released else "pending")


async def test_stop_identity_mismatch_is_uncertain_and_keeps_exclusion(setup, monkeypatch):
    from app.modules.autonomy.execution_client import JournalRecovery

    setup.control.active_execution_id, setup.control.active_intent_id = uuid.uuid4(), uuid.uuid4()
    setup.control.active_decision_id = uuid.uuid4()
    async def reference(self, reference, *, lock=False):
        raise ValueError("owned_execution_identity_mismatch")
    monkeypatch.setattr("app.modules.autonomy.execution_repository.ExecutionRepository.reference", reference)
    object.__setattr__(setup.providers, "recovery", JournalRecovery(sessions_for(setup.db)))
    response = await setup.service.stop(claims=setup.claims, network_id=setup.control.network_id)
    assert response.cancellation_status == "uncertain" and response.active_execution_id is not None


async def test_claim_uses_skip_locked_and_db_time(mock_db):
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result
    assert await AutonomyRepository(mock_db).claim() is None
    sql = str(mock_db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql and "lease_expires_at <= now()" in sql


def test_unresolved_cancellation_survives_no_active_identity():
    assert "execution_unresolved" in approval_reasons(control_record(cancellation_status="uncertain"))


@pytest.mark.parametrize("initial", [True, False])
async def test_older_put_cannot_clear_stop_during_readiness(setup, initial):
    if initial:
        setup.repo.control = None
    revision = 0 if initial else setup.control.revision
    entered, release = asyncio.Event(), asyncio.Event()
    async def qualify(_):
        entered.set()
        await release.wait()
        return setup.providers.model.qualify.return_value
    setup.providers.model.qualify.side_effect = qualify
    request = SetAutonomyRequest(network_id=setup.control.network_id, expected_revision=revision,
        mode="autonomous", checkpoint_sha256=HASH, approval_expires_at=datetime.now(UTC) + timedelta(minutes=5))
    task = asyncio.create_task(setup.service.set_mode(claims=setup.claims, request=request))
    await entered.wait()
    # Avoid waiting on provider status when serializing STOP, not its persistence path.
    setup.service.snapshot = AsyncMock()
    await setup.service.stop(claims=setup.claims, network_id=setup.control.network_id)
    stopped_revision = setup.repo.control.revision
    release.set()
    with pytest.raises(HTTPException) as error:
        await task
    assert error.value.detail["code"] == "AUTONOMY_REVISION_CONFLICT"
    assert setup.repo.control.emergency_stopped
    assert setup.repo.control.revision == stopped_revision
    assert [row.status for row in setup.repo.rows] == ["stopped"]


@pytest.mark.parametrize("value", [-1, True, "0", 1.5, None])
def test_expected_revision_requires_nonnegative_integer(value):
    with pytest.raises(ValidationError):
        SetAutonomyRequest(network_id=uuid.uuid4(), mode="monitor", expected_revision=value)


@pytest.mark.parametrize("field", ["selected_action", "certificate", "binding"])
async def test_missing_structured_safety_refuses_dispatch(setup, field):
    setup.providers.safety.assess.return_value = setup.providers.safety.assess.return_value.model_copy(update={field: None})
    await setup.worker.run_one()
    assert "safety_certificate_missing" in setup.repo.rows[-1].reasons
    setup.providers.executor.accept.assert_not_awaited()


@pytest.mark.parametrize("mutation", ["network", "action", "route", "run", "calibration", "certificate", "observation"])
async def test_safety_payload_tampering_refused(setup, mutation):
    safety = setup.providers.safety.assess.return_value.model_copy(deep=True)
    if mutation == "network":
        safety.selected_action.network_id = str(uuid.uuid4())
    elif mutation == "action":
        safety.selected_action.action_id = "changed"
    elif mutation == "route":
        safety.selected_action.routes[0].route_id = "route-A"
    elif mutation == "run":
        safety.selected_action.run_id = "foreign-run"
    elif mutation == "calibration":
        safety.binding.calibration.provider_id = "foreign-provider"
    elif mutation == "certificate":
        safety.certificate.drift.upper_bytes_squared = -99999.
    else:
        safety.binding.observation.queues[0].queue_bytes = 1.
    setup.providers.safety.assess.return_value = safety
    await setup.worker.run_one()
    assert set(setup.repo.rows[-1].reasons) & {"safety_binding_mismatch", "safety_certificate_mismatch"}
    setup.providers.executor.accept.assert_not_awaited()


def test_certificate_expiry_is_exclusive_even_when_observation_fresh(setup):
    safety = setup.providers.safety.assess.return_value
    observation, proposal = setup.providers.observer.observe.return_value, setup.providers.model.infer.return_value
    deadline = datetime.fromtimestamp(safety.certificate.expires_at_unix_seconds, UTC)
    assert (deadline - observation.observed_at).total_seconds() < 1
    assert validate_safety(safety, observation, proposal, now=deadline) == ["safety_certificate_expired"]


@pytest.mark.parametrize("stage", ["readiness", "callback"])
async def test_short_certificate_expires_before_acceptance_commit(setup, monkeypatch, stage):
    safety = setup.providers.safety.assess.return_value
    deadline = datetime.fromtimestamp(safety.certificate.expires_at_unix_seconds, UTC)
    class Clock:
        @staticmethod
        def now(_):
            return deadline
    if stage == "readiness":
        calls = 0
        async def qualify(_):
            nonlocal calls
            calls += 1
            if calls == 2:
                monkeypatch.setattr("app.modules.autonomy.worker.datetime", Clock)
            return setup.providers.model.qualify.return_value
        setup.providers.model.qualify.side_effect = qualify
    else:
        async def accept(*_):
            monkeypatch.setattr("app.modules.autonomy.worker.datetime", Clock)
        setup.providers.executor.accept.side_effect = accept
    await setup.worker.run_one()
    assert "safety_certificate_expired" in setup.repo.rows[-1].reasons
    assert setup.control.active_execution_id is None
    setup.providers.executor.verify.assert_not_awaited()
    if stage == "readiness":
        setup.providers.executor.accept.assert_not_awaited()
    else:
        setup.db.rollback.assert_awaited()


async def test_authorization_retains_immutable_exact_certificate_and_action(setup):
    await setup.worker.run_one()
    authorization = setup.providers.executor.accept.call_args.args[1]
    assert len(setup.providers.executor.accept.call_args.args) == 2
    safety = SafetyAssessment.model_validate_json(authorization.safety_evidence_json)
    assert contract_digest(safety) == authorization.safety_sha256
    assert json.loads(authorization.selected_action_json) == safety.selected_action.model_dump(mode="json")
    assert setup.repo.rows[-1].authorization == authorization.model_dump(mode="json")
    with pytest.raises(ValidationError):
        authorization.selected_action_json = "{}"


async def test_projected_action_not_original_proposal_is_authorized(setup):
    from app.modules.autonomy.safety import SafetyShield, safety_input_digest
    safety = setup.providers.safety.assess.return_value.model_copy(deep=True)
    safety.selected_action.action_id = "projected-alternative"
    safety.selected_action.bounds.action_id = "projected-alternative"
    safety.selected_action.routes[0].route_id = "route-A"
    safety.selected_action.bounds.input_sha256 = safety_input_digest(safety.binding.observation, safety.selected_action.routes)
    result = SafetyShield(safety.binding.policy, safety.binding.calibration).evaluate(
        safety.binding.observation, safety.selected_action, state=safety.binding.state, now=safety.binding.evaluated_at_unix_seconds)
    safety.action_id = safety.selected_action.action_id
    safety.certificate = type(safety.certificate).model_validate(result["certificate"])
    safety.binding.selected_action_sha256 = contract_digest(safety.selected_action)
    setup.providers.safety.assess.return_value = safety
    await setup.worker.run_one()
    authorization = setup.providers.executor.accept.call_args.args[1]
    action = json.loads(authorization.selected_action_json)
    assert action["action_id"] == "projected-alternative"
    assert action["routes"] == [{"demand_id": "demand-1", "route_id": "route-A"}]
    assert setup.repo.rows[-1].proposal["action_id"] == "test-action"


@pytest.mark.parametrize("governed", [True, False])
async def test_revoked_approver_still_verified_then_governed_recovery(setup, governed):
    await setup.worker.run_one()
    identity = setup.control.active_execution_id
    setup.auth.side_effect = HTTPException(403, "revoked")
    if governed:
        setup.providers.recovery.cancel.side_effect = lambda reference: Verification(
            execution_id=reference.execution_id, status="cancelled", safe_to_release=True, evidence=["test:compensation"])
    else:
        object.__setattr__(setup.providers, "recovery", UnavailableRecovery())
    await setup.worker.run_one()
    assert setup.providers.executor.verify.await_count == 2
    reference = setup.providers.executor.verify.call_args.args[0]
    assert reference.execution_id == identity and reference.network_id == setup.control.network_id
    assert "actor_id" not in type(reference).model_fields and "permissions" not in type(reference).model_fields
    if governed:
        assert setup.control.active_execution_id is None
        assert setup.repo.rows[-1].status == "cancelled"
    else:
        assert setup.control.active_execution_id == identity
        assert "operator_recovery_required" in setup.repo.rows[-1].reasons
        assert setup.repo.rows[-1].status == "uncertain"
