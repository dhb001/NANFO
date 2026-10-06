"""REST contract tests retain real JWT/session/current identity and ownership checks."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from tests.auth_support import create_authorized_workspace
from tests.autonomy_support import HASH, MemoryRepository


@pytest.fixture
def context(tenant_auth, mock_db, monkeypatch):
    workspace_id = create_authorized_workspace()
    network = SimpleNamespace(network_id=uuid.uuid4(), workspace_id=workspace_id)
    repo = MemoryRepository()
    monkeypatch.setattr("app.modules.autonomy.service.AutonomyRepository", lambda db: repo)
    monkeypatch.setattr("app.modules.network.repository.NetworkRepository.get_by_id",
                        AsyncMock(side_effect=lambda identity: network if identity == network.network_id else None))
    async def db():
        yield mock_db
    async def redis():
        yield tenant_auth.redis
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_redis] = redis
    yield SimpleNamespace(client=TestClient(app, raise_server_exceptions=False), auth=tenant_auth,
                          network=network, repo=repo)
    app.dependency_overrides.clear()


def headers(context, permissions=None, **scope):
    actor = str(uuid.uuid4())
    token, _ = context.auth.issue(user_id=actor, email="autonomy@example.com", roles=[actor],
        permissions=permissions if permissions is not None else ["read:telemetry", "write:config", "execute:rollback"], **scope)
    context.actor = actor
    return {"Authorization": f"Bearer {token}"}


def test_get_typed_fail_closed_status(context):
    response = context.client.get("/api/v1/autonomy", params={"network_id": str(context.network.network_id)}, headers=headers(context))
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True and body["errors"] is None
    data = body["data"]
    assert data["mode"] == "monitor" and data["status"] == "monitoring"
    assert data["ready"] is False and data["online_learning"] is False
    assert data["production_dispatch"] is False
    assert data["providers"]["observer"]["status"] == "incompatible"
    assert data["decisions"] == [] and data["last_observation"] is None


def test_autonomous_put_409_preserves_existing_mode(context):
    auth = headers(context)
    network_id = str(context.network.network_id)
    assert context.client.put("/api/v1/autonomy", json={"network_id": network_id, "expected_revision": 0, "mode": "recommend"}, headers=auth).status_code == 200
    response = context.client.put("/api/v1/autonomy", json={"network_id": network_id, "mode": "autonomous",
        "expected_revision": 1, "checkpoint_sha256": HASH, "approval_expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}, headers=auth)
    assert response.status_code == 409
    assert response.json()["errors"]["code"] == "AUTONOMY_NOT_READY"
    assert "autonomous_executor_unavailable" in response.json()["errors"]["message"]
    assert context.repo.control.mode == "recommend"


@pytest.mark.parametrize("permissions", [["write:config"], ["execute:rollback"], ["read:telemetry"]])
@pytest.mark.parametrize("method,path,payload", [
    ("put", "/api/v1/autonomy", {"mode": "monitor", "expected_revision": 0}),
    ("put", "/api/v1/autonomy/configuration", {"expected_revision": 0, "reason": "test", "operational": {}, "training": {}}),
    ("post", "/api/v1/autonomy/overrides", {"expected_revision": 0, "reason": "test", "duration_seconds": 10,
        "return_mode": "monitor", "intent_id": str(uuid.uuid4()), "execution_id": str(uuid.uuid4())}),
])
def test_writes_require_both_permissions(context, permissions, method, path, payload):
    response = getattr(context.client, method)(path, json={"network_id": str(context.network.network_id), **payload},
                                               headers=headers(context, permissions))
    assert response.status_code == 403
    assert context.repo.control is None


def test_current_permissions_not_token_permissions(context):
    auth = headers(context)
    context.auth.permissions[(context.actor,)] = ["read:telemetry"]
    response = context.client.put("/api/v1/autonomy", json={"network_id": str(context.network.network_id), "expected_revision": 0, "mode": "monitor"}, headers=auth)
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["configuration", "overrides"])
def test_operator_reads_require_telemetry_and_membership(context, path):
    route = f"/api/v1/autonomy/{path}"
    scope = {"network_id": str(context.network.network_id)}
    assert context.client.get(route, params=scope).status_code == 401
    auth = headers(context, ["write:config", "execute:rollback"])
    assert context.client.get(route, params=scope, headers=auth).status_code == 403
    auth = headers(context, ["read:telemetry"])
    response = context.client.get(route, params=scope, headers=auth)
    assert response.status_code == 200 and response.json()["success"]
    assert "capability" not in response.text
    context.auth.memberships.clear()
    assert context.client.get(route, params=scope, headers=auth).status_code == 403


@pytest.mark.parametrize("action", ["cancel", "return"])
def test_override_mutations_require_current_authority(context, monkeypatch, action):
    row = SimpleNamespace(override_id=uuid.uuid4(), network_id=context.network.network_id,
                          workspace_id=context.network.workspace_id)
    context.repo.override = AsyncMock(return_value=row)
    response = context.client.post(f"/api/v1/autonomy/overrides/{row.override_id}/{action}",
        json={"expected_revision": 0, "reason": "return"} if action == "return" else None,
        headers=headers(context, ["read:telemetry"]))
    assert response.status_code == 403


def test_global_admin_permissions_do_not_override_readonly_membership(context, monkeypatch):
    auth = headers(context)
    monkeypatch.setattr("app.modules.organization.repository.OrgMemberRepository.get_member",
        AsyncMock(return_value=SimpleNamespace(org_role="ReadOnly")))
    response = context.client.put("/api/v1/autonomy/configuration", headers=auth,
        json={"network_id": str(context.network.network_id), "expected_revision": 0, "reason": "denied", "operational": {}, "training": {}})
    assert response.status_code == 403


@pytest.mark.parametrize("scope", ["workspace_id", "org_id"])
def test_cross_scope_rejected(context, scope):
    response = context.client.get("/api/v1/autonomy", params={"network_id": str(context.network.network_id)},
                                  headers=headers(context, **{scope: str(uuid.uuid4())}))
    assert response.status_code == 403


def test_membership_revocation_denies_read(context):
    auth = headers(context)
    context.auth.memberships.clear()
    response = context.client.get("/api/v1/autonomy", params={"network_id": str(context.network.network_id)}, headers=auth)
    assert response.status_code == 403


def test_stop_latched_and_explicit_monitor_clears(context):
    auth = headers(context)
    payload = {"network_id": str(context.network.network_id)}
    response = context.client.post("/api/v1/autonomy/stop", json=payload, headers=auth)
    assert response.status_code == 200
    assert response.json()["data"]["emergency_stopped"] is True
    response = context.client.get("/api/v1/autonomy", params=payload, headers=auth)
    assert response.json()["data"]["status"] == "stopped"
    response = context.client.put("/api/v1/autonomy", json={**payload, "expected_revision": response.json()["data"]["revision"], "mode": "monitor"}, headers=auth)
    assert response.json()["data"]["emergency_stopped"] is False
    assert response.json()["data"]["last_decision"]["status"] == "control_changed"


def test_auth_and_bounded_history(context):
    params = {"network_id": str(context.network.network_id)}
    assert context.client.get("/api/v1/autonomy", params=params).status_code == 401
    auth = headers(context)
    assert context.client.get("/api/v1/autonomy", params={**params, "history_limit": 101}, headers=auth).status_code == 422


def test_openapi_concrete_schemas():
    schema = app.openapi()
    result = schema["paths"]["/api/v1/autonomy"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "APIResponse_AutonomyResponse_" in result["$ref"]
    assert "AutonomyResponse" in schema["components"]["schemas"]
    assert "DecisionResponse" in schema["components"]["schemas"]
    assert "expected_revision" in schema["components"]["schemas"]["SetAutonomyRequest"]["required"]


def test_stale_put_preserves_stop_and_initial_revision(context):
    auth = headers(context)
    scope = {"network_id": str(context.network.network_id)}
    assert context.client.get("/api/v1/autonomy", params=scope, headers=auth).json()["data"]["revision"] == 0
    assert context.client.put("/api/v1/autonomy", json={**scope, "mode": "monitor"}, headers=auth).status_code == 422
    stopped = context.client.post("/api/v1/autonomy/stop", json=scope, headers=auth).json()["data"]
    result = context.client.put("/api/v1/autonomy", json={**scope, "mode": "monitor", "expected_revision": 0}, headers=auth)
    assert result.status_code == 409
    assert result.json()["errors"]["code"] == "AUTONOMY_REVISION_CONFLICT"
    current = context.client.get("/api/v1/autonomy", params=scope, headers=auth).json()["data"]
    assert current["revision"] == stopped["revision"] and current["emergency_stopped"]


# ── ADR-028 C25 / fixes 1, 4, 5, 13 ────────────────────────────────────────────


@pytest.fixture
def audits(monkeypatch):
    recorded = AsyncMock()
    monkeypatch.setattr("app.modules.identity.service.append_audit_log", recorded)
    return recorded


def audited(audits, event_type):
    return [call.kwargs for call in audits.await_args_list if call.kwargs["event_type"] == event_type]


@pytest.mark.parametrize("permissions,status", [(["read:telemetry"], 200), (["write:config", "execute:rollback"], 403),
                                                (["write:config"], 403), (["execute:rollback"], 403)])
def test_stop_allowed_for_read_only_members(context, audits, permissions, status):
    payload = {"network_id": str(context.network.network_id)}
    response = context.client.post("/api/v1/autonomy/stop", json=payload, headers=headers(context, permissions))
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json()["data"]["emergency_stopped"] is True
        entry, = audited(audits, "autonomy.stop.latched")
        assert entry["resource_type"] == "autonomy_control" and entry["resource_id"] == context.network.network_id
        assert str(entry["actor_id"]) == context.actor and entry["org_id"] == context.auth.org_id
        assert entry["metadata"]["revision"] == 1
    else:
        assert context.repo.control is None and not audits.await_count


def test_stop_read_only_can_be_disabled(context, monkeypatch):
    monkeypatch.setattr("app.modules.autonomy.governance.stop_allows_read_only", lambda: False)
    payload = {"network_id": str(context.network.network_id)}
    assert context.client.post("/api/v1/autonomy/stop", json=payload,
                               headers=headers(context, ["read:telemetry"])).status_code == 403
    assert context.client.post("/api/v1/autonomy/stop", json=payload, headers=headers(context)).status_code == 200


def test_stop_correlates_audit_with_request_id(context, audits):
    request_id = str(uuid.uuid4())
    auth = {**headers(context, ["read:telemetry"]), "X-Request-ID": request_id}
    response = context.client.post("/api/v1/autonomy/stop", json={"network_id": str(context.network.network_id)}, headers=auth)
    assert response.status_code == 200 and response.json()["meta"]["request_id"] == request_id
    assert str(audited(audits, "autonomy.stop.latched")[0]["correlation_id"]) == request_id


def test_stop_after_network_soft_delete_uses_control_workspace(context, monkeypatch, audits):
    network_id = context.network.network_id
    auth = headers(context)
    assert context.client.put("/api/v1/autonomy", json={"network_id": str(network_id), "expected_revision": 0,
                                                        "mode": "recommend"}, headers=auth).status_code == 200
    # Network hides soft-deleted rows; the control row keeps the authoritative workspace scope.
    monkeypatch.setattr("app.modules.network.repository.NetworkRepository.get_by_id", AsyncMock(return_value=None))
    response = context.client.post("/api/v1/autonomy/stop", json={"network_id": str(network_id)},
                                   headers=headers(context, ["read:telemetry"]))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["emergency_stopped"] is True and context.repo.control.emergency_stopped
    other = context.client.post("/api/v1/autonomy/stop", json={"network_id": str(uuid.uuid4())}, headers=auth)
    assert other.status_code == 404
    context.auth.memberships.clear()
    denied = context.client.post("/api/v1/autonomy/stop", json={"network_id": str(network_id)},
                                 headers={"Authorization": auth["Authorization"]})
    assert denied.status_code == 403


def test_clearing_stop_requires_org_admin(context, monkeypatch, audits):
    from types import SimpleNamespace as Namespace

    network = {"network_id": str(context.network.network_id)}
    auth = headers(context)
    stopped = context.client.post("/api/v1/autonomy/stop", json=network, headers=auth).json()["data"]
    monkeypatch.setattr("app.modules.organization.repository.OrgMemberRepository.get_member",
                        AsyncMock(return_value=Namespace(org_role="Operator")))
    response = context.client.put("/api/v1/autonomy", json={**network, "expected_revision": stopped["revision"],
                                                            "mode": "monitor"}, headers=auth)
    assert response.status_code == 403
    assert response.json()["errors"]["code"] == "AUTONOMY_STOP_CLEAR_REQUIRES_ADMIN"
    assert context.repo.control.emergency_stopped
    monkeypatch.setattr("app.modules.organization.repository.OrgMemberRepository.get_member",
                        AsyncMock(return_value=Namespace(org_role="Admin")))
    response = context.client.put("/api/v1/autonomy", json={**network, "expected_revision": stopped["revision"],
                                                            "mode": "monitor"}, headers=auth)
    assert response.status_code == 200 and response.json()["data"]["emergency_stopped"] is False
    entry, = audited(audits, "autonomy.mode.changed")
    assert entry["metadata"]["cleared_emergency_stop"] is True and entry["metadata"]["to_mode"] == "monitor"


@pytest.fixture
def ready_autonomy(context, monkeypatch):
    from app.modules.autonomy.schemas import Qualification
    from tests.autonomy_support import control_record, qualified_providers

    providers = qualified_providers(control_record(network_id=context.network.network_id,
                                                   workspace_id=context.network.workspace_id))
    monkeypatch.setattr("app.modules.autonomy.service.cached_providers", lambda *_: providers)
    monkeypatch.setattr("app.modules.autonomy.service.readiness", AsyncMock(return_value=(
        [], Qualification(qualified=True, checkpoint_sha256=HASH, observation_contract="test.measured.v1",
                          manifest_sha256="b" * 64, evidence=["test:manifest"]))))
    return providers


def autonomous_body(context, revision=0, minutes=5):
    return {"network_id": str(context.network.network_id), "expected_revision": revision, "mode": "autonomous",
            "checkpoint_sha256": HASH,
            "approval_expires_at": (datetime.now(UTC) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()}


def test_autonomous_switch_requires_two_distinct_users(context, ready_autonomy, audits):
    body = autonomous_body(context)
    requester = headers(context)
    requester_id = context.actor
    first = context.client.put("/api/v1/autonomy", json=body, headers=requester)
    assert first.status_code == 202, first.text
    envelope = first.json()
    assert envelope["meta"]["pending_approval"] is True
    assert envelope["meta"]["pending_requested_by_user_id"] == requester_id
    assert envelope["meta"]["pending_approval_expires_at"]
    assert envelope["data"]["mode"] == "monitor" and envelope["data"]["revision"] == 0
    assert envelope["data"]["pending_approval"]["requested_by_user_id"] == requester_id
    assert context.repo.control is None  # nothing switched, no control row mutated
    same_user = context.client.put("/api/v1/autonomy", json=body, headers=requester)
    assert same_user.status_code == 409
    assert same_user.json()["errors"]["code"] == "AUTONOMY_DISTINCT_APPROVER_REQUIRED"
    approver = headers(context)
    second = context.client.put("/api/v1/autonomy", json=body, headers=approver)
    assert second.status_code == 200, second.text
    data = second.json()["data"]
    assert second.json()["meta"]["pending_approval"] is False
    assert data["mode"] == "autonomous" and data["approved_by_user_id"] == context.actor != requester_id
    assert data["pending_approval"] is None
    requested, = audited(audits, "autonomy.mode.approval_requested")
    changed, = audited(audits, "autonomy.mode.changed")
    assert str(requested["actor_id"]) == requester_id
    assert changed["metadata"]["requested_by_user_id"] == requester_id and changed["metadata"]["two_person"] is True
    replay = context.client.put("/api/v1/autonomy", json=body, headers=headers(context))
    assert replay.status_code == 409 and replay.json()["errors"]["code"] == "AUTONOMY_REVISION_CONFLICT"


def test_pending_request_is_bound_to_exact_body_and_revision(context, ready_autonomy):
    first = context.client.put("/api/v1/autonomy", json=autonomous_body(context), headers=headers(context))
    assert first.status_code == 202
    # A different user's *different* request is a new pending request, not a confirmation.
    other = context.client.put("/api/v1/autonomy", json=autonomous_body(context, minutes=7), headers=headers(context))
    assert other.status_code == 202 and other.json()["data"]["mode"] == "monitor"
    # Any control change (STOP) makes the revision-bound request stale.
    context.client.post("/api/v1/autonomy/stop", json={"network_id": str(context.network.network_id)}, headers=headers(context))
    current = context.client.get("/api/v1/autonomy", params={"network_id": str(context.network.network_id)},
                                 headers=headers(context)).json()["data"]
    assert current["pending_approval"] is None


def test_single_person_switch_when_distinct_approver_disabled(context, ready_autonomy, monkeypatch):
    monkeypatch.setattr("app.modules.autonomy.governance.require_distinct_approver", lambda: False)
    response = context.client.put("/api/v1/autonomy", json=autonomous_body(context), headers=headers(context))
    assert response.status_code == 200 and response.json()["data"]["mode"] == "autonomous"
    assert response.json()["meta"]["pending_approval"] is False


def test_configuration_change_is_audited(context, audits, mock_db):
    from app.modules.autonomy.models import ConfigurationRevision

    request_id = str(uuid.uuid4())
    response = context.client.put("/api/v1/autonomy/configuration", headers={**headers(context), "X-Request-ID": request_id},
        json={"network_id": str(context.network.network_id), "expected_revision": 0, "reason": "tighten",
              "operational": {"min_confidence": 0.97}, "training": {}})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["allow_uncalibrated_confidence_honoured"] is False
    revision, = [call.args[0] for call in mock_db.add.call_args_list if isinstance(call.args[0], ConfigurationRevision)]
    assert revision.operational["min_confidence"] == 0.97 and revision.operational["allow_uncalibrated_confidence"] is False
    entry, = audited(audits, "autonomy.configuration.changed")
    assert entry["resource_type"] == "autonomy_configuration" and entry["metadata"]["min_confidence"] == 0.97
    assert str(entry["correlation_id"]) == request_id


@pytest.mark.parametrize("value", [0.9, 1.01, True, "0.99"])
def test_configuration_rejects_confidence_below_constitution_floor(context, value):
    response = context.client.put("/api/v1/autonomy/configuration", headers=headers(context),
        json={"network_id": str(context.network.network_id), "expected_revision": 0, "reason": "loosen",
              "operational": {"min_confidence": value}, "training": {}})
    assert response.status_code == 422


def test_history_lists_are_summaries_and_latest_is_full(context):
    from app.modules.autonomy.models import AutonomyDecision

    network = context.network
    auth = headers(context)
    context.client.put("/api/v1/autonomy", json={"network_id": str(network.network_id), "expected_revision": 0,
                                                 "mode": "monitor"}, headers=auth)
    now = datetime.now(UTC)
    samples = [{"record_id": str(uuid.uuid4()), "device_id": str(uuid.uuid4()), "metric": "m", "value": 1.0,
                "unit": None, "observed_at": now.isoformat(), "source": "emulation", "run_id": None, "port_no": None}
               for _ in range(100)]
    context.repo.rows.append(AutonomyDecision(decision_id=uuid.uuid4(), network_id=network.network_id,
        workspace_id=network.workspace_id, actor_id=context.actor, mode="monitor", control_revision=1, status="observed",
        reasons=["observation_contract_incompatible", "coalesced_cycles:7"], checkpoint_sha256=None,
        observation={"network_id": str(network.network_id), "workspace_id": str(network.workspace_id),
                     "provider_id": "p", "contract": "c", "observed_at": now.isoformat(), "collected_at": now.isoformat(),
                     "age_seconds": 0.0, "fresh": True, "compatible": False, "reasons": [], "samples": samples,
                     "evidence": ["x"]}, evidence=["x"], created_at=now, updated_at=now))
    data = context.client.get("/api/v1/autonomy", params={"network_id": str(network.network_id)}, headers=auth).json()["data"]
    summary = data["decisions"][0]
    assert summary["projection"] == "summary" and summary["observation"]["samples"] == []
    assert summary["observation"]["sample_count"] == 100 and "authorization" not in summary
    assert summary["repeat_count"] == 7 and summary["reasons"] == ["observation_contract_incompatible"]
    assert data["last_decision"]["projection"] == "full" and len(data["last_decision"]["observation"]["samples"]) == 100


def test_model_diagnostic_busy_is_a_per_network_429_envelope(context, monkeypatch):
    from app.modules.autonomy.model_diagnostic_registry import diagnostic_lock_key

    network_id = context.network.network_id
    model = SimpleNamespace(histories={"validation-06": SimpleNamespace(network_ids=[network_id])})
    monkeypatch.setattr("app.modules.autonomy.model_diagnostics.load_registry", lambda: (object(), "f" * 64, None))
    monkeypatch.setattr("app.modules.autonomy.model_diagnostics.select_model", lambda registry, network: model)
    # This network's live inference (or another diagnostic) holds the per-network admission lease.
    context.auth._writer.set(diagnostic_lock_key(network_id), "other-owner", px=40_000)
    response = context.client.post("/api/v1/autonomy/model/diagnose", headers=headers(context),
                                   json={"network_id": str(network_id), "history_reference": "validation-06"})
    assert response.status_code == 429 and response.headers["Retry-After"] == "5"
    body = response.json()
    assert body["success"] is False and body["errors"]["code"] == "MODEL_DIAGNOSTIC_BUSY"
    assert context.auth._writer.get(diagnostic_lock_key(network_id)) == "other-owner"  # never released by others
    assert context.auth._writer.keys("nanfo:autonomy:model-diagnostics:org:*") == []  # no slot taken or leaked


@pytest.mark.parametrize("action", ["stop", "configuration"])
def test_opaque_request_id_is_normalized_by_core_correlation(context, monkeypatch, action):
    from app.core.correlation import correlation_uuid

    appended = AsyncMock()  # repository boundary: the real append_audit_log normalization runs
    monkeypatch.setattr("app.modules.identity.repository.AuditLogRepository.append", appended)
    opaque = "gateway-trace:7f3a/opaque"
    auth = {**headers(context), "X-Request-ID": opaque}
    network = {"network_id": str(context.network.network_id)}
    if action == "stop":
        response = context.client.post("/api/v1/autonomy/stop", json=network, headers=auth)
    else:
        response = context.client.put("/api/v1/autonomy/configuration", headers=auth, json={
            **network, "expected_revision": 0, "reason": "trace", "operational": {}, "training": {}})
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["request_id"] == opaque
    entry, = [call.kwargs for call in appended.await_args_list]
    assert entry["event_type"] == ("autonomy.stop.latched" if action == "stop" else "autonomy.configuration.changed")
    assert entry["correlation_id"] == correlation_uuid(opaque) and entry["metadata"]["request_id"] == opaque
