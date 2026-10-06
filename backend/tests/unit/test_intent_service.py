"""Unit tests for intent validation service baseline behavior."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.correlation import correlation_uuid
from app.modules.intent.service import IntentValidationService, republish_deferred_intents, request_fingerprint


def _network(workspace_id, network_id):
    return SimpleNamespace(network_id=network_id, workspace_id=workspace_id)


def _persist(**kwargs):
    return SimpleNamespace(**{"created_at": datetime.now(UTC), "updated_at": datetime.now(UTC), **kwargs})


@pytest.fixture
def scope(mock_db, fake_redis):
    workspace_id, network_id = uuid.uuid4(), uuid.uuid4()
    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as ws,
        patch("app.modules.intent.service.NetworkService.assert_network_workspace_access",
              new_callable=AsyncMock) as network,
        patch("app.modules.intent.service.IntentRepository.create", new=AsyncMock(side_effect=_persist)) as create,
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as by_key,
    ):
        ws.return_value = SimpleNamespace(org_id=uuid.uuid4())
        network.return_value = _network(workspace_id, network_id)
        by_key.return_value = None
        yield SimpleNamespace(workspace_id=workspace_id, network_id=network_id, ws=ws, network=network,
                              create=create, by_key=by_key, db=mock_db, redis=fake_redis,
                              service=IntentValidationService(db=mock_db, redis=fake_redis))


async def _validate(ctx, *, intent=None, key=None, network_id="default", correlation_id=None, actor=None):
    return await ctx.service.validate_intent(
        workspace_id=ctx.workspace_id,
        network_id=ctx.network_id if network_id == "default" else network_id,
        intent_payload={"intent": intent or {"action": "reroute_path", "scope": {"building": "A"},
                                             "constraints": {"max_downtime": 0}}},
        idempotency_key=key,
        correlation_id=correlation_id or str(uuid.uuid4()),
        requested_by_user_id=actor or str(uuid.uuid4()),
    )


async def test_validate_intent_valid_payload_persists_validated_state(scope):
    operations = []
    scope.db.commit.side_effect = lambda: operations.append("commit")
    with patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as publish:
        publish.side_effect = lambda **kwargs: operations.append("publish") or "3007-0"
        result = await _validate(scope)

    assert result["status"] == "validated"
    assert result["validation"]["is_valid"] is True
    assert result["validation"]["reasons"] == []
    assert result["validation"]["required_checks"] == ["simulation_before_deployment", "blast_radius_assessment"]
    assert result["explainability"]["summary"] == "Intent passed baseline UNIL validation checks."
    assert result["explainability"]["evidence"] == [
        "BASELINE_SCHEMA_CHECKS_PASSED", "MODEL_CONFIDENCE_UNAVAILABLE", "DEPENDENCY_EVALUATOR_UNAVAILABLE",
    ]
    assert result["explainability"]["alternatives_considered"] == ["manual_review"]
    assert result["explainability"]["policy_reference"] == "ADR-008"
    assert result["confidence"] == {"score": 0.0, "band": "below_60", "approval_required": True}
    assert result["queue_status"] == "validated" and result["stream_entry_id"] == "3007-0"
    assert result["warning"] is None and result["idempotent_replay"] is False
    assert result["approval_binding"] is None and result["simulation_action_binding"] is None
    actor = scope.create.await_args.kwargs["requested_by_user_id"]
    scope.ws.assert_awaited_once_with(scope.workspace_id, user_id=actor, require_write=True)
    scope.network.assert_awaited_once_with(network_id=scope.network_id, requested_workspace_id=scope.workspace_id,
                                           actor_user_id=actor, require_write=True)
    # Regression (ADR-028): the row commits (pessimistically deferred) before publication.
    assert scope.create.await_args.kwargs["queue_status"] == "deferred"
    assert operations == ["commit", "publish", "commit"]


async def test_validate_intent_publishes_validated_event_with_deterministic_id(scope):
    with patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as publish:
        publish.return_value = "3007-0"
        result = await _validate(scope)
    kwargs = publish.await_args.kwargs
    assert kwargs["event_type"] == "intent.validated" and kwargs["source"] == "intent"
    assert kwargs["payload"]["status"] == "validated"
    assert kwargs["event_id"] == str(uuid.uuid5(uuid.UUID(result["intent_id"]), "intent.validated"))
    assert kwargs["correlation_id"] == result["correlation_id"]
    assert result["stream_entry_id"] == "3007-0"


async def test_validate_intent_publish_failure_is_fail_open_deferred(scope):
    with patch("app.modules.intent.service.publish_event", new=AsyncMock(side_effect=RuntimeError("down"))):
        result = await _validate(scope)
    assert result["queue_status"] == "deferred"
    assert result["stream_entry_id"] is None
    assert result["warning"] == "event_queue_unavailable"
    scope.db.commit.assert_awaited_once()  # nothing published before (or without) the commit


async def test_validate_intent_invalid_payload_returns_explicit_reasons(scope):
    scope.network.return_value = None
    result = await _validate(scope, intent={"scope": {}})
    reason_codes = {reason["code"] for reason in result["validation"]["reasons"]}
    assert result["status"] == "rejected"
    assert result["validation"]["is_valid"] is False
    assert {"ACTION_REQUIRED", "SCOPE_REQUIRED", "NETWORK_NOT_FOUND"} <= reason_codes
    assert {"ACTION_REQUIRED", "SCOPE_REQUIRED", "NETWORK_NOT_FOUND"} <= set(result["explainability"]["evidence"])
    assert result["explainability"]["policy_reference"] == "ADR-008"
    assert result["confidence"]["score"] == 0.0 and result["confidence"]["band"] == "below_60"
    scope.create.assert_awaited_once()


async def test_validate_intent_persists_normalized_idempotency_key(scope):
    await _validate(scope, key="  idem-1  ")
    assert scope.create.await_args.kwargs["idempotency_key"] == "idem-1"
    scope.by_key.assert_awaited_once_with(workspace_id=scope.workspace_id, idempotency_key="idem-1")


async def test_same_key_same_request_replays_stored_intent_without_new_row(scope):
    """Regression C3: validate always inserted; duplicates broke scalar_one_or_none lookups."""
    first = await _validate(scope, key="submit-1")
    stored = scope.create.await_args.kwargs
    scope.by_key.return_value = _persist(**stored)
    scope.create.reset_mock()
    scope.db.commit.reset_mock()
    with patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as publish:
        replay = await _validate(scope, key="submit-1", intent={
            "constraints": {"max_downtime": 0}, "scope": {"building": "A"}, "action": "reroute_path"})
    assert replay["idempotent_replay"] is True and replay["intent_id"] == first["intent_id"]
    assert replay["validation"]["request_sha256"] == stored["validation_result"]["request_sha256"]
    scope.create.assert_not_awaited()
    publish.assert_not_awaited()
    scope.db.commit.assert_not_awaited()


@pytest.mark.parametrize("change", ["intent", "network"])
async def test_same_key_different_request_is_409_idempotency_key_reused(scope, change):
    await _validate(scope, key="submit-1")
    scope.by_key.return_value = _persist(**scope.create.await_args.kwargs)
    scope.create.reset_mock()
    with pytest.raises(HTTPException) as err:
        if change == "intent":
            await _validate(scope, key="submit-1", intent={"action": "throttle_qos", "scope": {"building": "A"}})
        else:
            await _validate(scope, key="submit-1", network_id=uuid.uuid4())
    assert err.value.status_code == 409 and err.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"
    scope.create.assert_not_awaited()


async def test_pre_adr028_row_without_fingerprint_compares_persisted_request(scope):
    intent = {"action": "reroute_path", "scope": {"building": "A"}}
    legacy = _persist(intent_id=uuid.uuid4(), workspace_id=scope.workspace_id, network_id=scope.network_id,
        intent_kind="reroute_path", intent_payload=intent, status="validated",
        validation_result={"is_valid": True, "reasons": [], "required_checks": [], "capability_match": "matched",
                           "dependency_analysis": "not_performed", "simulation_required": True,
                           "policy_reference": "ADR-008", "validated_at": datetime.now(UTC).isoformat()},
        explainability={"summary": "ok", "evidence": [], "alternatives_considered": [], "policy_reference": "ADR-008"},
        idempotency_key="legacy", correlation_id=uuid.uuid4(), requested_at=datetime.now(UTC),
        queue_status="validated", stream_entry_id="1-0", warning=None, execution_provenance={})
    scope.by_key.return_value = legacy
    assert (await _validate(scope, key="legacy", intent=dict(intent)))["idempotent_replay"] is True
    with pytest.raises(HTTPException) as err:
        await _validate(scope, key="legacy", intent={**intent, "scope": {"building": "B"}})
    assert err.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_unique_index_race_replays_winner_or_conflicts(scope):
    winner = {}

    async def race(**kwargs):
        winner.update(kwargs)
        raise IntegrityError("INSERT", {}, Exception("uq_intents_workspace_idempotency_key"))

    scope.create.side_effect = race
    scope.by_key.side_effect = [None, None]
    with pytest.raises(IntegrityError):  # no row with the key after rollback: not an idempotency race
        await _validate(scope, key="race-1")
    scope.db.rollback.assert_awaited_once()
    scope.by_key.side_effect = None
    scope.by_key.return_value = None
    request = {"action": "reroute_path", "scope": {"building": "A"}}
    same = {"validation_result": {"request_sha256": request_fingerprint(network_id=scope.network_id, intent=request)}}
    scope.by_key.side_effect = [None, _persist(**{**winner, **same})]
    replay = await _validate(scope, key="race-1", intent=request)
    assert replay["idempotent_replay"] is True
    scope.by_key.side_effect = [None, _persist(**{**winner, "validation_result": {"request_sha256": "0" * 64}})]
    with pytest.raises(HTTPException) as err:
        await _validate(scope, key="race-1", intent=request)
    assert err.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_overlong_idempotency_key_rejected_before_persistence(scope):
    with pytest.raises(HTTPException) as err:
        await _validate(scope, key="k" * 121)
    assert err.value.status_code == 400 and err.value.detail["code"] == "IDEMPOTENCY_KEY_INVALID"
    scope.create.assert_not_awaited()


async def test_opaque_request_id_uses_shared_correlation_and_keeps_original(scope):
    """Regression: a non-UUID request id became a random uuid4 (not traceable)."""
    result = await _validate(scope, correlation_id="client-trace-42")
    assert result["correlation_id"] == str(correlation_uuid("client-trace-42"))
    assert scope.create.await_args.kwargs["execution_provenance"]["request_id"] == "client-trace-42"
    entry = (await scope.redis.xrange("stream:intent"))[0][1]
    assert entry["correlation_id"] == str(correlation_uuid("client-trace-42"))


async def test_lab_validation_returns_approval_and_simulation_bindings(scope, execution_mode, monkeypatch):
    from app.core.config import get_settings
    from app.modules.intent.lab import digest
    from app.modules.simulation.modeled import current_network_state_hash

    execution_mode("emulation")
    monkeypatch.setenv("EMULATION_CONTROL_ENABLED", "true")
    get_settings.cache_clear()
    plan = SimpleNamespace(model_dump=lambda **_: {"operation": "reroute"})
    binding = SimpleNamespace(model_dump=lambda **_: {"binding": 1})
    snapshot = SimpleNamespace(run_id=uuid.UUID(int=9), model_dump=lambda **_: {"run_id": str(uuid.UUID(int=9)),
                                                                                "sequence": 3, "links": []})
    monkeypatch.setattr("app.modules.intent.lab.prepare_plan", AsyncMock(return_value=(plan, binding, snapshot)))
    result = await _validate(scope, intent={"action": "reroute_path", "scope": {"source_host": "h1"}})
    assert result["approval_binding"] == {"plan_hash": digest({"operation": "reroute"}),
                                          "binding_digest": digest({"binding": 1}), "run_id": str(uuid.UUID(int=9))}
    assert result["simulation_action_binding"] == {
        "intent_id": result["intent_id"], "plan_sha256": digest({"operation": "reroute"}),
        "network_state_sha256": current_network_state_hash(binding=binding, snapshot=snapshot)}
    assert result["validation"]["simulation_required"] is True
    assert {"simulation_before_deployment", "distinct_approver"} <= set(result["validation"]["required_checks"])


async def test_deferred_sweep_republishes_committed_events_with_stable_ids(mock_db, fake_redis):
    workspace_id, org_id = uuid.uuid4(), uuid.uuid4()
    validated = _persist(intent_id=uuid.uuid4(), workspace_id=workspace_id, network_id=None, intent_kind="reroute_path",
        status="validated", validation_result={"is_valid": True, "policy_reference": "ADR-008"},
        explainability={"summary": "ok"}, correlation_id=uuid.uuid4(), requested_by_user_id="u",
        execution_provenance={}, queue_status="deferred", warning="event_queue_unavailable", stream_entry_id=None,
        confidence_score=0.0, confidence_band="below_60", approval_required=True)
    executed = _persist(**{**vars(validated), "intent_id": uuid.uuid4(), "status": "execution_failed",
        "execution_provenance": {"executor": "unavailable", "status": "execution_failed",
                                 "failure_reason": "executor_unavailable", "correlation_id": str(uuid.uuid4())}})
    with (
        patch("app.modules.intent.service.IntentRepository.claim_deferred",
              new=AsyncMock(return_value=[validated, executed])) as claim,
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace",
              new=AsyncMock(return_value=SimpleNamespace(org_id=org_id))),
    ):
        assert await republish_deferred_intents(db=mock_db, redis=fake_redis) == 2
    assert claim.await_args.kwargs == {"limit": 20, "older_than_seconds": 30}
    entries = [entry for _, entry in await fake_redis.xrange("stream:intent")]
    assert [entry["event_type"] for entry in entries] == [
        "intent.validated", "intent.validated", "intent.execution_started", "intent.execution_failed"]
    assert entries[0]["event_id"] == str(uuid.uuid5(validated.intent_id, "intent.validated"))
    assert entries[3]["event_id"] == str(uuid.uuid5(executed.intent_id, "intent.execution_failed"))
    assert json.loads(entries[2]["payload"])["execution_provenance"]["status"] == "execution_started"
    assert (validated.queue_status, executed.queue_status) == ("validated", "queued")
    assert validated.warning is None and executed.stream_entry_id is not None
    mock_db.commit.assert_awaited_once()


async def test_deferred_sweep_parks_rows_of_deleted_workspaces_and_stops_on_redis_failure(mock_db):
    row = _persist(intent_id=uuid.uuid4(), workspace_id=uuid.uuid4(), status="validated", queue_status="deferred",
                   warning="event_queue_unavailable")
    with (
        patch("app.modules.intent.service.IntentRepository.claim_deferred", new=AsyncMock(return_value=[row])),
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace",
              new=AsyncMock(side_effect=HTTPException(404, detail="gone"))),
    ):
        assert await republish_deferred_intents(db=mock_db, redis=AsyncMock()) == 0
    assert row.queue_status == "deferred" and row.warning == "event_workspace_unavailable"
    redis = AsyncMock()
    redis.xadd.side_effect = ConnectionError("down")
    live = _persist(**{**vars(row), "warning": "event_queue_unavailable", "network_id": None, "intent_kind": "x",
                       "validation_result": {}, "explainability": {}, "correlation_id": uuid.uuid4(),
                       "requested_by_user_id": "u", "execution_provenance": {}})
    with (
        patch("app.modules.intent.service.IntentRepository.claim_deferred", new=AsyncMock(return_value=[live])),
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace",
              new=AsyncMock(return_value=SimpleNamespace(org_id=uuid.uuid4()))),
    ):
        assert await republish_deferred_intents(db=mock_db, redis=redis) == 0
    assert live.queue_status == "deferred"
