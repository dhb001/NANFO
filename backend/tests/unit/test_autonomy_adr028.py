"""ADR-028 BE-Autonomy fixes 1, 3 and 6: STOP latency, C17 confidence, bounded decision history."""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.modules.autonomy import providers as provider_module
from app.modules.autonomy.confidence import dispatch_confidence_reasons, uncalibrated_confidence_honoured
from app.modules.autonomy.models import AutonomyDecision
from app.modules.autonomy.repository import (
    STOP_LOCK_TIMEOUT_MS,
    AutonomyRepository,
    StopLockTimeout,
    require_explainable_proposal,
)
from app.modules.autonomy.schemas import (
    POLICY_PROBABILITY_METHOD,
    Confidence,
    DecisionSummary,
    OperationalSettings,
    Proposal,
    contract_digest,
)
from app.modules.autonomy.service import STOP_LOCK_ATTEMPTS, AutonomyService
from app.modules.autonomy.worker import AutonomyWorker
from tests.autonomy_support import (
    HASH,
    MemoryRepository,
    calibrated_confidence,
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
    for target in ("worker", "service"):
        monkeypatch.setattr(f"app.modules.autonomy.{target}.AutonomyRepository", lambda db: repo)
    auth = AsyncMock(return_value=(control, ["read:telemetry", "write:config", "execute:rollback"]))
    monkeypatch.setattr("app.modules.autonomy.worker.authorize", auth)
    monkeypatch.setattr("app.modules.autonomy.service.authorize", auth)
    monkeypatch.setattr("app.modules.autonomy.governance.audit", AsyncMock())
    monkeypatch.setattr("app.modules.autonomy.governance.caller_org_role", AsyncMock(return_value="Admin"))
    worker = AutonomyWorker(sessions=sessions_for(mock_db), redis=fake_redis, providers=providers)
    claims = SimpleNamespace(user_id=control.approved_by_user_id, workspace_id=None, org_id=None)
    return SimpleNamespace(control=control, repo=repo, providers=providers, worker=worker, claims=claims,
                           db=mock_db, redis=fake_redis)


def with_proposal(setup, **changes):
    proposal = setup.providers.model.infer.return_value.model_copy(update=changes)
    setup.providers.model.infer.return_value = proposal
    setup.providers.safety.assess.return_value = certified_assessment(
        setup.providers.observer.observe.return_value, proposal)
    return proposal


# ── Fix 1: STOP never constructs providers and never waits unboundedly ─────────


async def test_stop_does_not_construct_or_load_providers(setup, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("STOP must not construct providers or load installation evidence")
    for name in ("installed_providers", "shared_providers"):
        monkeypatch.setattr(provider_module, name, forbidden)
    monkeypatch.setattr("app.modules.autonomy.service.shared_providers", forbidden)
    monkeypatch.setattr("app.modules.autonomy.execution_settings.load_config", forbidden)
    monkeypatch.setattr("app.modules.autonomy.execution_settings.verified_installation", forbidden)
    service = AutonomyService(setup.db, setup.redis, sessions=sessions_for(setup.db))
    result = await service.stop(claims=setup.claims, network_id=setup.control.network_id)
    assert result.emergency_stopped and result.status == "stopped"
    assert result.providers.executor.reasons == ["provider_status_not_evaluated"]
    assert service._providers is None


async def test_stop_lock_timeout_is_bounded_and_retryable(setup, monkeypatch):
    attempts = []
    async def contended(**kwargs):
        attempts.append(time.monotonic())
        raise StopLockTimeout
    setup.repo.latch_stop = contended
    service = AutonomyService(setup.db, setup.redis, providers=setup.providers)
    started = time.monotonic()
    with pytest.raises(HTTPException) as error:
        await service.stop(claims=setup.claims, network_id=setup.control.network_id)
    assert error.value.status_code == 503 and error.value.detail["code"] == "AUTONOMY_STOP_BUSY"
    assert error.value.headers == {"Retry-After": "1"}
    assert len(attempts) == STOP_LOCK_ATTEMPTS
    assert setup.db.rollback.await_count >= STOP_LOCK_ATTEMPTS
    assert time.monotonic() - started < 1  # retries back off briefly; each wait is bounded by lock_timeout


async def test_latch_is_one_conditional_upsert_after_set_local_lock_timeout():
    executed = []
    result = MagicMock()
    result.one_or_none.return_value = None
    db = SimpleNamespace(execute=AsyncMock(side_effect=lambda statement, *a, **k: executed.append(statement) or result))
    assert await AutonomyRepository(db).latch_stop(network_id=uuid.uuid4(), workspace_id=uuid.uuid4(), actor_id="a") is None
    assert len(executed) == 2
    assert str(executed[0]) == f"SET LOCAL lock_timeout = '{STOP_LOCK_TIMEOUT_MS}ms'"
    sql = str(executed[1].compile(dialect=postgresql.dialect()))
    assert sql.startswith("INSERT INTO autonomy_controls") and "ON CONFLICT (network_id) DO UPDATE" in sql
    assert "WHERE autonomy_controls.workspace_id = " in sql and "RETURNING" in sql
    assert "emergency_stopped = " in sql and "next_cycle_at = now()" in sql and "claim_token = " in sql
    assert "revision = (autonomy_controls.revision + " in sql


async def test_latch_translates_lock_not_available():
    from sqlalchemy.exc import OperationalError

    class Orig(Exception):
        sqlstate = "55P03"
    calls = []
    async def execute(statement, *args, **kwargs):
        calls.append(statement)
        if len(calls) == 2:
            raise OperationalError("UPDATE", {}, Orig())
    with pytest.raises(StopLockTimeout):
        await AutonomyRepository(SimpleNamespace(execute=execute)).latch_stop(
            network_id=uuid.uuid4(), workspace_id=uuid.uuid4(), actor_id="a")


async def test_stop_sets_next_cycle_now_and_bumps_revision(setup):
    setup.control.next_cycle_at = datetime.now(UTC) + timedelta(hours=1)
    before = setup.control.revision
    await AutonomyService(setup.db, setup.redis, providers=setup.providers).stop(
        claims=setup.claims, network_id=setup.control.network_id)
    assert setup.control.revision == before + 1 and setup.control.claim_token is None
    assert setup.control.next_cycle_at <= datetime.now(UTC)


async def test_fresh_control_read_refreshes_the_identity_map_without_locking():
    executed = []
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = SimpleNamespace(execute=AsyncMock(side_effect=lambda statement: executed.append(statement) or result))
    await AutonomyRepository(db).get(uuid.uuid4(), fresh=True)
    await AutonomyRepository(db).get(uuid.uuid4())
    fresh, cached = executed
    assert fresh.get_execution_options().get("populate_existing") is True
    assert "FOR UPDATE" not in str(fresh.compile(dialect=postgresql.dialect()))
    assert "populate_existing" not in cached.get_execution_options()


async def test_stop_response_snapshot_rereads_the_committed_control(setup, monkeypatch):
    # latch_stop/settle_stop_cancellation are Core statements: the session's already loaded
    # control would otherwise be served stale (emergency_stopped=false) in the STOP response.
    reads = []
    original = setup.repo.get

    async def get(network_id, **kwargs):
        reads.append(kwargs)
        return await original(network_id, **kwargs)

    monkeypatch.setattr(setup.repo, "get", get)
    result = await AutonomyService(setup.db, setup.redis, providers=setup.providers).stop(
        claims=setup.claims, network_id=setup.control.network_id)
    assert reads[-1] == {"fresh": True}
    assert result.emergency_stopped and result.status == "stopped"


def test_shared_providers_are_cached_per_identity_and_rebuilt_on_change(monkeypatch):
    provider_module.clear_provider_cache()
    built = []
    def build(sessions, redis):
        built.append(1)
        return SimpleNamespace(executor=SimpleNamespace(blocked=False))
    monkeypatch.setattr(provider_module, "installed_providers", build)
    sessions, redis = object(), object()
    first = provider_module.shared_providers(sessions, redis)
    assert provider_module.shared_providers(sessions, redis) is first
    assert provider_module.cached_providers(sessions, redis) is first and len(built) == 1
    monkeypatch.setenv("NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256", "c" * 64)
    assert provider_module.cached_providers(sessions, redis) is None
    assert provider_module.shared_providers(sessions, redis) is not first and len(built) == 2
    assert provider_module.cached_providers(object(), redis) is None  # never shared across session factories
    provider_module.clear_provider_cache()


def test_blocked_composition_is_retried_after_short_interval(monkeypatch):
    provider_module.clear_provider_cache()
    monkeypatch.setattr(provider_module, "installed_providers",
                        lambda *_: SimpleNamespace(executor=SimpleNamespace(blocked=True)))
    sessions, redis = object(), object()
    provider_module.shared_providers(sessions, redis)
    assert provider_module.cached_providers(sessions, redis) is not None
    key = (id(sessions), id(redis))
    entry = provider_module._CACHE[key]
    provider_module._CACHE[key] = (*entry[:3], entry[3] - provider_module._BLOCKED_RETRY_SECONDS - 1, *entry[4:])
    assert provider_module.cached_providers(sessions, redis) is None
    provider_module.clear_provider_cache()


async def test_request_path_builds_providers_off_the_event_loop(monkeypatch, mock_db, fake_redis):
    provider_module.clear_provider_cache()
    loop_thread = []
    def build(sessions, redis):
        import threading
        loop_thread.append(threading.current_thread() is threading.main_thread())
        return SimpleNamespace(executor=SimpleNamespace(blocked=False))
    monkeypatch.setattr(provider_module, "installed_providers", build)
    service = AutonomyService(mock_db, fake_redis, sessions=sessions_for(mock_db))
    providers = await service.get_providers()
    assert loop_thread == [False]
    assert await AutonomyService(mock_db, fake_redis, sessions=service.sessions).get_providers() is providers
    provider_module.clear_provider_cache()


# ── Fix 3: C17 typed confidence and dispatch gates ─────────────────────────────


def test_raw_policy_probability_can_never_be_labelled_calibrated():
    with pytest.raises(ValidationError, match="raw_policy_probability_cannot_be_calibrated"):
        Confidence(value=0.99, method=POLICY_PROBABILITY_METHOD, calibrated=True, calibration_id="x")
    with pytest.raises(ValidationError, match="calibration_id_required"):
        Confidence(value=0.99, method="isotonic", calibrated=True)
    with pytest.raises(ValidationError, match="calibration_id_required"):
        Confidence(value=0.99, method=POLICY_PROBABILITY_METHOD, calibrated=False, calibration_id="x")
    for value in (-0.01, 1.01, True, "0.9"):
        with pytest.raises(ValidationError):
            Confidence(value=value, method="m", calibrated=False)


def test_historical_proposal_digest_is_unchanged_by_the_new_field():
    legacy = {"action_id": "a", "checkpoint_sha256": HASH, "observation_contract": "c", "evidence": ["e"]}
    proposal = Proposal.model_validate(legacy)
    assert proposal.confidence is None and proposal.model_dump(mode="json") == legacy
    import hashlib
    import json
    assert contract_digest(proposal) == hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with_confidence = Proposal.model_validate({**legacy, "confidence": calibrated_confidence().model_dump()})
    assert with_confidence.model_dump(mode="json")["confidence"]["calibrated"] is True


@pytest.mark.parametrize("confidence,operational,honoured,expected", [
    (Confidence(value=0.99, method="m", calibrated=True, calibration_id="c"), OperationalSettings(), False, []),
    (Confidence(value=0.94, method="m", calibrated=True, calibration_id="c"), OperationalSettings(), False,
     ["confidence_below_threshold"]),
    (Confidence(value=0.99, method=POLICY_PROBABILITY_METHOD, calibrated=False), OperationalSettings(), False,
     ["confidence_uncalibrated"]),
    (Confidence(value=0.99, method=POLICY_PROBABILITY_METHOD, calibrated=False),
     OperationalSettings(allow_uncalibrated_confidence=True), False, ["confidence_uncalibrated"]),
    (Confidence(value=0.99, method=POLICY_PROBABILITY_METHOD, calibrated=False),
     OperationalSettings(allow_uncalibrated_confidence=True), True, []),
    (Confidence(value=0.96, method=POLICY_PROBABILITY_METHOD, calibrated=False),
     OperationalSettings(allow_uncalibrated_confidence=True, min_confidence=0.97), True, ["confidence_below_threshold"]),
    (None, OperationalSettings(), True, ["confidence_missing"]),
])
def test_dispatch_confidence_gate(confidence, operational, honoured, expected):
    assert dispatch_confidence_reasons(confidence, operational, honour_uncalibrated=honoured) == expected


@pytest.mark.parametrize("lab,mode,honoured", [(True, "emulation", True), (True, "production", False),
                                               (False, "emulation", False), (True, "demo", False)])
def test_uncalibrated_confidence_only_in_enabled_experimental_lab(lab, mode, honoured):
    settings = SimpleNamespace(NANFO_EXPERIMENTAL_LAB_ENABLED=lab, EXECUTION_MODE=mode)
    assert uncalibrated_confidence_honoured(settings) is honoured
    assert uncalibrated_confidence_honoured(SimpleNamespace(EXECUTION_MODE="emulation")) is False


def test_min_confidence_cannot_be_below_constitution_tier():
    with pytest.raises(ValidationError):
        OperationalSettings(min_confidence=0.94)
    assert OperationalSettings().min_confidence == 0.95 and OperationalSettings().allow_uncalibrated_confidence is False


@pytest.mark.parametrize("case", ["uncalibrated", "below_threshold"])
async def test_autonomous_dispatch_refuses_unqualified_confidence(setup, case):
    if case == "uncalibrated":
        with_proposal(setup, confidence=Confidence(value=0.99, method=POLICY_PROBABILITY_METHOD, calibrated=False))
        reason = "confidence_uncalibrated"
    else:
        with_proposal(setup, confidence=calibrated_confidence(0.9))
        reason = "confidence_below_threshold"
    await setup.worker.run_one()
    row = setup.repo.rows[-1]
    assert row.status == "blocked" and reason in row.reasons
    assert row.proposal["confidence"]["value"] in (0.99, 0.9)  # the refused proposal stays explainable
    setup.providers.safety.assess.assert_not_awaited()
    setup.providers.executor.accept.assert_not_awaited()


async def test_experimental_lab_honours_allow_uncalibrated(setup, monkeypatch):
    with_proposal(setup, confidence=Confidence(value=0.97, method=POLICY_PROBABILITY_METHOD, calibrated=False))
    setup.repo.operational = AsyncMock(return_value=OperationalSettings(allow_uncalibrated_confidence=True))
    monkeypatch.setattr("app.modules.autonomy.worker.uncalibrated_confidence_honoured", lambda: True)
    await setup.worker.run_one()
    setup.providers.executor.accept.assert_awaited_once()


async def test_recommend_mode_persists_proposal_with_confidence(setup):
    setup.control.mode = "recommend"
    with_proposal(setup, confidence=Confidence(value=0.97, method=POLICY_PROBABILITY_METHOD, calibrated=False))
    await setup.worker.run_one()
    row = setup.repo.rows[-1]
    assert row.status == "recommended"
    assert row.proposal["confidence"] == {"value": 0.97, "method": POLICY_PROBABILITY_METHOD,
                                          "calibrated": False, "calibration_id": None}
    assert "confidence_uncalibrated" in row.reasons and "not_authorized_for_actuation" in row.reasons
    summary = DecisionSummary.model_validate(row)
    assert summary.confidence.calibrated is False and summary.confidence.value == 0.97


@pytest.mark.parametrize("mode", ["recommend", "autonomous"])
async def test_constitution_no_proposal_persisted_without_confidence(setup, mode):
    setup.control.mode = mode
    with_proposal(setup, confidence=None)
    await setup.worker.run_one()
    row = setup.repo.rows[-1]
    assert row.status == "blocked" and row.reasons == ["confidence_missing"] and row.proposal is None
    setup.providers.executor.accept.assert_not_awaited()
    with pytest.raises(ValueError, match="evidence_and_confidence_required"):
        AutonomyWorker.update_decision(row, status="recommended", reasons=[],
                                       proposal=setup.providers.model.infer.return_value)


def _decision(**changes):
    values = dict(decision_id=uuid.uuid4(), network_id=uuid.uuid4(), workspace_id=uuid.uuid4(), actor_id="a",
                  mode="recommend", control_revision=1, status="recommended", reasons=[], evidence=[])
    return AutonomyDecision(**(values | changes))


def test_flush_guard_rejects_unexplainable_proposals():
    legacy = {"action_id": "a", "checkpoint_sha256": HASH, "observation_contract": "c", "evidence": ["e"]}
    with pytest.raises(ValueError, match="evidence_and_confidence_required"):
        require_explainable_proposal(None, None, _decision(proposal=legacy))
    with pytest.raises(ValueError, match="proposal_contract_invalid"):
        require_explainable_proposal(None, None, _decision(proposal={**legacy, "evidence": []}))
    require_explainable_proposal(None, None, _decision(proposal={**legacy, "confidence": calibrated_confidence().model_dump()}))
    require_explainable_proposal(None, None, _decision(proposal=None))


def test_flush_guard_is_registered_for_inserts_and_updates():
    from sqlalchemy import event

    assert event.contains(AutonomyDecision, "before_insert", require_explainable_proposal)
    assert event.contains(AutonomyDecision, "before_update", require_explainable_proposal)


# ── Fix 6: coalesced no-change cycles, retention, summaries ────────────────────


async def test_unchanged_monitor_cycles_coalesce_into_one_row(setup):
    setup.control.mode = "monitor"
    for _ in range(3):
        await setup.worker.run_one()
    assert len(setup.repo.rows) == 1
    row = setup.repo.rows[0]
    assert row.status == "observed" and row.observation is not None
    summary = DecisionSummary.model_validate(row)
    assert summary.repeat_count == 3 and "coalesced_cycles:3" not in summary.reasons
    assert summary.last_seen_at == row.updated_at
    assert setup.control.last_observation is not None and setup.control.claim_token is None


async def test_changed_outcome_starts_a_new_row(setup):
    setup.control.mode = "monitor"
    await setup.worker.run_one()
    observation = setup.providers.observer.observe.return_value
    setup.providers.observer.observe.return_value = observation.model_copy(update={"evidence": []})
    await setup.worker.run_one()
    setup.providers.observer.observe.return_value = observation
    await setup.worker.run_one()
    assert [row.reasons for row in setup.repo.rows] == [[], ["observation_evidence_missing"], []]


async def test_provider_outputs_are_never_coalesced(setup):
    setup.control.mode = "recommend"
    await setup.worker.run_one()
    await setup.worker.run_one()
    assert [row.status for row in setup.repo.rows] == ["recommended", "recommended"]


async def test_control_revision_change_is_not_coalesced(setup):
    setup.control.mode = "monitor"
    await setup.worker.run_one()
    setup.control.revision += 1
    await setup.worker.run_one()
    assert len(setup.repo.rows) == 2


def test_summary_projection_sql_never_selects_blobs():
    from sqlalchemy import select

    from app.modules.autonomy.repository import _OBSERVATION_SUMMARY, _SAFETY_SUMMARY, _SUMMARY_COLUMNS

    sql = str(select(*_SUMMARY_COLUMNS, _OBSERVATION_SUMMARY, _SAFETY_SUMMARY).compile(dialect=postgresql.dialect()))
    assert "autonomy_decisions.observation - 'samples'" in sql and "jsonb_array_length" in sql
    for path in ("{selected_action}", "{binding,observation}", "{binding,policy}", "{binding,calibration}", "{binding,state}"):
        assert f"#- '{path}'" in sql
    assert "authorization" not in sql


async def test_history_summary_query_is_bounded():
    executed = []
    result = MagicMock()
    result.all.return_value = []
    db = SimpleNamespace(execute=AsyncMock(side_effect=lambda statement: executed.append(statement) or result))
    await AutonomyRepository(db).history(uuid.uuid4(), 500, summary=True)
    assert executed[0]._limit == 100


def test_summary_projection_from_full_row():
    control = control_record()
    providers = qualified_providers(control)
    observation = providers.observer.observe.return_value
    safety = providers.safety.assess.return_value
    row = _decision(network_id=control.network_id, workspace_id=control.workspace_id, status="blocked",
                    observation=observation.model_dump(mode="json"), safety=safety.model_dump(mode="json"),
                    proposal=providers.model.infer.return_value.model_dump(mode="json"), evidence=["e"],
                    created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    summary = DecisionSummary.model_validate(row)
    dumped = summary.model_dump(mode="json")
    assert set(dumped["safety"]["binding"]) == {"workspace_id", "observation_sha256", "proposal_sha256",
        "calibration_sha256", "selected_action_sha256", "evaluated_at_unix_seconds"}
    assert "selected_action" not in dumped["safety"] and dumped["safety"]["certificate"] is not None
    assert "authorization" not in dumped and dumped["projection"] == "summary"


async def test_retention_prunes_only_coalescible_rows_and_releases_pins(monkeypatch):
    from app.modules.autonomy import repository as repository_module

    network = uuid.uuid4()
    rows = [_decision(network_id=network, status="observed", observation=None) for _ in range(2)]
    executed, deleted, released = [], [], []
    scalars = MagicMock()
    scalars.all.return_value = rows
    db = SimpleNamespace(scalars=AsyncMock(side_effect=lambda statement: executed.append(statement) or scalars),
                         delete=AsyncMock(side_effect=deleted.append), flush=AsyncMock())
    monkeypatch.setattr(repository_module, "release_decision_pins", AsyncMock(side_effect=lambda db, row: released.append(row)))
    cutoff = datetime.now(UTC) - timedelta(days=30)
    assert await AutonomyRepository(db).prune_coalescible(network, before=cutoff, limit=2) == 2
    assert deleted == rows and released == rows
    sql = str(executed[0].compile(dialect=postgresql.dialect()))
    for clause in ("autonomy_decisions.network_id = ", "autonomy_decisions.created_at < ", "autonomy_decisions.updated_at < ",
                   "autonomy_decisions.status IN", "autonomy_decisions.proposal IS NULL", "autonomy_decisions.safety IS NULL",
                   "autonomy_decisions.execution_id IS NULL", 'autonomy_decisions."authorization" IS NULL',
                   "autonomy_decisions.verification IS NULL", "FOR UPDATE SKIP LOCKED"):
        assert clause in sql


async def test_worker_retention_uses_configured_days(setup, monkeypatch):
    calls = []
    class Repo:
        def __init__(self, db):
            pass
        async def control_network_ids(self):
            return [setup.control.network_id]
        async def prune_coalescible(self, network_id, *, before, limit):
            calls.append(before)
            return 0
    monkeypatch.setattr("app.modules.autonomy.worker.AutonomyRepository", Repo)
    monkeypatch.setattr("app.modules.autonomy.worker.get_settings",
                        lambda: SimpleNamespace(AUTONOMY_DECISION_RETENTION_DAYS=7))
    now = datetime.now(UTC)
    assert await setup.worker.prune_decisions(now=now) == 0
    assert calls == [now - timedelta(days=7)]


async def test_release_decision_pins_releases_only_this_rows_references(monkeypatch):
    from app.modules.autonomy.repository import release_decision_pins

    record = uuid.uuid4()
    row = _decision(status="observed", evidence=[f"telemetry_record:{record}"])
    released = []
    class Pins:
        def __init__(self, db, scope):
            assert scope.owner == "autonomy" and scope.workspace_id == row.workspace_id
        async def release(self, reference):
            released.append(reference)
            return True
    monkeypatch.setattr("app.modules.telemetry.pins.TelemetryEvidenceService", Pins)
    assert await release_decision_pins(object(), row) == 1
    assert released[0].record_id == record and released[0].network_id == row.network_id


async def test_previous_decision_lock_protects_against_retention():
    executed = []
    db = SimpleNamespace(scalar=AsyncMock(side_effect=lambda statement: executed.append(statement)))
    await AutonomyRepository(db).previous_decision(uuid.uuid4(), uuid.uuid4())
    sql = str(executed[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql and "status != " in sql


async def test_stop_bounded_even_when_cancellation_hangs(setup, monkeypatch):
    setup.control.active_execution_id, setup.control.active_intent_id = uuid.uuid4(), uuid.uuid4()
    setup.control.active_decision_id = uuid.uuid4()
    async def hang(reference):
        await asyncio.Event().wait()
    setup.providers.recovery.cancel.side_effect = hang
    monkeypatch.setattr("app.modules.autonomy.service.PROVIDER_TIMEOUT_SECONDS", 0.05)
    result = await AutonomyService(setup.db, setup.redis, providers=setup.providers).stop(
        claims=setup.claims, network_id=setup.control.network_id)
    assert result.emergency_stopped and result.cancellation_status == "uncertain"
