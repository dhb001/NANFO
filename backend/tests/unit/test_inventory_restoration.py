"""Deletion requires exact owner-projected compensation/restoration evidence (Intent-owned)."""

import copy
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.intent.lab import digest
from app.modules.intent.queries import has_blocking_work, verified_restoration

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


def verified(detail) -> bool:
    return verified_restoration(status=detail["status"], provenance=detail["execution_provenance"])


@pytest.mark.parametrize("restore", [False, True])
def test_exact_restoration_is_safe(restore):
    assert verified(restored_detail(restore=restore))


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
    assert not verified(detail)


def test_applied_policy_and_foreign_restore_do_not_prove_restoration():
    detail = restored_detail(restore=True)
    proof = copy.deepcopy(detail)
    proof["execution_provenance"]["verification"]["probe"]["destination_host"] = "h4"
    assert not verified(proof)
    applied = restored_detail()
    applied["status"] = applied["execution_provenance"]["status"] = "execution_completed"
    applied["execution_provenance"]["phase"] = "completed"
    assert not verified(applied)
    assert not verified_restoration(status="execution_failed", provenance=None)


def _rows(*rows):
    result = MagicMock()
    result.all.return_value = list(rows)
    return result


async def test_blocking_intent_status_is_one_indexed_network_probe():
    db = AsyncMock()
    db.scalar.return_value = INTENT
    assert await has_blocking_work(db, network_id=NETWORK) is True
    sql = db.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "intents.network_id =" in str(sql) and "intents.status NOT IN" in str(sql)
    assert NETWORK in sql.params.values()
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("restore", [False, True])
async def test_finished_executions_require_verified_restoration(restore):
    detail = restored_detail(restore=restore)
    good = SimpleNamespace(intent_id=INTENT, status=detail["status"], execution_provenance=detail["execution_provenance"])
    db = AsyncMock()
    db.scalar.return_value = None
    db.execute.return_value = _rows(good)
    assert await has_blocking_work(db, network_id=NETWORK) is False
    unproven = SimpleNamespace(intent_id=INTENT, status=detail["status"],
                               execution_provenance={**detail["execution_provenance"], "blocks_lab": True})
    db.execute.return_value = _rows(unproven)
    assert await has_blocking_work(db, network_id=NETWORK) is True


async def test_restoration_proofs_are_paged_by_intent_id():
    detail = restored_detail()
    good = [SimpleNamespace(intent_id=uuid.UUID(int=100 + n), status=detail["status"],
                            execution_provenance=detail["execution_provenance"]) for n in range(200)]
    bad = SimpleNamespace(intent_id=uuid.UUID(int=999), status=detail["status"], execution_provenance={})
    db = AsyncMock()
    db.scalar.return_value = None
    db.execute.side_effect = [_rows(*good), _rows(bad)]
    assert await has_blocking_work(db, network_id=NETWORK) is True
    second = str(db.execute.await_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    assert "intents.intent_id >" in second
