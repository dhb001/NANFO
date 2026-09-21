"""Deletion requires exact owner-projected compensation/restoration evidence."""

import copy
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.intent.lab import digest
from app.modules.network.deletion import InventoryDeletionService, _verified_intent_restoration

INTENT, NETWORK, WORKSPACE, EXECUTION, RUN = [uuid.UUID(int=n) for n in range(1, 6)]


def restored_detail(*, restore=False):
    now = datetime.now(UTC)
    plan = {"operation": "restore" if restore else "shape", "source_host": "h1", "destination_host": "h3",
            "paths": [], "weights": [], "rate_mbps": None if restore else 5.0, "dscp": None}
    status = "execution_completed" if restore else "execution_failed"
    return {"intent_id": str(INTENT), "network_id": str(NETWORK), "workspace_id": str(WORKSPACE), "status": status,
            "execution_provenance": {
                "executor": "manual_lab_v1", "status": status, "phase": "completed" if restore else "cancelled",
                "blocks_lab": False, "uncertain": False, "execution_id": str(EXECUTION), "run_id": str(RUN),
                "binding_digest": "b" * 64, "plan_hash": digest(plan), "approved_plan": plan,
                "approved_at": (now - timedelta(seconds=20)).isoformat(), "completed_at": now.isoformat(),
                "rollback": None if restore else {"verified": True, "readback_sha256": "c" * 64},
                "verification": {"readback_verified": True, "readback_sha256": "d" * 64,
                                 "config_readback_and_reachability": True, "traffic_effects_verified": False,
                                 "probe": {"sent": 3, "received": 3, "source_host": "h1", "destination_host": "h3"}},
            }}


@pytest.mark.parametrize("restore", [False, True])
def test_exact_restoration_is_safe(restore):
    assert _verified_intent_restoration(restored_detail(restore=restore), intent_id=INTENT,
                                       network=SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE))


@pytest.mark.parametrize("field,value", [
    ("executor", "unavailable"), ("blocks_lab", True), ("blocks_lab", None), ("uncertain", True),
    ("phase", "uncertain"), ("execution_id", "invalid"), ("run_id", None), ("binding_digest", "invalid"),
    ("plan_hash", "e" * 64), ("approved_plan", None), ("approved_at", "invalid"),
    ("completed_at", "2000-01-01T00:00:00Z"), ("rollback", None), ("rollback", {"verified": True}),
    ("rollback", {"verified": False, "readback_sha256": "c" * 64}), ("status", "execution_started"),
])
def test_incomplete_ambiguous_or_mismatched_proof_blocks(field, value):
    detail = restored_detail()
    detail["execution_provenance"][field] = value
    assert not _verified_intent_restoration(detail, intent_id=INTENT,
                                           network=SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE))


def test_applied_policy_and_foreign_restore_do_not_prove_restoration():
    network = SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE)
    detail = restored_detail(restore=True)
    for key in ("intent_id", "network_id", "workspace_id"):
        foreign = copy.deepcopy(detail)
        foreign[key] = str(uuid.UUID(int=99))
        assert not _verified_intent_restoration(foreign, intent_id=INTENT, network=network)
    proof = detail["execution_provenance"]
    proof["verification"]["probe"]["destination_host"] = "h4"
    assert not _verified_intent_restoration(detail, intent_id=INTENT, network=network)
    applied = restored_detail()
    applied["status"] = applied["execution_provenance"]["status"] = "execution_completed"
    applied["execution_provenance"]["phase"] = "completed"
    assert not _verified_intent_restoration(applied, intent_id=INTENT, network=network)


@pytest.mark.parametrize("restore", [False, True])
async def test_dependency_uses_owning_detail_and_still_blocks_missing_proof(mock_db, fake_redis, restore):
    network = SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE)
    with (
        patch("app.modules.simulation.history.SimulationHistoryService.list_page", new_callable=AsyncMock) as sim,
        patch("app.modules.intent.history.IntentHistoryService.list_page", new_callable=AsyncMock) as intent,
        patch("app.modules.intent.service.IntentExecutionService.get_intent_detail", new_callable=AsyncMock) as detail,
        patch("app.modules.autonomy.service.AutonomyService.snapshot", new_callable=AsyncMock) as autonomy,
    ):
        sim.return_value = SimpleNamespace(items=[], total=0)
        detail.return_value = restored_detail(restore=restore)
        intent.return_value = SimpleNamespace(items=[SimpleNamespace(intent_id=INTENT,
            status=detail.return_value["status"])], total=1)
        autonomy.return_value = SimpleNamespace(mode="monitor", active_execution_id=None,
                                               cancellation_status="none", blocked_reasons=[])
        service = InventoryDeletionService(mock_db, fake_redis)
        await service._assert_workflows_safe(network, "actor")
        detail.assert_awaited_once_with(workspace_id=WORKSPACE, intent_id=INTENT, user_id="actor")
        detail.return_value = {}
        with pytest.raises(HTTPException) as exc:
            await service._assert_workflows_safe(network, "actor")
        assert exc.value.status_code == 409
