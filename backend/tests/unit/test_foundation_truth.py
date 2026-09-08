"""No execution mode installs a controller, evaluator, model, or renderer."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.api.v1.simulation import SimulationCompareResponse
from app.core.config import get_settings
from app.modules.intent.repository import IntentRepository
from app.modules.intent.service import IntentExecutionService, IntentValidationService
from app.modules.network.repository import NetworkRepository
from app.modules.organization.repository import (
    OrganizationRepository,
    OrgMemberRepository,
    WorkspaceRepository,
)
from app.modules.report.repository import ReportRepository
from app.modules.report.service import ReportService
from app.modules.simulation.repository import SimulationRepository
from app.modules.simulation.service import (
    SimulationStartService,
    SimulationTerminalEventService,
)

ORG, WS, USER, NETWORK, ITEM = [UUID(int=n) for n in range(1, 6)]
NOW = datetime(2026, 1, 1, tzinfo=UTC)
NULL_METRICS = {"latency_ms": None, "loss_pct": None, "throughput_mbps": None}


@pytest.fixture(params=["demo", "emulation", "production"])
def execution_mode(request, monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", request.param)
    get_settings.cache_clear()
    yield request.param
    get_settings.cache_clear()


@pytest.fixture
def membership(monkeypatch):
    monkeypatch.setattr(OrganizationRepository, "get_by_id", AsyncMock(return_value=SimpleNamespace(org_id=ORG)))
    member = AsyncMock(return_value=SimpleNamespace(org_role="Admin"))
    monkeypatch.setattr(OrgMemberRepository, "get_member", member)
    monkeypatch.setattr(WorkspaceRepository, "get_by_id", AsyncMock(return_value=SimpleNamespace(org_id=ORG, workspace_id=WS)))
    monkeypatch.setattr(NetworkRepository, "get_by_id", AsyncMock(return_value=SimpleNamespace(network_id=NETWORK, workspace_id=WS)))
    return member


def simulation_record(**overrides):
    return SimpleNamespace(**({
        "simulation_id": ITEM, "parent_simulation_id": None, "scenario_id": ITEM,
        "network_id": NETWORK, "workspace_id": WS, "scenario_name": "baseline", "state": "queued",
        "status": "queued", "risk_gate": "required", "queue_status": "queued", "warning": None,
        "stream_entry_id": None, "validation": {}, "run_output": {"latency_ms": 0.0},
        "model_versions": {}, "audit_provenance": {}, "requested_by_user_id": str(USER),
        "requested_at": NOW, "created_at": NOW, "updated_at": NOW,
    } | overrides))


@pytest.mark.asyncio
async def test_simulation_terminal_never_passes_without_evaluator(execution_mode, mock_db, fake_redis, monkeypatch):
    row = simulation_record()
    monkeypatch.setattr(SimulationRepository, "get_by_id", AsyncMock(return_value=row))
    svc = SimulationTerminalEventService(db=mock_db, redis=fake_redis)
    await svc.process_started_event(event={
        "event_type": "simulation.started", "correlation_id": str(ITEM), "payload": {"simulation_id": str(ITEM)},
    })
    assert row.state == row.status == "cancelled"
    assert row.risk_gate == "blocked"
    assert row.validation["failure_reason"] == "evaluator_unavailable"
    assert row.run_output == NULL_METRICS
    entries = await fake_redis.xrange("stream:simulation")
    assert len(entries) == 1
    assert "simulation.cancelled" in str(entries)
    assert "simulation.completed" not in str(entries)


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [{}, {"latency_ms": 0.0}, {"latency_ms": 12.5, "loss_pct": 0.1, "throughput_mbps": 900}])
async def test_legacy_completed_simulations_are_not_measurements(
    execution_mode, membership, mock_db, fake_redis, monkeypatch, output,
):
    row = simulation_record(state="completed", status="completed", risk_gate="passed", run_output=output)
    monkeypatch.setattr(SimulationRepository, "get_by_id", AsyncMock(return_value=row))
    svc = SimulationStartService(db=mock_db, redis=fake_redis)
    args = {"requested_by_user_id": str(USER), "requested_workspace_id": WS, "claim_org_id": ORG}
    detail = await svc.get_simulation_detail(simulation_id=ITEM, **args)
    assert detail["state"] == detail["status"] == "cancelled"
    assert detail["risk_gate"] == "blocked"
    assert detail["run_output"] == NULL_METRICS
    assert detail["validation"]["legacy_baseline_unverified"] is True
    comparison = await svc.compare_simulations(simulation_id=ITEM, baseline_simulation_id=ITEM, **args)
    for key in ["simulation_metrics", "baseline_metrics", "deltas"]:
        assert comparison[key] == NULL_METRICS
    assert SimulationCompareResponse.model_validate(comparison).model_dump()["deltas"] == NULL_METRICS
    assert row.status == "completed"  # Read projection does not rewrite historical records.


@pytest.mark.asyncio
async def test_new_simulation_and_branch_never_copy_measurements(execution_mode, membership, mock_db, fake_redis, monkeypatch):
    svc = SimulationStartService(db=mock_db, redis=fake_redis)
    create = AsyncMock(side_effect=lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(SimulationRepository, "create", create)
    await svc.start_simulation(
        network_id=NETWORK, scenario_name="test", simulation_id=None, validation_checks=[], correlation_id=str(ITEM),
        requested_by_user_id=str(USER), requested_workspace_id=WS, claim_org_id=ORG,
    )
    assert create.await_args.kwargs["run_output"] == NULL_METRICS
    parent = simulation_record(state="completed", run_output={"latency_ms": 10}, model_versions={"baseline": "v1"})
    monkeypatch.setattr(SimulationRepository, "get_by_id", AsyncMock(return_value=parent))
    await svc.branch_simulation(
        parent_simulation_id=ITEM, scenario_name="branch", correlation_id=str(ITEM), requested_by_user_id=str(USER),
        requested_workspace_id=WS, claim_org_id=ORG,
    )
    assert create.await_args.kwargs["run_output"] == NULL_METRICS
    assert create.await_args.kwargs["model_versions"] == {}


def report_record(**overrides):
    return SimpleNamespace(**({
        "report_id": ITEM, "workspace_id": WS, "network_id": None, "report_type": "summary", "output_format": "pdf",
        "status": "requested", "date_range": {"start": NOW.isoformat(), "end": NOW.isoformat()},
        "scope": {}, "filters": {}, "artifact_refs": [], "error_context": {}, "queue_status": "queued",
        "stream_entry_id": None, "warning": None, "idempotency_key": None, "correlation_id": ITEM,
        "requested_by_user_id": str(USER), "requested_at": NOW, "completed_at": None,
        "created_at": NOW, "updated_at": NOW,
    } | overrides))


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_generation", [False, True])
async def test_report_renderer_unavailable_never_creates_artifacts(execution_mode, mock_db, fake_redis, monkeypatch, fail_generation):
    row = report_record()
    monkeypatch.setattr(ReportRepository, "get_by_id", AsyncMock(return_value=row))
    svc = ReportService(db=mock_db, redis=fake_redis)
    await svc.process_requested_event({
        "event_type": "report.requested", "correlation_id": str(ITEM),
        "payload": {"report_id": str(ITEM), "fail_generation": fail_generation},
    })
    assert row.status == "failed"
    assert row.artifact_refs == []
    assert row.error_context["code"] == "REPORT_RENDERER_UNAVAILABLE"
    entries = await fake_redis.xrange("stream:report")
    assert "report.failed" in str(entries)
    assert "s3://" not in str(entries)
    assert "report.generated" not in str(entries)


@pytest.mark.asyncio
async def test_legacy_report_get_and_replay_suppress_fake_artifacts(execution_mode, membership, mock_db, fake_redis, monkeypatch):
    row = report_record(status="generated", artifact_refs=[{"uri": "s3://legacy/fabricated.pdf"}])
    monkeypatch.setattr(ReportRepository, "get_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(ReportRepository, "get_by_idempotency_key", AsyncMock(return_value=row))
    svc = ReportService(db=mock_db, redis=fake_redis)
    detail = await svc.get_report(report_id=ITEM, workspace_id=WS, user_id=str(USER))
    replay = await svc.generate_report(
        workspace_id=WS, network_id=None, report_type="summary", output_format="pdf", date_range=row.date_range,
        scope={}, filters={}, fail_generation=False, idempotency_key="replay", correlation_id=str(ITEM), requested_by_user_id=str(USER),
    )
    for result in [detail, replay]:
        assert result["status"] == "failed"
        assert result["artifacts"] == []
        assert result["error"]["code"] == "REPORT_RENDERER_UNAVAILABLE"
    membership.assert_awaited_with(ORG, USER)


@pytest.mark.asyncio
async def test_report_membership_checked_before_record_or_replay(membership, mock_db, fake_redis, monkeypatch):
    membership.return_value = None
    lookup = AsyncMock()
    monkeypatch.setattr(ReportRepository, "get_by_id", lookup)
    monkeypatch.setattr(ReportRepository, "get_by_idempotency_key", lookup)
    svc = ReportService(db=mock_db, redis=fake_redis)
    with pytest.raises(HTTPException) as exc:
        await svc.get_report(report_id=ITEM, workspace_id=WS, user_id=str(USER))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await svc.generate_report(
            workspace_id=WS, network_id=None, report_type="summary", output_format="pdf", date_range={}, scope={}, filters={},
            fail_generation=False, idempotency_key="replay", correlation_id=str(ITEM), requested_by_user_id=str(USER),
        )
    assert exc.value.status_code == 403
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_intent_validation_and_execution_have_no_model_or_controller(
    execution_mode, membership, mock_db, fake_redis, monkeypatch,
):
    row = None

    def create(**kwargs):
        nonlocal row
        row = SimpleNamespace(**kwargs, created_at=NOW, updated_at=NOW)
        return row

    monkeypatch.setattr(IntentRepository, "create", AsyncMock(side_effect=create))
    validated = await IntentValidationService(db=mock_db, redis=fake_redis).validate_intent(
        workspace_id=WS, network_id=NETWORK, intent_payload={"action": "isolate_vlan", "scope": {"network": str(NETWORK)}},
        idempotency_key=None, correlation_id=str(ITEM), requested_by_user_id=str(USER),
    )
    assert validated["confidence"] == {"score": 0.0, "band": "below_60", "approval_required": True}
    assert validated["validation"]["model_evidence"] == "unavailable"
    assert validated["validation"]["dependency_analysis"] == "not_performed"
    monkeypatch.setattr(IntentRepository, "get_by_id", AsyncMock(return_value=row))
    executed = await IntentExecutionService(db=mock_db, redis=fake_redis).execute_intent(
        workspace_id=WS, intent_id=row.intent_id, idempotency_key=None, correlation_id=str(ITEM),
        requested_by_user_id=str(USER), requested_permissions=["write:config", "execute:rollback"],
    )
    assert executed["status"] == "execution_failed"
    assert executed["execution_provenance"]["failure_reason"] == "executor_unavailable"
    assert executed["execution_provenance"]["verification"]["status"] == "not_performed"
    assert "rollback" not in executed["execution_provenance"]
    assert "intent.execution_completed" not in str(await fake_redis.xrange("stream:intent"))


@pytest.mark.asyncio
async def test_legacy_intent_read_and_replay_never_advertise_baseline_rollback(
    execution_mode, membership, mock_db, fake_redis, monkeypatch,
):
    row = SimpleNamespace(
        intent_id=ITEM, workspace_id=WS, network_id=NETWORK, intent_kind="isolate_vlan", intent_payload={},
        status="execution_failed", validation_result={"capability_match": "matched", "dependency_analysis": "complete"},
        execution_provenance={"executor": "hypervisor_baseline", "verification": {"status": "failed"},
                              "rollback": {"attempted": True, "status": "completed"}},
        explainability={}, confidence_score=0.84, confidence_band="80-94", approval_required=True,
        idempotency_key="legacy", queue_status="queued", stream_entry_id=None, warning=None, correlation_id=ITEM,
        requested_by_user_id=str(USER), requested_at=NOW, created_at=NOW, updated_at=NOW,
    )
    monkeypatch.setattr(IntentRepository, "get_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(IntentRepository, "get_by_idempotency_key", AsyncMock(return_value=row))
    svc = IntentExecutionService(db=mock_db, redis=fake_redis)
    detail = await svc.get_intent_detail(workspace_id=WS, intent_id=ITEM, user_id=str(USER))
    replay = await svc.execute_intent(
        workspace_id=WS, intent_id=ITEM, idempotency_key="legacy", correlation_id=str(ITEM),
        requested_by_user_id=str(USER), requested_permissions=["write:config", "execute:rollback"],
    )
    for result in [detail, replay]:
        assert result["confidence"]["score"] == 0.0
        assert result["execution_provenance"]["verification"]["status"] == "not_performed"
        assert "rollback" not in result["execution_provenance"]


@pytest.mark.asyncio
async def test_missing_network_cannot_persist_or_publish_network_routing_context(membership, mock_db, fake_redis, monkeypatch):
    monkeypatch.setattr(NetworkRepository, "get_by_id", AsyncMock(return_value=None))
    create = AsyncMock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs, created_at=NOW, updated_at=NOW))
    monkeypatch.setattr(IntentRepository, "create", create)
    result = await IntentValidationService(db=mock_db, redis=fake_redis).validate_intent(
        workspace_id=WS, network_id=NETWORK, intent_payload={"action": "reroute_path", "scope": {"network": str(NETWORK)}},
        idempotency_key=None, correlation_id=str(ITEM), requested_by_user_id=str(USER),
    )
    assert result["status"] == "rejected"
    assert result["network_id"] is None
    assert create.await_args.kwargs["network_id"] is None
    assert "NETWORK_NOT_FOUND" in {reason["code"] for reason in result["validation"]["reasons"]}
    import json

    entries = await fake_redis.xrange("stream:intent")
    payload = json.loads(entries[0][1]["payload"])
    assert payload["network_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("publisher_unavailable", [False, True])
async def test_simulation_commits_terminal_state_before_publish_even_on_failure(
    execution_mode, membership, mock_db, fake_redis, monkeypatch, resume, publisher_unavailable,
):
    row = simulation_record(state="paused", status="paused") if resume else None
    operations = []

    def create(**kwargs):
        nonlocal row
        row = SimpleNamespace(**kwargs)
        operations.append("create")
        return row

    async def commit():
        assert row.state == row.status == "cancelled"
        assert row.risk_gate == "blocked"
        assert row.run_output == NULL_METRICS
        operations.append("commit")

    async def publish(**kwargs):
        assert operations[-1] == "commit"
        assert kwargs["event_type"] == "simulation.cancelled"
        assert kwargs["payload"]["workspace_id"] == str(WS)
        assert kwargs["payload"]["state"] == "cancelled"
        operations.append("publish")
        if publisher_unavailable:
            raise RuntimeError("publisher unavailable")
        return "1-0"

    monkeypatch.setattr(SimulationRepository, "create", AsyncMock(side_effect=create))
    monkeypatch.setattr(SimulationRepository, "get_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr("app.modules.simulation.service.publish_event", AsyncMock(side_effect=publish))
    mock_db.commit.side_effect = commit
    result = await SimulationStartService(db=mock_db, redis=fake_redis).start_simulation(
        network_id=NETWORK, scenario_name="test", simulation_id=ITEM if resume else None, validation_checks=[],
        correlation_id=str(ITEM), requested_by_user_id=str(USER), requested_workspace_id=WS, claim_org_id=ORG,
    )
    assert operations == (["create"] if not resume else []) + ["commit", "publish", "commit"]
    assert result["handoff"]["state"] == row.state == "cancelled"
    assert result["handoff"]["risk_gate"] == row.risk_gate == "blocked"
    assert result["queue_status"] == row.queue_status == ("deferred" if publisher_unavailable else "queued")
    assert row.validation["failure_reason"] == "evaluator_unavailable"


@pytest.mark.asyncio
async def test_simulation_commit_failure_never_publishes(membership, mock_db, fake_redis, monkeypatch):
    create = AsyncMock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
    publish = AsyncMock()
    monkeypatch.setattr(SimulationRepository, "create", create)
    monkeypatch.setattr("app.modules.simulation.service.publish_event", publish)
    mock_db.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError, match="commit failed"):
        await SimulationStartService(db=mock_db, redis=fake_redis).start_simulation(
            network_id=NETWORK, scenario_name="test", simulation_id=None, validation_checks=[], correlation_id=str(ITEM),
            requested_by_user_id=str(USER), requested_workspace_id=WS, claim_org_id=ORG,
        )
    publish.assert_not_awaited()
