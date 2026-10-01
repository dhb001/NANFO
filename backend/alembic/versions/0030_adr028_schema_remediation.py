"""ADR-028 BE-DB schema remediation (migration §4; contracts C3, C8, C20).

Revision ID: 0030
Revises: 0029 (revision 0031 is reserved for BE-Telemetry retention)

Migration notes (data changes; nothing is deleted):

* intents (C3): among rows sharing ``(workspace_id, idempotency_key)`` the earliest
  row (``created_at, requested_at, intent_id``) keeps its key and every later row's
  key becomes ``<key>~dup~<intent_id>`` (the original key is the prefix). Then the
  partial unique index ``uq_intents_workspace_idempotency`` is created.
* campus_buildings: among active rows sharing ``(network_id, building_id)`` the most
  recently updated row stays active; older rows are soft deleted (``deleted_at`` and
  ``updated_at`` = now(), the repository's soft-delete convention). Then
  ``uq_campus_buildings_network_building_active`` backs the owner's ON CONFLICT upsert.
* alerts: nullable ``org_id/workspace_id/network_id`` are backfilled from the payload
  in bounded keyset batches exactly as ``app.modules.alert.scope.scope_columns``
  derives them: the top-level value unless it is absent/JSON null, else the nested
  ``scope`` object's value; a present value must be a JSON string that is a UUID
  (``urn:``/``uuid:`` prefixes, surrounding braces and hyphens are tolerated like
  Python's ``uuid.UUID``); if any present value is invalid every column stays NULL
  (rows keep the legacy JSON predicate plus the in-memory recheck). Non-string JSON
  values are never accepted (Python would accept a 32-digit JSON integer; SQL is
  stricter, which only leaves such rows on the NULL/legacy path).

Schema changes: indexes for the telemetry/audit/alert hot paths (created CONCURRENTLY),
BRIN indexes on telemetry and alert-observation time (retention range scans), indexes
for every foreign key, same-module foreign keys
(NOT VALID, validated only when no orphan exists), fixed server defaults (devices.status
stored the quoted literal ``'active'``; plugin outcome defaults now match the model;
autonomy_overrides timestamps default to now()), ``claim_attempts`` (reports,
simulations), ``created_at`` on the simulation/report outboxes, closed-set status CHECKs
(NOT VALID, validated only when no row violates them), partial indexes for blocking-work
and deferred-publication sweeps, and delta storage columns on the immutable spatial
scene history (its UPDATE/DELETE/TRUNCATE triggers are row/statement triggers and do
not fire for ALTER TABLE).

Dropped as truly redundant (a single-column, non-unique, non-partial btree index whose
column leads another non-partial btree index or unique constraint on the same table):
``ix_telemetry_records_device_id`` (ix_telemetry_records_device_observed),
``ix_telemetry_records_workspace_id`` (ix_telemetry_workspace_keyset),
``ix_reports_workspace_id`` (ix_reports_history, uq_reports_workspace_idempotency),
``ix_reports_status`` (ix_reports_worker), ``ix_users_email`` (users_email_key) and
``ix_organizations_slug`` (organizations_slug_key). Indexes whose column only leads a
*partial* index (for example ix_simulations_state, ix_intents_network_id) are kept.

Operations: part A runs in the migration transaction under the environment's
``lock_timeout``. Part B (alert backfill batches, CONCURRENTLY index builds on large
tables, constraint validation) runs in an autocommit block with ``lock_timeout``
suspended (concurrent builds wait for older transactions but never block writers).
Every step is idempotent, so a failure in part B is recovered by re-running the
upgrade. When the caller already owns the transaction (for example test fixtures
running migrations inside ``engine.begin()``), part B runs as plain statements in it.

Downgrade reverses everything. It refuses (raises) while delta-encoded spatial history
exists, because the 0029 schema cannot hold it and that history is immutable. The alert
tenancy columns are an indexed projection of the retained payload, claim counters are
operational state; both are dropped. Renamed idempotency keys are restored unless an
execution already bound the renamed key; soft-deleted campus duplicates stay deleted.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator, Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.migration.0030")
BATCH_SIZE_SETTING = "NANFO_MIGRATION_BATCH_SIZE"  # rows per alert backfill batch (1..100000)
DEFAULT_BATCH_SIZE = 5000

# Closed value sets, derived from every writer in the owning module (and its history).
ALERT_STATUSES = ("active", "acknowledged", "resolved")
# Written: draft (default), validated, rejected, execution_{started,completed,failed};
# documented terminal outcomes (intent/queries.py SAFE_TERMINAL_STATUSES) are allowed too.
INTENT_STATUSES = ("draft", "validated", "rejected", "execution_started", "execution_completed",
                   "execution_failed", "cancelled", "compensated", "execution_cancelled",
                   "execution_compensated")
INTENT_QUEUE_STATUSES = ("pending", "validated", "deferred", "queued", "outbox_pending")
SIMULATION_STATES = ("draft", "queued", "running", "paused", "completed", "cancelled", "failed")
REPORT_STATUSES = ("requested", "running", "generated", "failed")
EXECUTION_PHASES = ("accepted", "dispatching", "cancelling", "completed", "failed", "cancelled", "uncertain")
LAB_ACTION_PHASES = ("observing", "observed", "inferred", "simulated", "preparing", "prepared",
                     "dispatching", "verifying", "verified", "holding", "recovering", "restored",
                     "rejected", "uncertain")
LAB_RUN_PHASES = ("observing", "bootstrap_prepared", "bootstrapped", "bootstrap_recovering", "observed",
                  "inferred", "simulated", "preparing", "prepared", "dispatching", "verifying",
                  "verified", "holding", "recovering", "restored", "uncertain")
ORG_ROLES = ("Admin", "Operator", "Read-Only")
PLUGIN_QUEUE_STATUSES = ("pending", "deferred", "queued", "not_applicable")
# Statuses after which an intent/simulation/execution cannot affect the network any more
# (intent/queries.py, simulation/queries.py, intent/operations.py).
INTENT_SETTLED_STATUSES = ("cancelled", "compensated", "execution_cancelled", "execution_compensated",
                           "execution_completed", "execution_failed", "rejected")
SIMULATION_TERMINAL_STATUSES = ("cancelled", "completed", "failed")
EXECUTION_TERMINAL_PHASES = ("completed", "failed", "cancelled")


def in_list(column: str, values: Sequence[str], *, negate: bool = False) -> str:
    quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
    return f"{column} {'NOT IN' if negate else 'IN'} ({quoted})"


STATUS_CHECKS = (
    ("ck_alerts_status", "alerts", in_list("status", ALERT_STATUSES)),
    ("ck_intents_status", "intents", in_list("status", INTENT_STATUSES)),
    ("ck_intents_queue_status", "intents", in_list("queue_status", INTENT_QUEUE_STATUSES)),
    ("ck_simulations_state", "simulations", in_list("state", SIMULATION_STATES)),
    ("ck_simulations_status", "simulations", in_list("status", SIMULATION_STATES)),
    ("ck_reports_status", "reports", in_list("status", REPORT_STATUSES)),
    ("ck_intent_executions_phase", "intent_executions", in_list("phase", EXECUTION_PHASES)),
    ("ck_experimental_action_phase", "experimental_lab_actions", in_list("phase", LAB_ACTION_PHASES)),
    ("ck_experimental_run_phase", "experimental_lab_runs", in_list("phase", LAB_RUN_PHASES)),
    ("ck_org_members_org_role", "org_members", in_list("org_role", ORG_ROLES)),
    ("ck_plugins_queue_status", "plugins", in_list("queue_status", PLUGIN_QUEUE_STATUSES)),
)
SPATIAL_HISTORY = "network_spatial_scene_revisions"
SPATIAL_CHECKS = (
    ("ck_spatial_history_storage_kind", "storage_kind IN ('full', 'delta')"),
    ("ck_spatial_history_body", "(storage_kind = 'full' AND scene IS NOT NULL) OR "
                                "(storage_kind = 'delta' AND delta IS NOT NULL AND base_revision IS NOT NULL)"),
)
# (name, table, column, referred table, referred column, ON DELETE). Same module only.
# Report retention deletes reports whose outbox rows are published: they go with the report.
FOREIGN_KEYS = (
    ("fk_report_outbox_report", "report_outbox", "report_id", "reports", "report_id", "CASCADE"),
    ("fk_alert_observations_detector", "alert_observations", "detector_key", "alert_detector_states",
     "detector_key", None),
    ("fk_autonomous_executions_resource", "autonomous_executions", "resource_id", "autonomous_resources",
     "resource_id", None),
)
# Small tables: built inside the migration transaction. (name, table, columns, where)
INDEXES = (
    ("ix_alert_detector_states_incident_id", "alert_detector_states", ("incident_id",), None),
    ("ix_experimental_lab_receipts_request_id", "experimental_lab_receipts", ("request_id",), None),
    ("ix_experimental_lab_runs_resource_id", "experimental_lab_runs", ("resource_id",), None),
    ("ix_user_roles_role_id", "user_roles", ("role_id",), None),
    ("ix_autonomous_executions_resource_id", "autonomous_executions", ("resource_id",), None),
    ("ix_intents_network_blocking", "intents", ("network_id",),
     in_list("status", INTENT_SETTLED_STATUSES, negate=True)),
    ("ix_intent_executions_unresolved", "intent_executions", ("created_at",),
     in_list("phase", EXECUTION_TERMINAL_PHASES, negate=True)),
    ("ix_simulations_network_active", "simulations", ("network_id",),
     in_list("status", SIMULATION_TERMINAL_STATUSES, negate=True)),
    ("ix_autonomous_executions_network_unreleased", "autonomous_executions", ("network_id",), "released = false"),
    ("ix_intents_deferred_updated", "intents", ("updated_at",), "queue_status = 'deferred'"),
    ("ix_plugins_deferred_updated", "plugins", ("updated_at",), "queue_status = 'deferred'"),
)
# Large tables: CREATE INDEX CONCURRENTLY. (name, table, columns, method)
CONCURRENT_INDEXES = (
    ("ix_telemetry_records_device_observed", "telemetry_records",
     ("device_id", "observed_at DESC", "record_id DESC"), None),
    ("ix_telemetry_records_observed_at_brin", "telemetry_records", ("observed_at",), "brin"),
    ("ix_audit_logs_org_timestamp", "audit_logs", ("org_id", '"timestamp" DESC', "log_id DESC"), None),
    ("ix_alerts_workspace_updated", "alerts", ("workspace_id", "updated_at DESC", "alert_id DESC"), None),
    ("ix_alerts_network_id", "alerts", ("network_id",), None),
    ("ix_alert_consumed_events_alert_id", "alert_consumed_events", ("alert_id",), None),
    ("ix_alert_observations_detector_key", "alert_observations", ("detector_key",), None),
    # Observation retention prunes by time (AlertRepository.purge_observations).
    ("ix_alert_observations_observed_at_brin", "alert_observations", ("observed_at",), "brin"),
)
# Truly redundant indexes (see module notes): (name, table, column, on a large table)
REDUNDANT_INDEXES = (
    ("ix_telemetry_records_device_id", "telemetry_records", "device_id", True),
    ("ix_telemetry_records_workspace_id", "telemetry_records", "workspace_id", True),
    ("ix_reports_workspace_id", "reports", "workspace_id", False),
    ("ix_reports_status", "reports", "status", False),
    ("ix_users_email", "users", "email", False),
    ("ix_organizations_slug", "organizations", "slug", False),
)
# (table, column, fixed default, previous default exactly as earlier migrations stored it)
SERVER_DEFAULTS = (
    ("devices", "status", "active", "'active'"),
    ("plugins", "signature_status", "declared_unverified", sa.text("'unverified'")),
    ("plugins", "dependency_status", "declared_unverified", sa.text("'unknown'")),
    ("plugins", "sandbox_status", "not_executed", sa.text("'pending'")),
    ("autonomy_overrides", "created_at", sa.func.now(), None),
    ("autonomy_overrides", "updated_at", sa.func.now(), None),
)
ALERT_SCOPE_COLUMNS = ("org_id", "workspace_id", "network_id")
_UUID_HEX = "'^[0-9a-f]{32}$'"


# ----------------------------------------------------------------------------- helpers

def _index_elements(columns: Sequence[str]) -> list:
    return [column if column.isidentifier() else sa.text(column) for column in columns]


def _in_caller_transaction() -> bool:
    """True when the caller began the transaction; autocommit is impossible then."""
    context = op.get_context()
    return not context.as_sql and bool(getattr(context, "_in_external_transaction", False))


@contextlib.contextmanager
def _outside_transaction() -> Iterator[bool]:
    """Autocommit block for CONCURRENTLY/batched work; yields whether it is concurrent."""
    if _in_caller_transaction():
        yield False
        return
    with op.get_context().autocommit_block():
        # Concurrent builds wait for older transactions; those waits count against
        # lock_timeout although they never block writers. Suspend it for this block.
        op.execute("SELECT set_config('nanfo.migration_lock_timeout', current_setting('lock_timeout'), false)")
        op.execute("SET lock_timeout = 0")
        try:
            yield True
        finally:
            op.execute("SELECT set_config('lock_timeout', current_setting('nanfo.migration_lock_timeout'), false)")


def _drop_invalid_leftover(name: str, table: str) -> None:
    """A failed CONCURRENTLY build leaves an INVALID index that IF NOT EXISTS would keep."""
    if op.get_context().as_sql:
        op.drop_index(name, table_name=table, postgresql_concurrently=True, if_exists=True)
        return
    invalid = op.get_bind().scalar(
        sa.text("SELECT NOT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"), {"name": name})
    if invalid:
        log.warning("Rebuilding invalid index %s left by an interrupted concurrent build", name)
        op.drop_index(name, table_name=table, postgresql_concurrently=True, if_exists=True)


def _create_large_index(name: str, table: str, columns: Sequence[str], method: str | None,
                        concurrent: bool) -> None:
    if concurrent:
        _drop_invalid_leftover(name, table)
    options = {"postgresql_using": method} if method else {}
    op.create_index(name, table, _index_elements(columns), postgresql_concurrently=concurrent,
                    if_not_exists=True, **options)


def _validate(table: str, constraint: str, violations: str) -> None:
    """VALIDATE a NOT VALID constraint only when no existing row violates it."""
    notice = (f"{table}.{constraint} left NOT VALID: existing rows violate it; "
              "new and updated rows are still checked")
    if op.get_context().as_sql:
        op.execute(f"DO $$ BEGIN IF EXISTS ({violations}) THEN RAISE NOTICE '{notice}'; "
                   f"ELSE ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}; END IF; END $$")
        return
    if op.get_bind().scalar(sa.text(f"SELECT EXISTS ({violations})")):
        log.warning(notice)
        return
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}")


def _execute_counted(sql: str, message: str) -> None:
    if op.get_context().as_sql:
        op.execute(sql)
        return
    count = op.get_bind().execute(sa.text(sql)).rowcount
    if count:
        log.warning(message, count)


# ----------------------------------------------------------------------------- data fixes

DEDUPE_INTENT_KEYS = """
    UPDATE intents AS target
    SET idempotency_key = target.idempotency_key || '~dup~' || target.intent_id::text
    FROM (
        SELECT intent_id, row_number() OVER (
            PARTITION BY workspace_id, idempotency_key
            ORDER BY created_at, requested_at, intent_id) AS position
        FROM intents
        WHERE idempotency_key IS NOT NULL
    ) AS ranked
    WHERE target.intent_id = ranked.intent_id AND ranked.position > 1
"""
DEDUPE_CAMPUS_BUILDINGS = """
    UPDATE campus_buildings AS target
    SET deleted_at = now(), updated_at = now()
    FROM (
        SELECT campus_building_id, row_number() OVER (
            PARTITION BY network_id, building_id
            ORDER BY updated_at DESC, created_at DESC, campus_building_id DESC) AS position
        FROM campus_buildings
        WHERE deleted_at IS NULL
    ) AS ranked
    WHERE target.campus_building_id = ranked.campus_building_id AND ranked.position > 1
"""
# Restores renamed keys (exact suffix marker) unless an execution bound the renamed key.
RESTORE_INTENT_KEYS = """
    UPDATE intents AS target
    SET idempotency_key = left(target.idempotency_key,
                               length(target.idempotency_key) - length('~dup~' || target.intent_id::text))
    WHERE target.idempotency_key IS NOT NULL
      AND right(target.idempotency_key, length('~dup~' || target.intent_id::text))
          = '~dup~' || target.intent_id::text
      AND NOT EXISTS (
          SELECT 1 FROM intent_executions AS execution
          WHERE execution.workspace_id = target.workspace_id
            AND execution.request_key = target.idempotency_key)
"""


def _scope_raw(key: str) -> str:
    """The recorded JSON value for ``key``: top-level unless absent/null, else nested scope."""
    return (f"COALESCE(NULLIF(payload -> '{key}', 'null'::jsonb), "
            f"CASE WHEN jsonb_typeof(payload -> 'scope') = 'object' "
            f"THEN NULLIF(payload -> 'scope' -> '{key}', 'null'::jsonb) END)")


def _scope_hex(raw: str) -> str:
    """Hex digits of a JSON string UUID (Python uuid.UUID normalisation), '!' for non-strings."""
    text = raw + " #>> '{}'"
    return (f"CASE WHEN {raw} IS NULL THEN NULL WHEN jsonb_typeof({raw}) = 'string' THEN "
            f"lower(replace(btrim(replace(replace({text}, 'urn:', ''), 'uuid:', ''), '{{}}'), '-', '')) "
            f"ELSE '!' END")


def alert_scope_batch_update(after: str, upper: str) -> str:
    """Backfill statement for alert ids in ``(after, upper]`` whose columns are all NULL."""
    raws = ", ".join(f"{_scope_raw(key)} AS {key}_raw" for key in ALERT_SCOPE_COLUMNS)
    hexes = ", ".join(f"{_scope_hex(key + '_raw')} AS {key}_hex" for key in ALERT_SCOPE_COLUMNS)
    assignments = ", ".join(
        f"{key} = CASE WHEN scoped.{key}_hex ~ {_UUID_HEX} THEN CAST(scoped.{key}_hex AS uuid) END"
        for key in ALERT_SCOPE_COLUMNS)
    valid = " AND ".join(f"(scoped.{key}_hex IS NULL OR scoped.{key}_hex ~ {_UUID_HEX})"
                         for key in ALERT_SCOPE_COLUMNS)
    present = ", ".join(f"scoped.{key}_hex" for key in ALERT_SCOPE_COLUMNS)
    # The target-row NULL test is re-evaluated on concurrently updated rows, so values an
    # application writer stored meanwhile are never overwritten.
    return (f"WITH candidate AS (SELECT alert_id, {raws} FROM alerts "
            f"WHERE ({after} IS NULL OR alert_id > {after}) AND alert_id <= {upper} "
            f"AND org_id IS NULL AND workspace_id IS NULL AND network_id IS NULL "
            f"AND jsonb_typeof(payload) = 'object'), "
            f"scoped AS (SELECT alert_id, {hexes} FROM candidate) "
            f"UPDATE alerts SET {assignments} FROM scoped "
            f"WHERE alerts.alert_id = scoped.alert_id "
            f"AND alerts.org_id IS NULL AND alerts.workspace_id IS NULL AND alerts.network_id IS NULL "
            f"AND {valid} AND num_nonnulls({present}) > 0")


def alert_scope_batch_upper(after: str, size: str, *, into: str = "") -> str:
    """Last alert id of the next keyset batch of rows whose tenancy columns are all NULL."""
    target = f" INTO {into}" if into else ""
    return (f"SELECT batch.alert_id{target} FROM (SELECT alert_id FROM alerts "
            f"WHERE ({after} IS NULL OR alert_id > {after}) "
            f"AND org_id IS NULL AND workspace_id IS NULL AND network_id IS NULL "
            f"ORDER BY alert_id LIMIT {size}) AS batch ORDER BY batch.alert_id DESC LIMIT 1")


def batch_size() -> int:
    raw = os.environ.get(BATCH_SIZE_SETTING, str(DEFAULT_BATCH_SIZE)).strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 100_000:
        raise RuntimeError(f"{BATCH_SIZE_SETTING} must be an integer between 1 and 100000")
    return int(raw)


def _backfill_alert_scope() -> None:
    size = batch_size()
    if op.get_context().as_sql:
        upper = alert_scope_batch_upper("last_id", str(size), into="upper_id")
        update = alert_scope_batch_update("last_id", "upper_id")
        op.execute("DO $$ DECLARE last_id uuid; upper_id uuid; BEGIN LOOP "
                   f"{upper}; EXIT WHEN upper_id IS NULL; {update}; last_id := upper_id; END LOOP; END $$")
        return
    bind = op.get_bind()
    upper_sql = sa.text(alert_scope_batch_upper("CAST(:after AS uuid)", ":size"))
    update_sql = sa.text(alert_scope_batch_update("CAST(:after AS uuid)", "CAST(:upper AS uuid)"))
    after, updated = None, 0
    while (upper := bind.scalar(upper_sql, {"after": after, "size": size})) is not None:
        updated += bind.execute(update_sql, {"after": after, "upper": str(upper)}).rowcount or 0
        after = str(upper)
    log.info("Backfilled alert tenancy columns for %d rows", updated)


def _refuse_delta_history() -> None:
    """Self-enforcing guard (also in offline SQL): delta history is immutable evidence."""
    op.execute(f"""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM {SPATIAL_HISTORY} WHERE storage_kind <> 'full' OR scene IS NULL
                   OR delta IS NOT NULL OR base_revision IS NOT NULL) THEN
            RAISE EXCEPTION 'Downgrade below 0030 refused: delta-encoded spatial scene history exists and the 0029 schema cannot store it';
        END IF;
    END $$""")


# ----------------------------------------------------------------------------- upgrade

def upgrade() -> None:
    # Part A: one transaction; each statement is idempotent (re-runnable after part B fails).
    op.execute("LOCK TABLE intents IN SHARE ROW EXCLUSIVE MODE")
    _execute_counted(DEDUPE_INTENT_KEYS, "Renamed %d duplicate intent idempotency keys to <key>~dup~<intent_id>")
    op.create_index("uq_intents_workspace_idempotency", "intents", ["workspace_id", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"), if_not_exists=True)
    op.execute("LOCK TABLE campus_buildings IN SHARE ROW EXCLUSIVE MODE")
    _execute_counted(DEDUPE_CAMPUS_BUILDINGS, "Soft-deleted %d older duplicate active campus buildings")
    op.create_index("uq_campus_buildings_network_building_active", "campus_buildings", ["network_id", "building_id"],
                    unique=True, postgresql_where=sa.text("deleted_at IS NULL"), if_not_exists=True)

    for column in ALERT_SCOPE_COLUMNS:
        op.add_column("alerts", sa.Column(column, pg.UUID(as_uuid=True), nullable=True), if_not_exists=True)
    for table in ("reports", "simulations"):
        op.add_column(table, sa.Column("claim_attempts", sa.Integer(), nullable=False, server_default="0"),
                      if_not_exists=True)
    for table in ("simulation_outbox", "report_outbox"):
        op.add_column(table, sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                                       server_default=sa.func.now()), if_not_exists=True)

    op.add_column(SPATIAL_HISTORY, sa.Column("delta", pg.JSONB(), nullable=True), if_not_exists=True)
    op.add_column(SPATIAL_HISTORY, sa.Column("base_revision", sa.BigInteger(), nullable=True), if_not_exists=True)
    op.add_column(SPATIAL_HISTORY, sa.Column("storage_kind", sa.Text(), nullable=False, server_default="full"),
                  if_not_exists=True)
    op.alter_column(SPATIAL_HISTORY, "scene", existing_type=pg.JSONB(), nullable=True)
    for name, condition in SPATIAL_CHECKS:
        op.drop_constraint(name, SPATIAL_HISTORY, type_="check", if_exists=True)
        op.create_check_constraint(name, SPATIAL_HISTORY, condition)

    for table, column, default, _previous in SERVER_DEFAULTS:
        op.alter_column(table, column, server_default=default)

    for name, table, columns, where in INDEXES:
        options = {"postgresql_where": sa.text(where)} if where else {}
        op.create_index(name, table, list(columns), if_not_exists=True, **options)
    for name, table, _column, large in REDUNDANT_INDEXES:
        if not large:
            op.drop_index(name, table_name=table, if_exists=True)

    for name, table, column, referred, referred_column, ondelete in FOREIGN_KEYS:
        op.drop_constraint(name, table, type_="foreignkey", if_exists=True)
        op.create_foreign_key(name, table, referred, [column], [referred_column], ondelete=ondelete,
                              postgresql_not_valid=True)
    for name, table, condition in STATUS_CHECKS:
        op.drop_constraint(name, table, type_="check", if_exists=True)
        op.create_check_constraint(name, table, condition, postgresql_not_valid=True)

    # Part B: large-table work outside the transaction whenever possible.
    with _outside_transaction() as concurrent:
        _backfill_alert_scope()
        for name, table, columns, method in CONCURRENT_INDEXES:
            _create_large_index(name, table, columns, method, concurrent)
        for name, table, _column, large in REDUNDANT_INDEXES:
            if large:  # only after its covering index exists
                op.drop_index(name, table_name=table, postgresql_concurrently=concurrent, if_exists=True)
        for name, table, column, referred, referred_column, _ondelete in FOREIGN_KEYS:
            _validate(table, name, f"SELECT 1 FROM {table} AS child WHERE child.{column} IS NOT NULL "
                                   f"AND NOT EXISTS (SELECT 1 FROM {referred} AS parent "
                                   f"WHERE parent.{referred_column} = child.{column})")
        for name, table, condition in STATUS_CHECKS:
            _validate(table, name, f"SELECT 1 FROM {table} WHERE NOT ({condition})")


# ----------------------------------------------------------------------------- downgrade

def downgrade() -> None:
    _refuse_delta_history()  # before anything is committed by the autocommit block
    with _outside_transaction() as concurrent:
        for name, table, column, large in REDUNDANT_INDEXES:
            if large:  # recreate before the covering index disappears
                _create_large_index(name, table, (column,), None, concurrent)
        for name, table, _columns, _method in reversed(CONCURRENT_INDEXES):
            op.drop_index(name, table_name=table, postgresql_concurrently=concurrent, if_exists=True)

    _refuse_delta_history()
    for name, table, _condition in reversed(STATUS_CHECKS):
        op.drop_constraint(name, table, type_="check", if_exists=True)
    for name, table, _column, _referred, _referred_column, _ondelete in reversed(FOREIGN_KEYS):
        op.drop_constraint(name, table, type_="foreignkey", if_exists=True)
    for name, table, column, large in reversed(REDUNDANT_INDEXES):
        if not large:
            op.create_index(name, table, [column], if_not_exists=True)
    for name, table, _columns, _where in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
    for table, column, _default, previous in reversed(SERVER_DEFAULTS):
        op.alter_column(table, column, server_default=previous)

    for name, _condition in reversed(SPATIAL_CHECKS):
        op.drop_constraint(name, SPATIAL_HISTORY, type_="check", if_exists=True)
    op.alter_column(SPATIAL_HISTORY, "scene", existing_type=pg.JSONB(), nullable=False)
    for column in ("storage_kind", "base_revision", "delta"):
        op.drop_column(SPATIAL_HISTORY, column)

    for table in ("report_outbox", "simulation_outbox"):
        op.drop_column(table, "created_at")
    for table in ("simulations", "reports"):
        op.drop_column(table, "claim_attempts")
    for column in reversed(ALERT_SCOPE_COLUMNS):
        op.drop_column("alerts", column)

    op.drop_index("uq_campus_buildings_network_building_active", table_name="campus_buildings", if_exists=True)
    op.drop_index("uq_intents_workspace_idempotency", table_name="intents", if_exists=True)
    op.execute(RESTORE_INTENT_KEYS)
