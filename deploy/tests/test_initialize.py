"""Fresh-role/migration ordering and refusal tests; no database or Docker calls."""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from psycopg2 import sql

from deploy import initialize
from deploy.schema_contract import CURRENT_SCHEMA

VERIFIER = "SCRAM-SHA-256$4096:c2FsdA==$c3RvcmVkLWtleQ==:c2VydmVyLWtleQ=="


def literals(statement):
    """Literal values inside a psycopg2 Composed statement (never rendered to SQL)."""
    if isinstance(statement, sql.Literal):
        return [statement.wrapped]
    if isinstance(statement, sql.Composed):
        return [value for part in statement.seq for value in literals(part)]
    return []


@pytest.fixture
def initializer(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "backend"))
    admin, owner = MagicMock(), MagicMock()
    admin_cursor = admin.cursor.return_value.__enter__.return_value
    owner_cursor = owner.cursor.return_value.__enter__.return_value
    admin_cursor.fetchone.return_value = (0,)
    state = {"audit": (False,), "purge": (True,), "grants": (True,), "admin": admin}

    def owner_fetchone():
        statement = str(owner_cursor.execute.call_args.args[0])
        if "'audit_logs'" in statement:
            return state["audit"]
        if "purge_table" in statement:
            return state["purge"]
        return state["grants"]

    owner_cursor.fetchone.side_effect = owner_fetchone
    connect = Mock(side_effect=[admin, owner])
    monkeypatch.setattr(initialize.psycopg2, "connect", connect)
    monkeypatch.setattr(initialize, "read_secret", lambda _: "test-only-password")
    encrypt = Mock(return_value=VERIFIER)
    monkeypatch.setattr(initialize, "encrypt_password", encrypt)
    guard = Mock(return_value=CURRENT_SCHEMA)
    monkeypatch.setattr(initialize, "require_consistent_schema", guard)
    monkeypatch.setenv("POSTGRES_USER", "nanfo_runtime")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only-runtime")
    migrate = Mock()
    seed = AsyncMock()
    monkeypatch.setattr(initialize.subprocess, "run", migrate)
    monkeypatch.setattr(initialize, "seed_actor", seed)
    return admin_cursor, owner_cursor, migrate, seed, connect, state, encrypt, guard


def test_fresh_migration_precedes_all_table_sequence_grants_and_seed(initializer):
    _, owner, migrate, seed, connect, _, _, _ = initializer

    def check_migration(*args, **kwargs):
        # No owner grant/query can run against an old schema.
        assert owner.execute.call_count == 0
        assert connect.call_count == 1

    migrate.side_effect = check_migration
    initialize.main()
    migrate.assert_called_once_with(["alembic", "upgrade", CURRENT_SCHEMA], check=True)
    sql_text = [call.args[0] for call in owner.execute.call_args_list]
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nanfo_runtime"
        in sql_text
    )
    assert (
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nanfo_runtime" in sql_text
    )
    assert "REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM nanfo_runtime" in sql_text
    assert "REVOKE UPDATE, DELETE ON audit_logs FROM nanfo_runtime" in sql_text
    grant = next(value for value in sql_text if "pg_get_serial_sequence" in value)
    assert "network_spatial_scenes" in grant
    assert "pg_get_serial_sequence('network_outbox', 'sequence')" in grant
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert f"'network_outbox', '{privilege}'" in grant
        assert f"'network_spatial_scenes', '{privilege}'" in grant
    per_table = {call.args[1][0] for call in owner.execute.call_args_list
                 if len(call.args) == 2 and isinstance(call.args[1][0], str)}
    assert per_table == {
        "network_spatial_scene_revisions",
        "campus_model_assets",
        "telemetry_evidence_pins",
        "telemetry_reference_coverage",
        "telemetry_event_tombstones",
        "telemetry_archive_receipts",
        "telemetry_reference_reconciliation",
        "telemetry_fleet_devices",
        "telemetry_fleet_spool",
        "autonomous_resources",
        "autonomous_executions",
        "autonomous_observations",
        "autonomous_provider_state",
        "experimental_lab_resources",
        "experimental_lab_runs",
        "experimental_lab_actions",
        "experimental_lab_receipts",
    }
    seed.assert_awaited_once()


def test_retention_purge_tables_are_proven_deletable_and_audit_stays_append_only(initializer):
    _, owner, _, seed, _, _, _, _ = initializer
    initialize.main()
    purge = next(call for call in owner.execute.call_args_list if "purge_table" in str(call.args[0]))
    assert "'DELETE'" in purge.args[0] and "'SELECT'" in purge.args[0]
    assert purge.args[1] == ([
        "network_outbox", "report_outbox", "reports", "simulation_outbox", "intent_outbox",
        "alert_observations", "autonomy_decisions",
    ],)
    audit = next(call.args[0] for call in owner.execute.call_args_list if "'audit_logs'" in str(call.args[0]))
    assert all(f"'audit_logs', '{privilege}'" in audit for privilege in ("UPDATE", "DELETE", "TRUNCATE"))
    # No broader privilege than the existing schema DML grant is added for purges.
    assert not any("TRUNCATE" in str(call.args[0]) and "GRANT" in str(call.args[0])
                   for call in owner.execute.call_args_list)
    seed.assert_awaited_once()


@pytest.mark.parametrize("fault,value,message", [
    ("purge", (False,), "retention/purge DELETE"),
    ("purge", (None,), "retention/purge DELETE"),
    ("audit", (True,), "append-only"),
    ("audit", (None,), "append-only"),
])
def test_missing_purge_privilege_or_mutable_audit_refuses_before_seed(initializer, fault, value, message):
    _, _, _, seed, _, state, _, _ = initializer
    state[fault] = value
    with pytest.raises(ValueError, match=message):
        initialize.main()
    seed.assert_not_awaited()


def test_roles_receive_scram_verifiers_never_plaintext_sql(initializer):
    admin, _, _, _, _, state, encrypt, _ = initializer
    initialize.main()
    creates = [call.args[0] for call in admin.execute.call_args_list if isinstance(call.args[0], sql.Composed)]
    assert len(creates) == 2
    for statement in creates:
        assert literals(statement) == [VERIFIER]
    assert [call.args[1] for call in encrypt.call_args_list] == ["nanfo_owner", "nanfo_runtime"]
    assert {call.args[0] for call in encrypt.call_args_list} == {"test-only-password", "test-only-runtime"}
    # libpq computes the verifier against the admin connection, with explicit SCRAM.
    assert all(call.args[2] is state["admin"] and call.args[3] == "scram-sha-256"
               for call in encrypt.call_args_list)
    assert not any("test-only" in str(value) for statement in creates for value in literals(statement))


def test_verifier_must_be_a_scram_hash_without_the_password(monkeypatch):
    monkeypatch.setattr(initialize, "encrypt_password", Mock(return_value="md5deadbeef"))
    with pytest.raises(ValueError, match="SCRAM"):
        initialize.scram_verifier(object(), "nanfo_runtime", "password-0123456789")
    monkeypatch.setattr(initialize, "encrypt_password", Mock(return_value="SCRAM-SHA-256$password-0123456789"))
    with pytest.raises(ValueError, match="SCRAM"):
        initialize.scram_verifier(object(), "nanfo_runtime", "password-0123456789")


def test_lagging_schema_contract_refuses_before_any_connection(initializer):
    _, _, migrate, seed, connect, _, _, guard = initializer
    guard.side_effect = ValueError("Backend schema contract 0029 lags migration head 0030")
    with pytest.raises(ValueError, match="lags migration head"):
        initialize.main()
    connect.assert_not_called()
    migrate.assert_not_called()
    seed.assert_not_awaited()


@pytest.mark.parametrize("grant_result", [False, None])
def test_missing_new_table_or_identity_grant_refuses_before_seed(
    initializer, grant_result
):
    _, _, _, seed, _, state, _, _ = initializer
    state["grants"] = (grant_result,)
    with pytest.raises(ValueError, match="privileges unavailable"):
        initialize.main()
    seed.assert_not_awaited()


def test_existing_database_never_migrates_or_grants(initializer):
    admin, owner, migrate, seed, connect, _, _, _ = initializer
    admin.fetchone.return_value = (1,)
    with pytest.raises(ValueError, match="implicit migration"):
        initialize.main()
    migrate.assert_not_called()
    owner.execute.assert_not_called()
    seed.assert_not_awaited()
    assert connect.call_count == 1
