"""Fresh-role/migration ordering and refusal tests; no database or Docker calls."""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from deploy import initialize


@pytest.fixture
def initializer(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "backend"))
    admin, owner = MagicMock(), MagicMock()
    admin_cursor = admin.cursor.return_value.__enter__.return_value
    owner_cursor = owner.cursor.return_value.__enter__.return_value
    admin_cursor.fetchone.return_value = (0,)
    owner_cursor.fetchone.return_value = (True,)
    connect = Mock(side_effect=[admin, owner])
    monkeypatch.setattr(initialize.psycopg2, "connect", connect)
    monkeypatch.setattr(initialize, "read_secret", lambda _: "test-only-password")
    monkeypatch.setenv("POSTGRES_USER", "nanfo_runtime")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only-runtime")
    migrate = Mock()
    seed = AsyncMock()
    monkeypatch.setattr(initialize.subprocess, "run", migrate)
    monkeypatch.setattr(initialize, "seed_actor", seed)
    return admin_cursor, owner_cursor, migrate, seed, connect


def test_fresh_migration_precedes_all_table_sequence_grants_and_seed(initializer):
    _, owner, migrate, seed, connect = initializer

    def check_migration(*args, **kwargs):
        # No owner grant/query can run against an old schema.
        assert owner.execute.call_count == 0
        assert connect.call_count == 1

    migrate.side_effect = check_migration
    initialize.main()
    migrate.assert_called_once_with(["alembic", "upgrade", "0029"], check=True)
    sql = [call.args[0] for call in owner.execute.call_args_list]
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nanfo_runtime"
        in sql
    )
    assert (
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nanfo_runtime" in sql
    )
    assert "REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM nanfo_runtime" in sql
    assert "REVOKE UPDATE, DELETE ON audit_logs FROM nanfo_runtime" in sql
    grant = next(value for value in sql if "pg_get_serial_sequence" in value)
    assert "network_spatial_scenes" in grant
    assert "pg_get_serial_sequence('network_outbox', 'sequence')" in grant
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert f"'network_outbox', '{privilege}'" in grant
        assert f"'network_spatial_scenes', '{privilege}'" in grant
    assert {call.args[1][0] for call in owner.execute.call_args_list if len(call.args) == 2} == {
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


@pytest.mark.parametrize("grant_result", [False, None])
def test_missing_new_table_or_identity_grant_refuses_before_seed(
    initializer, grant_result
):
    _, owner, _, seed, _ = initializer
    owner.fetchone.return_value = (grant_result,)
    with pytest.raises(ValueError, match="privileges unavailable"):
        initialize.main()
    seed.assert_not_awaited()


def test_existing_database_never_migrates_or_grants(initializer):
    admin, owner, migrate, seed, connect = initializer
    admin.fetchone.return_value = (1,)
    with pytest.raises(ValueError, match="implicit migration"):
        initialize.main()
    migrate.assert_not_called()
    owner.execute.assert_not_called()
    seed.assert_not_awaited()
    assert connect.call_count == 1
