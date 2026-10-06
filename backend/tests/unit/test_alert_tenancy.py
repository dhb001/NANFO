"""ADR-028 alert tenancy columns, exact in-memory scope checks and SQL shape."""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.alert.models import AlertRecord
from app.modules.alert.repository import AlertRepository, _filters, escape_like
from app.modules.alert.scope import AlertListScope, is_platform_scoped, scope_columns

ORG, WORKSPACE, NETWORK, OTHER = (uuid.UUID(int=i) for i in (901, 902, 903, 904))
NOW = datetime(2026, 9, 23, tzinfo=UTC)


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect()))


class CapturingSession:
    """Records statements; returns empty results (no database)."""

    def __init__(self):
        self.statements, self.added = [], []

    async def execute(self, statement):
        self.statements.append(statement)
        result = MagicMock()
        result.all.return_value = []
        result.scalars.return_value.all.return_value = []
        return result

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


@pytest.mark.parametrize("payload,expected", [
    ({"workspace_id": str(WORKSPACE), "scope": {"workspace_id": str(OTHER)}},
     {"org_id": None, "workspace_id": WORKSPACE, "network_id": None}),
    ({"scope": {"workspace_id": str(WORKSPACE), "org_id": str(ORG), "network_id": str(NETWORK)}},
     {"org_id": ORG, "workspace_id": WORKSPACE, "network_id": NETWORK}),
    ({"workspace_id": None, "scope": {"workspace_id": str(WORKSPACE).upper()}},
     {"org_id": None, "workspace_id": WORKSPACE, "network_id": None}),
    ({"network_id": str(NETWORK)}, {"org_id": None, "workspace_id": None, "network_id": NETWORK}),
    # Any present non-UUID value leaves every column NULL (legacy fail-closed path).
    ({"workspace_id": "not-a-uuid", "org_id": str(ORG)}, {"org_id": None, "workspace_id": None, "network_id": None}),
    ({"scope": "not-a-dict", "org_id": str(ORG)}, {"org_id": ORG, "workspace_id": None, "network_id": None}),
    (None, {"org_id": None, "workspace_id": None, "network_id": None}),
])
def test_scope_columns_mirror_recorded_scope_precedence(payload, expected):
    assert scope_columns(payload) == expected


SCOPE = AlertListScope(workspace_orgs={WORKSPACE: ORG}, member_org_ids=frozenset({ORG}),
                       networks={NETWORK: WORKSPACE})


@pytest.mark.parametrize("payload,allowed", [
    ({"workspace_id": str(WORKSPACE)}, True),
    ({"workspace_id": str(WORKSPACE), "org_id": str(ORG)}, True),
    ({"workspace_id": str(WORKSPACE), "org_id": str(OTHER)}, False),  # inconsistent org
    ({"workspace_id": str(OTHER)}, False),
    ({"network_id": str(NETWORK)}, True),  # legacy network-only
    ({"workspace_id": str(WORKSPACE), "network_id": str(NETWORK)}, True),
    ({"workspace_id": str(OTHER), "network_id": str(NETWORK)}, False),  # network outside workspace
    ({"workspace_id": str(WORKSPACE), "network_id": str(OTHER)}, False),  # unknown/deleted network
    ({"org_id": str(ORG)}, True),  # org-only with live membership
    ({"org_id": str(OTHER)}, False),
    ({}, False),  # unscoped infrastructure alerts stay denied
    ({"workspace_id": "garbage"}, False),
    ({"scope": {"workspace_id": str(WORKSPACE), "org_id": str(ORG)}}, True),
])
def test_in_memory_scope_check_matches_owner_authorization(payload, allowed):
    assert SCOPE.allows(payload) is allowed


def test_network_selection_excludes_other_and_non_network_rows():
    selected = AlertListScope(workspace_orgs={WORKSPACE: ORG}, networks={NETWORK: WORKSPACE}, network_id=NETWORK)
    assert selected.allows({"workspace_id": str(WORKSPACE), "network_id": str(NETWORK)})
    assert not selected.allows({"workspace_id": str(WORKSPACE)})
    assert not selected.allows({"org_id": str(ORG)})


def test_search_is_escaped_bounded_and_field_specific():
    (clause,) = _filters(status=None, severity=None, source=None, correlation_id=None, search="  50%_off\\x  ")
    compiled = clause.compile(dialect=postgresql.dialect())
    text = str(compiled)
    assert "ESCAPE '\\\\'" in text or "ESCAPE '\\'" in text
    assert "CAST(alerts.payload AS VARCHAR)" not in text
    assert "alerts.alert_key ILIKE" in text and "alerts.source ILIKE" in text
    assert "->> %(payload_" in text or "->>" in text  # specific payload text fields only
    assert set(compiled.params.values()) >= {"%50\\%\\_off\\\\x%"}
    assert escape_like("a%b_c\\") == "a\\%b\\_c\\\\"
    with pytest.raises(ValueError):
        _filters(status=None, severity=None, source=None, correlation_id=None, search="x" * 201)


def test_created_range_filters_are_start_inclusive_end_exclusive():
    later = NOW.replace(day=24)
    clauses = _filters(status=None, severity=None, source=None, correlation_id=None, search=None,
                       created_from=NOW, created_before=later)
    assert [sql(clause) for clause in clauses] == [
        "alerts.created_at >= %(created_at_1)s", "alerts.created_at < %(created_at_1)s"]


async def test_list_query_serves_workspace_rows_from_the_tenancy_index_branch():
    db = CapturingSession()
    await AlertRepository(db).list_alerts(status="active", severity=None, source=None, correlation_id=None,
                                          search=None, limit=200, scope=SCOPE)
    text = sql(db.statements[0])
    workspace_branch, null_branch = text.split(" UNION ALL ")
    assert "alerts.workspace_id = %(workspace_id_1)s" in workspace_branch
    assert "ORDER BY alerts.updated_at DESC, alerts.alert_id DESC" in workspace_branch
    assert "->>" not in workspace_branch  # no JSON predicates on the indexed branch
    # JSON predicates survive only for rows without any tenancy column.
    assert "alerts.workspace_id IS NULL" in null_branch
    assert "alerts.network_id IS NULL AND alerts.org_id IS NULL" in null_branch
    assert "ORDER BY alert_page.updated_at DESC, alert_page.alert_id DESC" in text


async def test_count_query_uses_the_same_scope_without_limit():
    db = CapturingSession()
    counts = await AlertRepository(db).count_alerts(status=None, severity="warning", source=None, correlation_id=None,
                                                   search=None, scope=SCOPE)
    text = sql(db.statements[0])
    assert counts == {}
    assert "count(*)" in text and "GROUP BY alerts.status" in text and "LIMIT" not in text
    assert "alerts.workspace_id = %(workspace_id_1)s" in text and "alerts.severity = " in text


async def test_empty_scope_never_queries():
    db = CapturingSession()
    repo = AlertRepository(db)
    assert await repo.list_alerts(status=None, severity=None, source=None, correlation_id=None, search=None,
                                  limit=10, scope=AlertListScope()) == []
    assert await repo.count_alerts(status=None, severity=None, source=None, correlation_id=None, search=None,
                                   scope=AlertListScope()) == {}
    assert db.statements == []


async def test_multi_workspace_scope_pairs_workspace_and_org():
    db = CapturingSession()
    scope = AlertListScope(workspace_orgs={WORKSPACE: ORG, NETWORK: ORG, OTHER: uuid.UUID(int=905)})
    await AlertRepository(db).list_alerts(status=None, severity=None, source=None, correlation_id=None,
                                          search=None, limit=5, scope=scope)
    compiled = db.statements[0].compile(dialect=postgresql.dialect())
    text = str(compiled)
    # Several workspaces of one organization bind as ONE array (stable statement
    # text for any set size); each organization pairs only with its workspaces.
    assert "alerts.workspace_id = ANY (%(workspace_ids_1)s::UUID[])" in text
    assert "alerts.workspace_id = %(workspace_id_1)s" in text
    assert text.count("alerts.org_id IS NULL OR alerts.org_id = ") == 2
    assert compiled.params["workspace_ids_1"] == sorted([WORKSPACE, NETWORK])
    assert " IN (" not in text and "POSTCOMPILE" not in text


async def test_many_organizations_and_legacy_networks_use_array_binds():
    db = CapturingSession()
    orgs = [uuid.UUID(int=910 + i) for i in range(3)]
    scope = AlertListScope(workspace_orgs={uuid.UUID(int=920 + i): orgs[0] for i in range(40)},
                           member_org_ids=frozenset(orgs), networks={uuid.UUID(int=960 + i): uuid.UUID(int=920 + i)
                                                                     for i in range(30)})
    await AlertRepository(db).count_alerts(status=None, severity=None, source=None, correlation_id=None,
                                           search=None, scope=scope)
    compiled = db.statements[0].compile(dialect=postgresql.dialect())
    text = str(compiled)
    assert "alerts.network_id = ANY (" in text and "alerts.org_id = ANY (" in text
    assert "::TEXT[]" in text  # the JSON fallback binds text arrays too
    assert len(compiled.params["workspace_ids_1"]) == 40 and len(compiled.params["network_ids_1"]) == 30
    assert " IN (" not in text and "POSTCOMPILE" not in text


async def test_legacy_network_probe_reads_only_alert_owned_null_workspace_rows():
    db = CapturingSession()
    assert await AlertRepository(db).legacy_network_ids(limit=11) == []
    text = sql(db.statements[0])
    assert "alerts.workspace_id IS NULL" in text and " UNION " in text and "LIMIT" in text


async def test_create_and_transitions_stamp_tenancy_columns_from_the_payload():
    db = CapturingSession()
    repo = AlertRepository(db)
    payload = {"org_id": str(ORG), "workspace_id": str(WORKSPACE), "network_id": str(NETWORK)}
    alert = await repo.create_generated(alert_id=uuid.uuid4(), alert_key="k", source="telemetry", severity="warning",
                                        correlation_id=uuid.uuid4(), payload=payload, generated_event_id=uuid.uuid4(),
                                        created_at=NOW)
    assert (alert.org_id, alert.workspace_id, alert.network_id) == (ORG, WORKSPACE, NETWORK)
    await repo.mark_acknowledged(alert, acknowledged_by_user_id="u", acknowledged_at=NOW,
                                 payload={"scope": {"workspace_id": str(OTHER)}}, acknowledged_event_id=None)
    assert (alert.org_id, alert.workspace_id, alert.network_id) == (None, OTHER, None)
    await repo.mark_resolved(alert, resolved_by_user_id="u", resolved_at=NOW, payload={"workspace_id": "bad"},
                             resolved_event_id=None)
    assert (alert.org_id, alert.workspace_id, alert.network_id) == (None, None, None)
    assert isinstance(alert, AlertRecord)


def test_measured_payload_scope_is_indexed():
    """Measured incidents record top-level org/workspace/network identity."""
    from app.modules.alert.detector import DetectorSettings, detector_identity
    from tests.alert_support import observation

    sample = observation()
    identity = detector_identity(sample, ORG, DetectorSettings().utilization)
    assert scope_columns(identity) == {"org_id": ORG, "workspace_id": sample.workspace_id,
                                       "network_id": sample.network_id}


# ── Platform-scoped SLO alerts (BE-Telemetry request) ────────────────────────

PLATFORM = {"alert_key": "telemetry_runtime_adapter_slo_threshold_breach", "alert_scope": "platform",
            "org_id": None, "workspace_id": None, "network_id": None, "severity": "warning",
            "evaluation_window": {"start": "2026-09-23T00:00:00+00:00", "end": "2026-09-23T00:00:30+00:00",
                                  "seconds": 30.0, "counter_reset": False}}


@pytest.mark.parametrize("payload,platform", [
    (PLATFORM, True),
    ({"alert_scope": "platform", "org_id": str(ORG)}, True),  # no workspace: still never tenant-visible
    ({"alert_scope": "platform", "network_id": "garbage"}, True),
    ({"alert_scope": "platform", "workspace_id": str(WORKSPACE)}, False),  # workspace-scoped: a tenant row
    ({"alert_scope": "platform", "scope": {"workspace_id": str(WORKSPACE)}}, False),
    ({"alert_scope": "platform", "workspace_id": "garbage"}, False),  # invalid is not "no workspace"
    ({"alert_scope": "Platform"}, False),
    ({"scope": {"alert_scope": "platform"}}, False),
    ({}, False),
    (None, False),
])
def test_platform_scope_marker(payload, platform):
    assert is_platform_scoped(payload) is platform


def test_platform_alerts_need_platform_authority_and_tenants_never_see_them():
    assert not SCOPE.allows(PLATFORM)
    # Even members of a recorded organization never see a platform alert.
    assert not SCOPE.allows({"alert_scope": "platform", "org_id": str(ORG)})
    admin = AlertListScope(platform=True)
    assert not admin.empty
    assert admin.allows(PLATFORM) and admin.allows({"alert_scope": "platform", "org_id": str(ORG)})
    assert not admin.allows({})  # unscoped non-platform rows stay denied
    assert not admin.allows({"workspace_id": str(WORKSPACE)})  # platform authority is not tenant authority
    assert not AlertListScope(platform=True, network_id=NETWORK).allows(PLATFORM)
    member_admin = AlertListScope(workspace_orgs={WORKSPACE: ORG}, platform=True)
    assert member_admin.allows({"alert_scope": "platform", "workspace_id": str(WORKSPACE)})
    assert AlertListScope().empty


async def test_platform_rows_are_selected_only_for_platform_authority():
    tenant_db, admin_db = CapturingSession(), CapturingSession()
    await AlertRepository(tenant_db).list_alerts(status=None, severity=None, source=None, correlation_id=None,
                                                 search=None, limit=20, scope=SCOPE)
    await AlertRepository(admin_db).list_alerts(status=None, severity=None, source=None, correlation_id=None,
                                                search=None, limit=20, scope=AlertListScope(platform=True))
    tenant = tenant_db.statements[0].compile(dialect=postgresql.dialect())
    admin = admin_db.statements[0].compile(dialect=postgresql.dialect())
    # Tenant NULL-workspace rows exclude platform-marked rows; only the admin selects them.
    assert "NOT (coalesce((alerts.payload ->> " in str(tenant) and "platform" in tenant.params.values()
    admin_sql = str(admin)
    assert " UNION ALL " not in admin_sql and "NOT (" not in admin_sql
    assert "alerts.workspace_id IS NULL AND coalesce((alerts.payload ->> " in admin_sql
    assert "platform" in admin.params.values()
    count_db = CapturingSession()
    assert await AlertRepository(count_db).count_alerts(status=None, severity=None, source=None, correlation_id=None,
                                                        search=None, scope=AlertListScope(platform=True)) == {}
    assert len(count_db.statements) == 1
    probe_db = CapturingSession()
    await AlertRepository(probe_db).legacy_network_ids(limit=3)
    assert "NOT (coalesce((alerts.payload ->> " in sql(probe_db.statements[0])


async def test_platform_alerts_are_never_enumerated_as_unknown_tenant_evidence():
    import json

    from app.modules.alert.measured import telemetry_reference_page

    statements = []

    class ReferenceSession:
        async def scalars(self, statement):
            statements.append(statement)
            result = MagicMock()
            result.all.return_value = []
            return result

    for stage in (1, 2):  # AlertRecord, AlertHistory
        page = await telemetry_reference_page(ReferenceSession(), workspace_id=WORKSPACE,
                                              after=json.dumps([stage, None]), limit=10)
        assert page.items == []
    assert len(statements) == 2
    for statement in statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        text = str(compiled)
        # Unscoped legacy rows are still enumerated (as unknown); platform rows are not.
        assert "IS NULL AND coalesce((" in text and ") != %(" in text
        assert "platform" in compiled.params.values() and str(WORKSPACE) in compiled.params.values()
