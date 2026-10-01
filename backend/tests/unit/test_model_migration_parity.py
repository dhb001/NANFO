"""Offline model <-> migration parity (ADR-028 BE-DB); no database is required.

Every Alembic revision is replayed against a recording stub ``op`` that keeps an
in-memory schema: tables, columns (type, nullability, server default), primary keys,
indexes (columns/expressions incl. DESC, uniqueness, partial WHERE, method), unique,
CHECK and foreign-key constraints. The replayed schema must equal ``Base.metadata``
exactly. That covers what ``alembic check`` compares (compare_type,
compare_server_default, indexes, uniques, FKs incl. actions, named CHECKs) plus what
it cannot see (partial predicates, index methods, CHECK text).

Upgrades replay in offline mode: ``op.get_bind()`` fails there, so every upgrade must
also render with ``alembic upgrade --sql``. Downgrades replay against an empty fake
connection so their evidence guards pass and their DDL is checked for consistency.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import importlib
import importlib.util
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import TextClause

from alembic.config import Config
from alembic.ddl.postgresql import PostgresqlImpl
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2]
VERSIONS = BACKEND / "alembic" / "versions"
PG = postgresql.dialect()
_IMPL = PostgresqlImpl(PG, None, False, False, None, {})
_UNCHANGED = False  # alembic's "no change" sentinel for alter_column(server_default=...)

# Raw SQL may move data, create triggers/functions or VALIDATE constraints. Any change
# of schema shape must use an op so the replay (and autogenerate) can see it.
_RAW_DDL = re.compile(
    r"^\s*(CREATE\s+(UNIQUE\s+)?INDEX|DROP\s+INDEX|CREATE\s+TABLE|DROP\s+TABLE|"
    r"ALTER\s+TABLE\s+\S+\s+(ADD|DROP|ALTER|RENAME))",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- schema model

@dataclass(frozen=True)
class Column:
    type: str
    nullable: bool
    default: str | None


@dataclass(frozen=True)
class Index:
    unique: bool
    expressions: tuple[str, ...]
    where: str | None
    using: str


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]
    ondelete: str | None
    onupdate: str | None
    deferrable: bool
    initially: str | None


@dataclass
class Table:
    columns: dict[str, Column] = field(default_factory=dict)
    primary_key: tuple[str, ...] = ()
    indexes: dict[str, Index] = field(default_factory=dict)
    uniques: set[tuple[str | None, tuple[str, ...]]] = field(default_factory=set)
    checks: dict[str, str] = field(default_factory=dict)
    foreign_keys: set[tuple[str | None, ForeignKey]] = field(default_factory=set)


def _text(element) -> str:
    if isinstance(element, str):
        return element
    if isinstance(element, TextClause):
        return element.text
    return _IMPL._compile_element(element)


def _outer_pair(sql: str) -> bool:
    depth = 0
    for position, char in enumerate(sql):
        depth += char == "("
        depth -= char == ")"
        if depth == 0:
            return position == len(sql) - 1
    return False


def _squash(sql: str) -> str:
    sql = " ".join(sql.split())
    while sql.startswith("(") and sql.endswith(")") and _outer_pair(sql):
        sql = sql[1:-1].strip()
    return sql


def _type(column: sa.Column) -> str:
    rendered = column.type.compile(dialect=PG).upper()
    return {"DOUBLE PRECISION": "FLOAT"}.get(rendered, rendered)


def _default_sql(default) -> str | None:
    if default is None:
        return None
    arg = default.arg if isinstance(default, sa.DefaultClause) else default
    sql = "'" + arg.replace("'", "''") + "'" if isinstance(arg, str) else _text(arg)
    sql = re.sub(r"::[a-z ]+$", "", " ".join(sql.split()), flags=re.IGNORECASE)
    literal = re.fullmatch(r"'(-?\d+|true|false)'", sql, flags=re.IGNORECASE)
    if literal:
        sql = literal.group(1)
    return sql.lower() if sql.lower() in {"true", "false"} else sql


def _default(column: sa.Column) -> str | None:
    return "IDENTITY" if column.identity is not None else _default_sql(column.server_default)


def _name(constraint) -> str | None:
    return constraint.name if isinstance(constraint.name, str) and constraint.name else None


def _action(value: str | None) -> str | None:
    return None if value is None or value.upper() == "NO ACTION" else value.upper()


def _foreign_key(constraint: sa.ForeignKeyConstraint) -> tuple[str | None, ForeignKey]:
    targets = [element.target_fullname.rsplit(".", 1) for element in constraint.elements]
    (referred,) = {table for table, _ in targets}
    return _name(constraint), ForeignKey(
        columns=tuple(constraint.column_keys), referred_table=referred,
        referred_columns=tuple(column for _, column in targets),
        ondelete=_action(constraint.ondelete), onupdate=_action(constraint.onupdate),
        deferrable=bool(constraint.deferrable),
        initially=constraint.initially.upper() if constraint.initially else None,
    )


def _index(index: sa.Index) -> Index:
    options = index.dialect_options["postgresql"]
    where = options.get("where")
    return Index(
        unique=bool(index.unique),
        expressions=tuple(_IMPL._cleanup_index_expr(index, _text(expression)) for expression in index.expressions),
        where=None if where is None else _squash(_text(where)),
        using=(options.get("using") or "btree").lower(),
    )


def _table(table: sa.Table) -> Table:
    state = Table(
        columns={column.name: Column(_type(column), bool(column.nullable), _default(column))
                 for column in table.columns},
        primary_key=tuple(column.name for column in table.primary_key.columns),
        indexes={index.name: _index(index) for index in table.indexes},
    )
    for constraint in table.constraints:
        if isinstance(constraint, sa.UniqueConstraint):
            state.uniques.add((_name(constraint), tuple(column.name for column in constraint.columns)))
        elif isinstance(constraint, sa.CheckConstraint):
            assert _name(constraint), f"{table.name}: CHECK constraints must be named"
            state.checks[_name(constraint)] = _squash(_text(constraint.sqltext))
        elif isinstance(constraint, sa.ForeignKeyConstraint):
            state.foreign_keys.add(_foreign_key(constraint))
    return state


def _mentions(sql: str | tuple[str, ...], column: str) -> bool:
    text = " ".join(sql) if isinstance(sql, tuple) else sql or ""
    return re.search(rf"\b{re.escape(column)}\b", text) is not None


# --------------------------------------------------------------------------- recording op

class _Result:
    rowcount = 0

    def scalar(self):
        return None

    def all(self):
        return []

    def __iter__(self):
        return iter(())


class _Database:
    """Online-mode connection to a database whose tables are all empty."""

    def __init__(self, recorder: RecordingOp, evidence: bool):
        self.recorder, self.evidence = recorder, evidence

    def scalar(self, statement, *args, **kwargs):
        self.recorder.queries.append(_text(statement))
        return True if self.evidence else None

    def execute(self, statement, *args, **kwargs):
        self.recorder.queries.append(_text(statement))
        return _Result()


class _Context:
    _in_external_transaction = False

    def __init__(self, as_sql: bool):
        self.as_sql = as_sql
        self.autocommit_blocks = 0

    @contextlib.contextmanager
    def autocommit_block(self):
        self.autocommit_blocks += 1
        yield


class RecordingOp:
    """The subset of ``alembic.op`` used by the revisions, applied to an in-memory schema."""

    def __init__(self, schema: dict[str, Table], *, online: bool, evidence: bool = False):
        self.schema = schema
        self.online, self.evidence = online, evidence
        self.context = _Context(as_sql=not online)
        self.statements: list[str] = []
        self.queries: list[str] = []

    def __getattr__(self, name):
        raise AttributeError(f"parity recorder does not implement op.{name}; extend it before using it")

    def get_context(self):
        return self.context

    def get_bind(self):
        if not self.online:
            raise AssertionError("op.get_bind() in offline mode: `alembic upgrade --sql` cannot render this")
        return _Database(self, self.evidence)

    def f(self, name):
        return name

    def execute(self, sql, *args, **kwargs):
        text = _text(sql)
        assert not _RAW_DDL.match(text), f"schema DDL must use an alembic op: {text[:120]}"
        self.statements.append(text)

    def _get(self, name: str) -> Table:
        assert name in self.schema, f"table {name} does not exist"
        return self.schema[name]

    def create_table(self, name, *items, if_not_exists=None, **kw):
        assert name not in self.schema, f"table {name} already exists"
        self.schema[name] = _table(sa.Table(name, sa.MetaData(), *items))

    def drop_table(self, name, if_exists=None, **kw):
        self._get(name)
        dependants = [other for other, table in self.schema.items() if other != name
                      and any(fk.referred_table == name for _, fk in table.foreign_keys)]
        assert not dependants, f"drop_table({name}) while referenced by {dependants}"
        del self.schema[name]

    def add_column(self, table_name, column, if_not_exists=None, **kw):
        table = self._get(table_name)
        if if_not_exists and column.name in table.columns:
            return
        assert column.name not in table.columns, f"{table_name}.{column.name} already exists"
        added = _table(sa.Table(table_name, sa.MetaData(), column))
        table.columns.update(added.columns)
        table.indexes.update(added.indexes)
        table.uniques |= added.uniques
        table.checks.update(added.checks)
        table.foreign_keys |= added.foreign_keys

    def drop_column(self, table_name, column_name, **kw):
        table = self._get(table_name)
        assert column_name in table.columns, f"{table_name}.{column_name} does not exist"
        del table.columns[column_name]
        # PostgreSQL drops every index/constraint depending on the column.
        table.indexes = {name: index for name, index in table.indexes.items()
                         if not (_mentions(index.expressions, column_name) or _mentions(index.where, column_name))}
        table.uniques = {unique for unique in table.uniques if column_name not in unique[1]}
        table.checks = {name: sql for name, sql in table.checks.items() if not _mentions(sql, column_name)}
        table.foreign_keys = {fk for fk in table.foreign_keys if column_name not in fk[1].columns}

    def alter_column(self, table_name, column_name, *, nullable=None, server_default=_UNCHANGED,
                     type_=None, new_column_name=None, **kw):
        assert new_column_name is None, "column renames are not modelled"
        table = self._get(table_name)
        column = table.columns[column_name]
        table.columns[column_name] = Column(
            type=column.type if type_ is None else _type(sa.Column("probe", type_)),
            nullable=column.nullable if nullable is None else bool(nullable),
            default=column.default if server_default is _UNCHANGED else _default_sql(server_default),
        )

    def create_index(self, index_name, table_name, columns, *, unique=False, if_not_exists=None, **kw):
        table = self._get(table_name)
        if if_not_exists and index_name in table.indexes:
            return
        assert index_name not in table.indexes, f"index {index_name} already exists"
        names = [column for column in columns if isinstance(column, str)]
        missing = [name for name in names if name not in table.columns]
        assert not missing, f"index {index_name} names unknown columns {missing}"
        probe = sa.Table(table_name, sa.MetaData(), *[sa.Column(name, sa.Integer) for name in dict.fromkeys(names)])
        kw.pop("postgresql_concurrently", None)
        index = sa.Index(index_name, *[probe.c[column] if isinstance(column, str) else column for column in columns],
                         unique=unique, _table=probe, **kw)
        table.indexes[index_name] = _index(index)

    def drop_index(self, index_name, table_name=None, *, if_exists=None, **kw):
        owners = [table_name] if table_name else [name for name, table in self.schema.items()
                                                  if index_name in table.indexes]
        if if_exists and (not owners or index_name not in self._get(owners[0]).indexes):
            return
        assert len(owners) == 1 and index_name in self._get(owners[0]).indexes, f"index {index_name} does not exist"
        del self.schema[owners[0]].indexes[index_name]

    def create_unique_constraint(self, name, table_name, columns, **kw):
        table = self._get(table_name)
        assert set(columns) <= set(table.columns)
        table.uniques.add((name, tuple(columns)))

    def create_check_constraint(self, name, table_name, condition, **kw):
        table = self._get(table_name)
        assert name not in table.checks, f"check {name} already exists"
        table.checks[name] = _squash(_text(condition))

    def create_foreign_key(self, name, source_table, referent_table, local_cols, remote_cols, *,
                           onupdate=None, ondelete=None, deferrable=None, initially=None, **kw):
        table = self._get(source_table)
        referent = self._get(referent_table)
        assert set(local_cols) <= set(table.columns) and set(remote_cols) <= set(referent.columns)
        table.foreign_keys.add((name, ForeignKey(
            tuple(local_cols), referent_table, tuple(remote_cols), _action(ondelete), _action(onupdate),
            bool(deferrable), initially.upper() if initially else None)))

    def drop_constraint(self, name, table_name, type_=None, *, if_exists=None, **kw):
        table = self._get(table_name)
        before = (len(table.uniques), len(table.checks), len(table.foreign_keys))
        table.uniques = {unique for unique in table.uniques if unique[0] != name}
        table.checks.pop(name, None)
        table.foreign_keys = {fk for fk in table.foreign_keys if fk[0] != name}
        removed = before != (len(table.uniques), len(table.checks), len(table.foreign_keys))
        assert removed or if_exists, f"constraint {name} does not exist on {table_name}"


# --------------------------------------------------------------------------- replay helpers

def _scripts() -> ScriptDirectory:
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(config)


def _load(path: str | Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrations() -> list[ModuleType]:
    """Freshly loaded revision modules, base first (never Alembic's cached objects)."""
    scripts = list(reversed(list(_scripts().walk_revisions("base", "heads"))))
    return [_load(script.path, f"parity_migration_{script.revision}") for script in scripts]


def upgrade(modules: list[ModuleType], schema: dict[str, Table] | None = None) -> dict[str, Table]:
    schema = {} if schema is None else schema
    for module in modules:
        module.op = RecordingOp(schema, online=False)
        module.upgrade()
    return schema


def downgrade(modules: list[ModuleType], schema: dict[str, Table]) -> dict[str, Table]:
    for module in reversed(modules):
        module.op = RecordingOp(schema, online=True)
        module.downgrade()
    return schema


def model_modules() -> list[str]:
    names = []
    for path in sorted((BACKEND / "app" / "modules").rglob("*.py")):
        if (path.name == "models.py" or path.name.endswith("_models.py")) and "__tablename__" in path.read_text():
            names.append(".".join(path.relative_to(BACKEND).with_suffix("").parts))
    return names


def model_schema() -> dict[str, Table]:
    from app.db.postgres import Base

    for name in model_modules():
        importlib.import_module(name)
    tables = {mapper.local_table for mapper in Base.registry.mappers
              if mapper.class_.__module__.startswith("app.modules.")}
    return {table.name: _table(table) for table in tables}


def diff(migrated: dict[str, Table], models: dict[str, Table]) -> list[str]:
    problems: list[str] = []

    def compare(where: str, kind: str, left: dict, right: dict) -> None:
        for key in sorted(left.keys() | right.keys(), key=str):
            if left.get(key) != right.get(key):
                problems.append(f"{where} {kind} {key}: migrations={left.get(key)} models={right.get(key)}")

    for name in sorted(migrated.keys() | models.keys()):
        if name not in models or name not in migrated:
            problems.append(f"{name}: table only in {'migrations' if name in migrated else 'models'}")
            continue
        left, right = migrated[name], models[name]
        compare(name, "column", left.columns, right.columns)
        if left.primary_key != right.primary_key:
            problems.append(f"{name} primary key: migrations={left.primary_key} models={right.primary_key}")
        compare(name, "index", left.indexes, right.indexes)
        compare(name, "unique", {u: True for u in left.uniques}, {u: True for u in right.uniques})
        compare(name, "check", left.checks, right.checks)
        compare(name, "foreign key", {fk: True for fk in left.foreign_keys}, {fk: True for fk in right.foreign_keys})
    return problems


# --------------------------------------------------------------------------- tests

def test_models_mirror_every_migrated_table_column_index_and_constraint():
    problems = diff(upgrade(migrations()), model_schema())
    assert not problems, "model/migration drift:\n" + "\n".join(problems)


def _by_revision(modules: list[ModuleType]) -> dict[str, ModuleType]:
    return {module.revision: module for module in modules}


def test_revision_chain_is_linear_with_single_head_0030():
    scripts = _scripts()
    assert scripts.get_heads() == ["0030"]
    assert scripts.get_revision("0030").down_revision == "0029"
    assert [module.revision for module in migrations()] == [f"{number:04d}" for number in range(1, 31)]


def test_0030_downgrade_restores_the_exact_0029_schema():
    modules = migrations()
    before = upgrade(modules[:-1])
    after = downgrade(modules[-1:], upgrade(modules))
    assert not diff(before, after), "\n".join(diff(before, after))


def test_every_downgrade_replays_back_to_an_empty_schema():
    modules = migrations()
    assert downgrade(modules, upgrade(modules)) == {}


def test_0030_upgrade_is_rerunnable_after_a_partial_failure():
    """Part B runs after a commit; recovering means re-running the whole revision."""
    modules = migrations()
    schema = upgrade(modules)
    upgrade(modules[-1:], schema)
    assert not diff(schema, model_schema())


def test_redundant_single_column_indexes_are_dropped():
    """No non-unique, non-partial single-column btree index may be the leading column
    of another non-partial btree index, unique constraint or primary key."""
    redundant = []
    for name, table in upgrade(migrations()).items():
        prefixes = {index_name: index.expressions for index_name, index in table.indexes.items()
                    if index.where is None and index.using == "btree"}
        prefixes |= {f"unique{columns}": columns for _, columns in table.uniques}
        prefixes["primary key"] = table.primary_key
        for index_name, index in table.indexes.items():
            if index.unique or index.where is not None or index.using != "btree" or len(index.expressions) != 1:
                continue
            covering = [other for other, columns in prefixes.items()
                        if other != index_name and columns and columns[0] == index.expressions[0]]
            if covering:
                redundant.append(f"{name}.{index_name} is covered by {covering}")
    assert not redundant, "\n".join(redundant)


def test_every_foreign_key_has_a_covering_index():
    uncovered = []
    for name, table in upgrade(migrations()).items():
        prefixes = [index.expressions for index in table.indexes.values()
                    if index.where is None and index.using == "btree"]
        prefixes += [columns for _, columns in table.uniques] + [table.primary_key]
        for fk_name, fk in table.foreign_keys:
            if not any(tuple(prefix[:len(fk.columns)]) == fk.columns for prefix in prefixes):
                uncovered.append(f"{name}{fk.columns} -> {fk.referred_table} ({fk_name})")
    assert not uncovered, "\n".join(uncovered)


def test_foreign_keys_never_cross_module_ownership():
    owners = {}
    for module_name in model_modules():
        module = importlib.import_module(module_name)
        for value in vars(module).values():
            table = getattr(value, "__table__", None)
            if isinstance(table, sa.Table) and value.__module__ == module_name:
                owners[table.name] = module_name.split(".")[2]
    crossing = [f"{name}.{fk.columns} -> {fk.referred_table}"
                for name, table in upgrade(migrations()).items() for _, fk in table.foreign_keys
                if owners[name] != owners[fk.referred_table]]
    assert not crossing, crossing


def test_mappers_with_onupdate_columns_fetch_server_values_eagerly():
    from app.db.postgres import Base

    model_schema()
    lacking = [mapper.class_.__name__ for mapper in Base.registry.mappers
               if mapper.class_.__module__.startswith("app.modules.")
               and any(column.onupdate is not None for column in mapper.local_table.columns)
               and mapper.eager_defaults is not True]
    assert not lacking, lacking


def test_alembic_env_imports_every_model_module():
    tree = ast.parse((BACKEND / "alembic" / "env.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported |= {node.module} | {f"{node.module}.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
    missing = [name for name in model_modules() if name not in imported]
    assert not missing, f"alembic/env.py must import {missing}"


def test_migrations_never_import_application_code():
    offenders = []
    for path in sorted(VERSIONS.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            offenders += [f"{path.name}: {name}" for name in names if name == "app" or name.startswith("app.")]
    assert not offenders, offenders


# AST digests of every historical top-level function except downgrade() (upgrades and
# their helpers). ADR-028 only hardened downgrades; upgrade behaviour must stay frozen.
FROZEN_UPGRADES = {
    "0001": "3200aab5cdd8a84a", "0002": "84751ed0b91354ff", "0003": "81d0235c93bbc4eb",
    "0004": "1c4904fbecab636f", "0005": "597de4ad5a746df6", "0006": "5ecefb109e4b7dfa",
    "0007": "a65c46d1ff99a896", "0008": "eedb4d8afc592013", "0009": "b791a6f6f4ff1492",
    "0010": "927909c9e11fc7bc", "0011": "93e249b0391eae9f", "0012": "e0e79912e4abe729",
    "0013": "343f9a77628e5ce5", "0014": "fa6ba99dd514cfb0", "0015": "3e6b451c475d3af1",
    "0016": "6461c6caeec897a2", "0017": "689c9298be327cc4", "0018": "9bb088bfc9304696",
    "0019": "41f5a9b3d39f37bf", "0020": "2865d11635fe7749", "0021": "b309bf28da066b4b",
    "0022": "0f56e11a39363e72", "0023": "5e6ddad911d90076", "0024": "be6abf5dcc49a092",
    "0025": "6d6ff007201141fd", "0026": "6e84a58996859351", "0027": "300fb0eaf42ae03b",
    "0028": "b1fe0153287e1dbc", "0029": "e89d150405adc7b9",
}


def test_historical_upgrades_are_unchanged():
    import hashlib

    current = {}
    for path in sorted(VERSIONS.glob("00[0-2][0-9]_*.py")):
        tree = ast.parse(path.read_text())
        body = "\n".join(ast.dump(node) for node in tree.body
                         if isinstance(node, ast.FunctionDef) and node.name != "downgrade")
        current[path.name[:4]] = hashlib.sha256(body.encode()).hexdigest()[:16]
    assert current == FROZEN_UPGRADES


def _render(module: ModuleType, direction: str) -> str:
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={
        "as_sql": True, "output_buffer": output, "transaction_per_migration": True})
    with Operations.context(context):
        getattr(module, direction)()
    return output.getvalue()


def _position(sql: str, needle: str) -> int:
    assert needle in sql, needle
    return sql.index(needle)


def test_0030_offline_upgrade_sql_orders_dedupe_concurrency_and_validation():
    migration = _by_revision(migrations())["0030"]
    sql = _render(migration, "upgrade")
    # C3: lock, rename later duplicates, then the partial unique index.
    assert (_position(sql, "LOCK TABLE intents IN SHARE ROW EXCLUSIVE MODE")
            < _position(sql, "SET idempotency_key = target.idempotency_key || '~dup~' || target.intent_id::text")
            < _position(sql, "CREATE UNIQUE INDEX IF NOT EXISTS uq_intents_workspace_idempotency ON intents "
                             "(workspace_id, idempotency_key) WHERE idempotency_key IS NOT NULL"))
    assert "ORDER BY created_at, requested_at, intent_id" in sql
    assert (_position(sql, "SET deleted_at = now(), updated_at = now()")
            < _position(sql, "uq_campus_buildings_network_building_active ON campus_buildings "
                             "(network_id, building_id) WHERE deleted_at IS NULL"))
    # Large-table work only after the transaction committed, with lock_timeout restored.
    commit = _position(sql, "COMMIT;")
    assert commit < _position(sql, "SET lock_timeout = 0") < sql.index("CONCURRENTLY")
    assert sql.count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == 8
    assert "ON telemetry_records (device_id, observed_at DESC, record_id DESC)" in sql
    assert "ON telemetry_records USING brin (observed_at)" in sql
    assert "ix_alert_observations_observed_at_brin ON alert_observations USING brin (observed_at)" in sql
    assert 'ON audit_logs (org_id, "timestamp" DESC, log_id DESC)' in sql
    assert "ON alerts (workspace_id, updated_at DESC, alert_id DESC)" in sql
    assert (_position(sql, "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_telemetry_records_device_observed")
            < _position(sql, "DROP INDEX CONCURRENTLY IF EXISTS ix_telemetry_records_device_id;"))
    assert sql.index("CONCURRENTLY") > commit and sql.rindex("CONCURRENTLY") < sql.rindex("BEGIN;")
    assert (_position(sql, "current_setting('nanfo.migration_lock_timeout')") < sql.rindex("BEGIN;"))
    # 3 FKs + 11 status CHECKs are added NOT VALID and validated only when clean.
    assert sql.count(" NOT VALID;") == 14 and sql.count("VALIDATE CONSTRAINT") == 14
    assert "REFERENCES reports (report_id) ON DELETE CASCADE NOT VALID" in sql
    assert "RAISE NOTICE" in sql and "RAISE EXCEPTION" not in sql
    # Bounded keyset batches, in offline form a PL/pgSQL loop.
    assert "ORDER BY alert_id LIMIT 5000" in sql and "EXIT WHEN upper_id IS NULL" in sql


def test_0030_offline_downgrade_refuses_delta_history_before_any_change():
    sql = _render(_by_revision(migrations())["0030"], "downgrade")
    guard = "RAISE EXCEPTION 'Downgrade below 0030 refused"
    assert sql.index(guard) < sql.index("COMMIT;") < sql.index("CONCURRENTLY")
    assert sql.count(guard) == 2 and sql.rindex(guard) < sql.index("DROP COLUMN")
    assert "ALTER TABLE devices ALTER COLUMN status SET DEFAULT '''active''';" in sql  # exact 0029 state
    assert "length('~dup~' || target.intent_id::text)" in sql


def test_status_check_sets_cover_every_value_the_owners_write():
    from app.modules.autonomy.experimental import models as experimental
    from app.modules.intent import models as intent_models
    from app.modules.intent import queries as intent_queries
    from app.modules.intent.lab import LabResult
    from app.modules.organization.service import ORG_ROLES
    from app.modules.simulation import models as simulation_models
    from app.modules.simulation import queries as simulation_queries

    migration = _by_revision(migrations())["0030"]
    settled = intent_queries.SAFE_TERMINAL_STATUSES | intent_queries.RESTORATION_STATUSES
    assert set(migration.INTENT_SETTLED_STATUSES) == settled <= set(migration.INTENT_STATUSES)
    assert migration.INTENT_STATUSES == intent_models.INTENT_STATUSES
    assert migration.INTENT_QUEUE_STATUSES == intent_models.INTENT_QUEUE_STATUSES
    assert migration.EXECUTION_PHASES == intent_models.EXECUTION_PHASES
    assert set(LabResult.model_fields["status"].annotation.__args__) <= set(migration.EXECUTION_PHASES)
    assert set(migration.EXECUTION_TERMINAL_PHASES) <= set(migration.EXECUTION_PHASES)
    assert set(simulation_queries.TERMINAL_STATUSES) == set(migration.SIMULATION_TERMINAL_STATUSES)
    assert migration.SIMULATION_STATES == simulation_models.SIMULATION_STATES
    assert migration.ORG_ROLES == tuple(ORG_ROLES)
    assert migration.LAB_ACTION_PHASES == experimental.LAB_ACTION_PHASES
    assert migration.LAB_RUN_PHASES == experimental.LAB_RUN_PHASES


GUARDED_DOWNGRADES = {
    "0011": ("intent_executions", "intent_outbox"),
    "0018": ("alert_history",),
    "0022": ("network_spatial_scene_revisions",),
    "0027": ("autonomous_executions", "autonomous_observations", "autonomous_provider_state"),
    "0028": ("experimental_lab_runs", "experimental_lab_receipts"),
}


@pytest.mark.parametrize("revision", sorted(GUARDED_DOWNGRADES))
def test_downgrade_refuses_while_immutable_evidence_exists(revision):
    modules = migrations()
    schema = upgrade(modules[:int(revision)])
    before = copy.deepcopy(schema)
    target = _by_revision(modules)[revision]
    target.op = RecordingOp(schema, online=True, evidence=True)
    with pytest.raises(RuntimeError, match=f"Downgrade below {revision} refused"):
        target.downgrade()
    assert schema == before and not target.op.statements  # refused before any DDL
    assert all(table in " ".join(target.op.queries) for table in GUARDED_DOWNGRADES[revision])


@pytest.mark.parametrize("revision", sorted(GUARDED_DOWNGRADES) + ["0025", "0026"])
def test_data_checking_downgrades_refuse_offline_rendering(revision):
    target = _by_revision(migrations())[revision]
    target.op = RecordingOp(upgrade(migrations()[:int(revision)]), online=False)
    with pytest.raises(RuntimeError, match=f"Downgrade below {revision} must run online"):
        target.downgrade()


# ------------------------------------------------------------------ alembic environment

LOCK_TIMEOUT = "NANFO_MIGRATION_LOCK_TIMEOUT"


@pytest.fixture
def alembic_env(monkeypatch):
    import runpy
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from alembic import context
    from app.core import config as core_config
    from app.core.config import Settings

    settings = Settings(_env_file=None, POSTGRES_PASSWORD="parity-test")
    monkeypatch.setattr(core_config, "get_settings", lambda: settings)
    monkeypatch.setattr(context, "config", Config(), raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    for name in ("configure", "begin_transaction", "execute", "run_migrations"):
        monkeypatch.setattr(context, name, MagicMock())
    monkeypatch.delenv(LOCK_TIMEOUT, raising=False)
    namespace = runpy.run_path(str(BACKEND / "alembic" / "env.py"))
    return SimpleNamespace(namespace=namespace, context=context)


@pytest.mark.parametrize("value", ["5s", "500ms", "0", "2min", "1.5s", " 10s "])
def test_env_lock_timeout_accepts_postgres_durations(alembic_env, monkeypatch, value):
    monkeypatch.setenv(LOCK_TIMEOUT, value)
    assert alembic_env.namespace["lock_timeout"]() == value.strip()


@pytest.mark.parametrize("value", ["5s'; DROP TABLE users; --", "abc", "-1s", "5 seconds", "1e3"])
def test_env_lock_timeout_rejects_anything_else(alembic_env, monkeypatch, value):
    monkeypatch.setenv(LOCK_TIMEOUT, value)
    with pytest.raises(RuntimeError, match=LOCK_TIMEOUT):
        alembic_env.namespace["lock_timeout"]()


@pytest.mark.parametrize("in_transaction", [False, True])
def test_env_supplied_connection_gets_lock_timeout_and_per_revision_transactions(alembic_env, in_transaction):
    from unittest.mock import MagicMock

    connection = MagicMock()
    connection.in_transaction.return_value = in_transaction
    alembic_env.namespace["_run_on"](connection)
    statement, parameters = connection.execute.call_args.args
    assert "set_config('lock_timeout', :value, :local)" in str(statement)
    assert parameters == {"value": "5s", "local": in_transaction}
    # A caller-owned transaction keeps its scope; otherwise the session setting is committed.
    assert connection.commit.call_count == (0 if in_transaction else 1)
    options = alembic_env.context.configure.call_args.kwargs
    assert options["connection"] is connection
    assert options["transaction_per_migration"] is True
    assert options["compare_type"] is True and options["compare_server_default"] is True
