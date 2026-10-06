"""ADR-028 C7 audit read model and fix-10 allowlisted, size-capped event projection."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from app.core.correlation import correlation_uuid
from app.core.dependencies import get_db, get_redis
from app.events.consumers import audit_consumer
from app.modules.identity.audit import (
    AUDIT_EVENT_PROJECTIONS,
    MAX_PROJECTION_BYTES,
    MAX_TEXT_CHARS,
    TRUNCATED_MARKER,
    AuditQueryService,
    project_event_metadata,
)
from app.modules.identity.repository import AuditLogRepository, _audit_search_clause
from tests.auth_support import create_authorized_workspace, create_session_access_token

TERM_UUID = uuid.UUID(int=4242)


def _sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# ── Search semantics ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("term", [str(TERM_UUID), str(TERM_UUID).upper(), TERM_UUID.hex])
def test_uuid_search_matches_uuid_columns_exactly(term):
    sql = _sql(_audit_search_clause(term))
    for column in ("correlation_id", "resource_id", "actor_id", "event_id", "log_id"):
        assert f"audit_logs.{column} = '{TERM_UUID}'" in sql
    assert "CAST" not in sql.upper() and "LIKE" not in sql.upper()


def test_text_search_is_escaped_ilike_on_text_columns_only():
    sql = _sql(_audit_search_clause("50%_off/x"))
    assert "audit_logs.event_type ILIKE" in sql and "audit_logs.resource_type ILIKE" in sql
    # Wildcards and the escape character are escaped (literal rendering doubles '%').
    assert sql.count("'50/%%/_off//x'") == 2 and sql.count("ESCAPE '/'") == 2
    assert "CAST" not in sql.upper()
    for column in ("resource_id", "actor_id"):
        assert f"audit_logs.{column}" not in sql
    # An opaque request id finds its deterministic correlation UUID exactly.
    assert f"audit_logs.correlation_id = '{correlation_uuid('50%_off/x')}'" in sql


class _CapturingDb:
    def __init__(self, rows=()):
        self.statements = []
        self._rows = list(rows)

    async def execute(self, statement):
        self.statements.append(statement)
        result = MagicMock()
        result.scalar_one.return_value = len(self._rows)
        result.scalars.return_value.all.return_value = self._rows
        return result


async def test_platform_scope_selects_only_unscoped_rows():
    db = _CapturingDb()
    await AuditLogRepository(db).list_entries(platform_only=True, org_id=None, search="auth.user")
    listing = _sql(db.statements[-1])
    assert "audit_logs.org_id IS NULL" in listing
    assert "ORDER BY audit_logs.timestamp DESC, audit_logs.log_id DESC" in listing


async def test_org_scope_filters_by_org_and_whitespace_search_is_ignored():
    db = _CapturingDb()
    await AuditLogRepository(db).list_entries(org_id=TERM_UUID, search="   ", page=3, page_size=10)
    listing = _sql(db.statements[-1])
    assert f"audit_logs.org_id = '{TERM_UUID}'" in listing and "ILIKE" not in listing
    assert "LIMIT 10 OFFSET 20" in listing


async def test_audit_query_service_shapes_scoped_pages():
    row = SimpleNamespace(log_id=uuid.uuid4(), event_type="auth.user.logged_in", actor_id=uuid.uuid4(),
                          resource_type=None, resource_id=None, org_id=None, correlation_id=uuid.uuid4(),
                          timestamp=datetime.now(UTC), metadata_={"ip_address": "127.0.0.1"})
    db = _CapturingDb([row])
    page = await AuditQueryService(db).list_logs(scope="platform", org_id=None, page=1, page_size=5)
    assert page.scope == "platform" and page.total == 1 and page.items[0].metadata == {"ip_address": "127.0.0.1"}
    with pytest.raises(ValueError):
        await AuditQueryService(db).list_logs(scope="platform", org_id=TERM_UUID)
    with pytest.raises(ValueError):
        await AuditQueryService(db).list_logs(scope="org", org_id=None)


# ── Router authorization (real JWT/session/identity checks) ──────────────────

@pytest.fixture
async def audit_client(tenant_auth, mock_db, monkeypatch):
    from app.main import app

    listing = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(AuditLogRepository, "list_entries", listing)
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: tenant_auth.redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://test") as client:
            yield SimpleNamespace(client=client, listing=listing, identities=tenant_auth)
    finally:
        app.dependency_overrides.clear()


def _headers(roles=("Admin",), **scope):
    token, _ = create_session_access_token(
        user_id=str(uuid.uuid4()), email="auditor@example.com", roles=list(roles),
        permissions=["write:config", "read:topology"] if "Admin" in roles else ["read:topology"], **scope,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_platform_scope_is_global_admin_only(audit_client):
    response = await audit_client.client.get("/api/v1/audit/logs?scope=platform", headers=_headers())
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"items": [], "total": 0, "page": 1, "page_size": 50, "scope": "platform"}
    kwargs = audit_client.listing.await_args.kwargs
    assert kwargs["platform_only"] is True and kwargs["org_id"] is None
    denied = await audit_client.client.get("/api/v1/audit/logs?scope=platform", headers=_headers(("Read-Only",)))
    assert denied.status_code == 403


async def test_platform_scope_rejects_org_filter_and_narrowed_tokens(audit_client):
    org = audit_client.identities.org_id
    combined = await audit_client.client.get(f"/api/v1/audit/logs?scope=platform&org_id={org}", headers=_headers())
    assert combined.status_code == 422
    narrowed = await audit_client.client.get("/api/v1/audit/logs?scope=platform",
                                             headers=_headers(org_id=str(org)))
    assert narrowed.status_code == 403
    audit_client.listing.assert_not_awaited()


async def test_org_scope_requires_membership_and_hides_existence(audit_client):
    headers = _headers()
    member = await audit_client.client.get(f"/api/v1/audit/logs?org_id={audit_client.identities.org_id}",
                                           headers=headers)
    assert member.status_code == 200 and audit_client.listing.await_args.kwargs["org_id"] == audit_client.identities.org_id
    assert member.json()["data"]["scope"] == "org"
    audit_client.listing.reset_mock()
    absent = await audit_client.client.get(f"/api/v1/audit/logs?org_id={uuid.uuid4()}", headers=headers)
    audit_client.identities.memberships.clear()
    foreign = await audit_client.client.get(f"/api/v1/audit/logs?org_id={audit_client.identities.org_id}",
                                            headers=headers)
    assert absent.status_code == foreign.status_code == 403
    assert absent.json()["errors"] == foreign.json()["errors"]
    missing = await audit_client.client.get("/api/v1/audit/logs", headers=headers)
    assert missing.status_code == 403
    audit_client.listing.assert_not_awaited()


async def test_workspace_scoped_token_cannot_read_org_wide_audit(audit_client):
    workspace_id = create_authorized_workspace()
    headers = _headers(org_id=str(audit_client.identities.org_id), workspace_id=str(workspace_id))
    response = await audit_client.client.get(
        f"/api/v1/audit/logs?org_id={audit_client.identities.org_id}", headers=headers)
    assert response.status_code == 403
    audit_client.listing.assert_not_awaited()


@pytest.mark.parametrize(("query", "status_code"), [
    ("page=10001", 422), ("page=0", 422), ("page=10000", 200), ("scope=tenant", 422),
    ("resource_type=" + "x" * 101, 422),
])
async def test_audit_page_is_bounded(audit_client, query, status_code):
    org = audit_client.identities.org_id
    response = await audit_client.client.get(f"/api/v1/audit/logs?org_id={org}&{query}", headers=_headers())
    assert response.status_code == status_code, response.text


# ── Event projection (fix 10) ────────────────────────────────────────────────

def test_every_audited_event_type_declares_a_projection():
    assert set(audit_consumer._AUDIT_MAP) <= set(AUDIT_EVENT_PROJECTIONS)
    assert project_event_metadata("unknown.event.type", {"secret": "x"}) == {}


@pytest.mark.parametrize(("event_type", "payload"), [
    ("org.organization.created", {"org_id": "o", "name": "Org", "slug": "org", "actor_id": "a"}),
    ("org.organization.updated", {"org_id": "o", "changed_fields": {"name": "New"}, "actor_id": "a"}),
    ("org.organization.deleted", {"org_id": "o", "actor_id": "a"}),
    ("org.workspace.created", {"workspace_id": "w", "org_id": "o", "name": "W", "actor_id": "a"}),
    ("org.workspace.updated", {"workspace_id": "w", "org_id": "o",
                               "changed_fields": {"name": "W", "description": None}, "actor_id": "a"}),
    ("org.workspace.deleted", {"workspace_id": "w", "org_id": "o", "actor_id": "a"}),
    ("org.member.added", {"org_id": "o", "user_id": "u", "org_role": "Operator", "actor_id": "a",
                          "restored": True}),
    ("org.member.removed", {"org_id": "o", "user_id": "u", "actor_id": "a"}),
])
def test_org_lifecycle_projection_preserves_the_documented_payload(event_type, payload):
    # Direct append and consumer replay of one event must store identical metadata.
    assert project_event_metadata(event_type, payload) == payload


def test_projection_drops_unlisted_fields_and_keeps_audit_facts():
    payload = {
        "intent_id": str(uuid.uuid4()), "workspace_id": "w", "org_id": "o", "status": "execution_failed",
        "intent_kind": "reroute", "requested_by_user_id": "u",
        "validation_result": {"is_valid": True, "reasons": [{"code": "X", "message": "m" * 5000}]},
        "explainability": {"summary": "long " * 2000},
        "execution_provenance": {"executor": "manual_lab_v1", "approved_plan": {"steps": list(range(500))},
                                 "rollback": {"attempted": True, "status": "completed"}},
        "confidence": {"score": 0.0, "band": "below_60", "approval_required": True, "raw": [1] * 999},
        "credentials": "must-not-persist",
    }
    projected = project_event_metadata("intent.execution_failed", payload)
    assert "explainability" not in projected and "credentials" not in projected
    assert projected["validation_result"] == {"is_valid": True}
    assert projected["execution_provenance"] == {"executor": "manual_lab_v1",
                                                 "rollback": {"attempted": True, "status": "completed"}}
    assert projected["confidence"] == {"score": 0.0, "band": "below_60", "approval_required": True}
    assert TRUNCATED_MARKER not in projected


def test_projection_caps_text_containers_depth_and_total_size():
    capped = project_event_metadata("network.device.updated", {
        "device_id": "d", "hostname": "h" * (MAX_TEXT_CHARS + 50),
        "changed_fields": {f"field{index}": {"deep": {"deeper": {"deepest": 1}}} for index in range(40)},
    })
    assert len(capped["hostname"]) == MAX_TEXT_CHARS
    assert len(capped["changed_fields"]) == 32
    assert capped["changed_fields"]["field0"] == {"deep": None}
    assert capped[TRUNCATED_MARKER] is True
    huge = project_event_metadata("report.failed", {
        "report_id": "r", "status": "failed",
        "error": {f"k{index}": "v" * MAX_TEXT_CHARS for index in range(30)},
    })
    assert len(json.dumps(huge).encode()) <= MAX_PROJECTION_BYTES
    assert huge == {"report_id": "r", "status": "failed", TRUNCATED_MARKER: True}
    assert project_event_metadata("alert.generated", {"alert_id": "a", "severity": float("nan")}) == {
        "alert_id": "a", "severity": None, TRUNCATED_MARKER: True,
    }


async def test_consumer_persists_the_projection_not_the_payload():
    payload = {"simulation_id": str(uuid.uuid4()), "network_id": str(uuid.uuid4()), "state": "queued",
               "scenario_config": {"topology": "x" * 100_000}, "checkpoint": "y" * 100_000}
    append = AsyncMock()
    session = AsyncMock()
    session.__aenter__.return_value = AsyncMock()
    with (
        patch("app.events.consumers.audit_consumer.AsyncSessionLocal", return_value=session),
        patch("app.events.consumers.audit_consumer.append_audit_log", append),
    ):
        await audit_consumer.handle_audit_event({"event_id": str(uuid.uuid4()), "event_type": "simulation.started",
                                                 "correlation_id": "req_opaque", "payload": payload})
    metadata = append.await_args.kwargs["metadata"]
    assert metadata == {"simulation_id": payload["simulation_id"], "network_id": payload["network_id"],
                        "state": "queued", "request_id": "req_opaque"}
    assert append.await_args.kwargs["correlation_id"] == correlation_uuid("req_opaque")


async def test_org_direct_append_uses_the_same_projection(mock_db, fake_redis):
    from app.modules.organization.service import _commit_lifecycle

    payload = {"workspace_id": str(uuid.uuid4()), "org_id": str(uuid.uuid4()), "actor_id": str(uuid.uuid4()),
               "changed_fields": {"description": "d" * 4000}}
    with patch("app.modules.organization.service.append_audit_log", new_callable=AsyncMock) as append:
        await _commit_lifecycle(mock_db, fake_redis, event_type="org.workspace.updated", payload=payload,
                                correlation_id=str(uuid.uuid4()))
    assert append.await_args.kwargs["metadata"] == project_event_metadata("org.workspace.updated", payload)
    assert len(append.await_args.kwargs["metadata"]["changed_fields"]["description"]) == MAX_TEXT_CHARS
