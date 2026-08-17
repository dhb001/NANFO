"""Integration tests for intent endpoint contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.core.security import create_access_token
from app.main import app


def _make_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="intent@example.com",
        roles=["Admin"],
        permissions=["write:config", "read:topology", "execute:rollback"],
    )
    return token


def _make_no_execute_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="intent-no-exec@example.com",
        roles=["Admin"],
        permissions=["write:config", "read:topology"],
    )
    return token


def _make_no_write_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="intent-no-write@example.com",
        roles=["Admin"],
        permissions=["read:topology"],
    )
    return token


def _make_no_read_topology_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="intent-no-read@example.com",
        roles=["Admin"],
        permissions=["write:config", "execute:rollback"],
    )
    return token


def _make_workspace_scoped_token(*, workspace_id: uuid.UUID) -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="intent-scoped@example.com",
        roles=["Admin"],
        permissions=["write:config", "read:topology", "execute:rollback"],
        workspace_id=str(workspace_id),
    )
    return token


@pytest.fixture
def client() -> TestClient:
    fake_r = fakeredis.FakeAsyncRedis(decode_responses=True)
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    async def _redis():
        yield fake_r

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_validate_intent_returns_envelope_and_validation_payload(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    now = datetime.now(UTC)
    result_payload = {
        "intent_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "network_id": uuid.uuid4(),
        "status": "validated",
        "intent_kind": "reroute_path",
        "validation": {
            "is_valid": True,
            "reasons": [],
            "required_checks": ["simulation_before_deployment", "blast_radius_assessment"],
            "capability_match": "matched",
            "dependency_analysis": "complete",
            "simulation_required": True,
            "policy_reference": "ADR-008",
            "validated_at": now,
        },
        "explainability": {
            "summary": "Intent passed baseline UNIL validation checks.",
            "evidence": ["BASELINE_CHECKS_PASSED"],
            "alternatives_considered": ["manual_review"],
            "policy_reference": "ADR-008",
        },
        "confidence": {
            "score": 0.84,
            "band": "80-94",
            "approval_required": True,
        },
        "idempotency_key": None,
        "correlation_id": uuid.uuid4(),
        "requested_at": now,
    }

    with patch(
        "app.modules.intent.service.IntentValidationService.validate_intent",
        new=AsyncMock(return_value=result_payload),
    ):
        response = client.post(
            "/api/v1/intents/validate",
            json={
                "workspace_id": str(result_payload["workspace_id"]),
                "network_id": str(result_payload["network_id"]),
                "intent": {
                    "action": "reroute_path",
                    "scope": {"building": "A"},
                    "constraints": {"max_downtime": 0},
                },
            },
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["status"] == "validated"
    assert body["data"]["validation"]["is_valid"] is True
    assert body["data"]["confidence"]["approval_required"] is True


def test_validate_intent_forwards_idempotency_key_header(client):
    headers = {
        "Authorization": f"Bearer {_make_token()}",
        "Idempotency-Key": "idem-header-1",
    }

    with patch(
        "app.modules.intent.service.IntentValidationService.validate_intent",
        new=AsyncMock(
            return_value={
                "intent_id": uuid.uuid4(),
                "workspace_id": uuid.uuid4(),
                "network_id": uuid.uuid4(),
                "status": "validated",
                "intent_kind": "reroute_path",
                "validation": {
                    "is_valid": True,
                    "reasons": [],
                    "required_checks": ["simulation_before_deployment"],
                    "capability_match": "matched",
                    "dependency_analysis": "complete",
                    "simulation_required": True,
                    "policy_reference": "ADR-008",
                    "validated_at": datetime.now(UTC),
                },
                "explainability": {
                    "summary": "ok",
                    "evidence": ["BASELINE_CHECKS_PASSED"],
                    "alternatives_considered": ["manual_review"],
                    "policy_reference": "ADR-008",
                },
                "confidence": {"score": 0.84, "band": "80-94", "approval_required": True},
                "idempotency_key": "idem-header-1",
                "correlation_id": uuid.uuid4(),
                "requested_at": datetime.now(UTC),
            }
        ),
    ) as mock_validate:
        response = client.post(
            "/api/v1/intents/validate",
            json={
                "workspace_id": str(uuid.uuid4()),
                "network_id": str(uuid.uuid4()),
                "intent": {"action": "reroute_path", "scope": {"building": "A"}},
            },
            headers=headers,
        )

    assert response.status_code == 200
    assert mock_validate.await_args.kwargs["idempotency_key"] == "idem-header-1"


def test_validate_intent_invalid_returns_explicit_reasons(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    now = datetime.now(UTC)
    workspace_id = uuid.uuid4()
    result_payload = {
        "intent_id": uuid.uuid4(),
        "workspace_id": workspace_id,
        "network_id": None,
        "status": "rejected",
        "intent_kind": "unknown",
        "validation": {
            "is_valid": False,
            "reasons": [
                {
                    "code": "ACTION_REQUIRED",
                    "message": "Intent action is required.",
                    "path": "intent.action",
                },
                {
                    "code": "NETWORK_ID_REQUIRED",
                    "message": "network_id is required for capability and dependency validation.",
                    "path": "network_id",
                },
            ],
            "required_checks": ["simulation_before_deployment"],
            "capability_match": "failed",
            "dependency_analysis": "failed",
            "simulation_required": True,
            "policy_reference": "ADR-008",
            "validated_at": now,
        },
        "explainability": {
            "summary": "Intent rejected by baseline UNIL validation checks.",
            "evidence": ["ACTION_REQUIRED", "NETWORK_ID_REQUIRED"],
            "alternatives_considered": ["manual_review"],
            "policy_reference": "ADR-008",
        },
        "confidence": {
            "score": 0.0,
            "band": "below_60",
            "approval_required": True,
        },
        "idempotency_key": None,
        "correlation_id": uuid.uuid4(),
        "requested_at": now,
    }

    with patch(
        "app.modules.intent.service.IntentValidationService.validate_intent",
        new=AsyncMock(return_value=result_payload),
    ):
        response = client.post(
            "/api/v1/intents/validate",
            json={
                "workspace_id": str(workspace_id),
                "intent": {},
            },
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "rejected"
    assert body["data"]["validation"]["is_valid"] is False
    reason_codes = {item["code"] for item in body["data"]["validation"]["reasons"]}
    assert "ACTION_REQUIRED" in reason_codes
    assert "NETWORK_ID_REQUIRED" in reason_codes


def test_validate_intent_requires_auth(client):
    response = client.post(
        "/api/v1/intents/validate",
        json={
            "workspace_id": str(uuid.uuid4()),
            "intent": {"action": "reroute_path", "scope": {"building": "A"}},
        },
    )
    assert response.status_code in (401, 403)


def test_validate_intent_missing_write_permission_returns_403(client):
    headers = {"Authorization": f"Bearer {_make_no_write_token()}"}
    response = client.post(
        "/api/v1/intents/validate",
        json={
            "workspace_id": str(uuid.uuid4()),
            "network_id": str(uuid.uuid4()),
            "intent": {"action": "reroute_path", "scope": {"building": "A"}},
        },
        headers=headers,
    )

    assert response.status_code == 403


def test_validate_intent_workspace_scope_mismatch_returns_403(client):
    token_workspace_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {_make_workspace_scoped_token(workspace_id=token_workspace_id)}"}
    response = client.post(
        "/api/v1/intents/validate",
        json={
            "workspace_id": str(uuid.uuid4()),
            "network_id": str(uuid.uuid4()),
            "intent": {"action": "reroute_path", "scope": {"building": "A"}},
        },
        headers=headers,
    )

    assert response.status_code == 403


def test_execute_intent_returns_envelope_and_execution_payload(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    now = datetime.now(UTC)
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    result_payload = {
        "intent_id": intent_id,
        "workspace_id": workspace_id,
        "network_id": uuid.uuid4(),
        "status": "execution_started",
        "intent_kind": "reroute_path",
        "queue_status": "queued",
        "stream_entry_id": "3001-0",
        "warning": None,
        "validation_result": {"is_valid": True},
        "execution_provenance": {"pipeline_stage": "execution_started"},
        "explainability": {"summary": "ok"},
        "confidence": {"score": 0.84, "band": "80-94", "approval_required": True},
        "idempotency_key": "idem-1",
        "correlation_id": uuid.uuid4(),
        "requested_by_user_id": str(uuid.uuid4()),
        "requested_at": now,
        "updated_at": now,
        "idempotent_replay": False,
    }

    with patch(
        "app.modules.intent.service.IntentExecutionService.execute_intent",
        new=AsyncMock(return_value=result_payload),
    ):
        response = client.post(
            "/api/v1/intents/execute",
            json={
                "workspace_id": str(workspace_id),
                "intent_id": str(intent_id),
                "idempotency_key": "idem-1",
            },
            headers=headers,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["intent_id"] == str(intent_id)
    assert body["data"]["status"] == "execution_started"
    assert body["data"]["idempotent_replay"] is False


def test_execute_intent_requires_execute_rollback_permission(client):
    headers = {"Authorization": f"Bearer {_make_no_execute_token()}"}
    response = client.post(
        "/api/v1/intents/execute",
        json={
            "workspace_id": str(uuid.uuid4()),
            "intent_id": str(uuid.uuid4()),
            "idempotency_key": "idem-1",
        },
        headers=headers,
    )

    assert response.status_code == 403
    body = response.json()
    assert body["success"] is False
    assert body["errors"]["code"] == "INTENT_EXECUTION_PERMISSION_DENIED"


def test_execute_intent_prefers_body_idempotency_key_over_header(client):
    headers = {
        "Authorization": f"Bearer {_make_token()}",
        "Idempotency-Key": "idem-header-1",
    }
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()

    with patch(
        "app.modules.intent.service.IntentExecutionService.execute_intent",
        new=AsyncMock(
            return_value={
                "intent_id": intent_id,
                "workspace_id": workspace_id,
                "network_id": uuid.uuid4(),
                "status": "execution_started",
                "intent_kind": "reroute_path",
                "queue_status": "queued",
                "stream_entry_id": None,
                "warning": None,
                "validation_result": {"is_valid": True},
                "execution_provenance": {"pipeline_stage": "execution_started"},
                "explainability": {"summary": "ok"},
                "confidence": {"score": 0.84, "band": "80-94", "approval_required": True},
                "idempotency_key": "idem-body-1",
                "correlation_id": uuid.uuid4(),
                "requested_by_user_id": str(uuid.uuid4()),
                "requested_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "idempotent_replay": False,
            }
        ),
    ) as mock_execute:
        response = client.post(
            "/api/v1/intents/execute",
            json={
                "workspace_id": str(workspace_id),
                "intent_id": str(intent_id),
                "idempotency_key": "idem-body-1",
            },
            headers=headers,
        )

    assert response.status_code == 202
    assert mock_execute.await_args.kwargs["idempotency_key"] == "idem-body-1"


def test_get_intent_returns_envelope_and_detail_payload(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    now = datetime.now(UTC)
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    result_payload = {
        "intent_id": intent_id,
        "workspace_id": workspace_id,
        "network_id": uuid.uuid4(),
        "status": "execution_started",
        "intent_kind": "reroute_path",
        "intent_payload": {"action": "reroute_path", "scope": {"building": "A"}},
        "validation_result": {"is_valid": True},
        "execution_provenance": {"pipeline_stage": "execution_started"},
        "explainability": {"summary": "ok"},
        "confidence": {"score": 0.84, "band": "80-94", "approval_required": True},
        "idempotency_key": "idem-1",
        "queue_status": "queued",
        "stream_entry_id": "3001-0",
        "warning": None,
        "correlation_id": uuid.uuid4(),
        "requested_by_user_id": str(uuid.uuid4()),
        "requested_at": now,
        "created_at": now,
        "updated_at": now,
    }

    with patch(
        "app.modules.intent.service.IntentExecutionService.get_intent_detail",
        new=AsyncMock(return_value=result_payload),
    ):
        response = client.get(
            f"/api/v1/intents/{intent_id}",
            params={"workspace_id": str(workspace_id)},
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["intent_id"] == str(intent_id)
    assert body["data"]["status"] == "execution_started"


def test_get_intent_invalid_workspace_id_returns_422(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    response = client.get(
        f"/api/v1/intents/{uuid.uuid4()}",
        params={"workspace_id": "not-a-uuid"},
        headers=headers,
    )

    assert response.status_code == 422


def test_get_intent_missing_read_topology_permission_returns_403(client):
    workspace_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {_make_no_read_topology_token()}"}
    response = client.get(
        f"/api/v1/intents/{uuid.uuid4()}",
        params={"workspace_id": str(workspace_id)},
        headers=headers,
    )

    assert response.status_code == 403


def test_get_intent_workspace_scope_mismatch_returns_403(client):
    token_workspace_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {_make_workspace_scoped_token(workspace_id=token_workspace_id)}"}
    response = client.get(
        f"/api/v1/intents/{uuid.uuid4()}",
        params={"workspace_id": str(uuid.uuid4())},
        headers=headers,
    )

    assert response.status_code == 403


def test_execute_intent_invalid_payload_returns_422(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    response = client.post(
        "/api/v1/intents/execute",
        json={
            "workspace_id": "not-a-uuid",
            "intent_id": str(uuid.uuid4()),
        },
        headers=headers,
    )

    assert response.status_code == 422


def test_execute_and_get_intent_require_auth(client):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()

    r1 = client.post(
        "/api/v1/intents/execute",
        json={
            "workspace_id": str(workspace_id),
            "intent_id": str(intent_id),
        },
    )
    r2 = client.get(
        f"/api/v1/intents/{intent_id}",
        params={"workspace_id": str(workspace_id)},
    )

    assert r1.status_code in (401, 403)
    assert r2.status_code in (401, 403)
