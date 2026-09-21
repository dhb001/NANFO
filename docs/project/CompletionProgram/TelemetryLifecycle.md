# ADR022 Telemetry lifecycle foundation

## Scope and wire contract

Telemetry owns migration `0024` after `0023`, durable evidence pins, prospective
reference coverage and bounded archival assessment. This is **not complete
retention**. No delete, partition conversion, public pin endpoint or scheduler is
introduced. Existing global `event_id` uniqueness and record identities survive.

Existing `GET /api/v1/telemetry/history` page/aggregation responses are unchanged.
Opt in with `pagination=cursor` (default `page`), `page_size=1..200`, optional
`cursor=<opaque token>`, and the existing workspace/network/metric/time filters.
Cursor mode is raw history only; `page` must be 1, aggregation/buckets are rejected.
A cursor without cursor mode is rejected. Success uses the standard envelope with
`data={items, page_size, next_cursor, upper_observed_at, upper_record_id}`; there is
no expensive count or invented total. Empty results have null upper watermark.
Errors use the existing canonical envelope (422 invalid combinations, 400 invalid,
expired, tampered or mismatched cursor; current authorization failures remain 403).

Every request rechecks current membership and `read:telemetry`. Tokens bind the
actor, resolved workspace/network, normalized complete filters, page size and raw
history endpoint/version. HMAC-SHA256 uses a domain-separated key derived from the
existing settings JWT secret. Tokens are opaque API values, authenticated but not
encrypted, expire after 15 minutes without renewal, and fail after secret rotation.
Ordering is `(observed_at DESC, record_id DESC)`; continuation uses strict keyset
comparison below the last item and at/below the initial upper tuple. A fixed
creation-time cutoff also excludes ordinary later backfill. This is a bounded
traversal, not an MVCC snapshot across HTTP requests: transactions already in flight
at the cutoff may become visible later. Clients needing a frozen export must use an
owner-held snapshot. Device and aggregate endpoints retain page mode.

## Owner contract and handoff

Only trusted composition instantiates a telemetry-owned evidence service bound to
one of `report`, `intent`, `alert`, `simulation`, `autonomy` and one workspace. This
is an internal owner-service contract, not user-supplied authority or a new event.
Owning services must perform their own actor authorization before calling it.
Telemetry validates every pin's record/network/workspace and never queries owner
tables. Each pin binds owner, immutable reference UUID and record UUID, with a
restricting telemetry-local FK. Release is explicit, scoped and durable, never TTL.
Released pins retain their audit FK too: a prospective archival candidate is not
permission to delete its row; future deletion needs an approved audit-link strategy.
Reusing a released reference/record pair is rejected; use a new reference identity.
Methods flush but do not commit: caller owns the transaction. Persist pins before
publishing references; for independent transactions pin first and compensate only
after proving no reference became durable. Orphan pins conservatively retain data.

`register_prospective` records database time, coverage version 1 and the explicit
`pin-before-reference/v1` attestation. It cannot backdate or certify history.
Registration is idempotent and revocable; revoked registration cannot silently
reactivate. Pin issuance is allowed before registration to support safe rollout.
Registration is an owner attestation, not proof that integration has happened.
Default composition registers **nobody**. All five owners must be registered for
the workspace before even prospective unpinned rows can be classified as archival
candidates. Version changes/new reference owners require extending the required
owner set and coverage contract, not ignoring unknown owners.

Parent handoff must integrate report source snapshots/artifact references and
intent evidence/plan/execution/rollback references, plus alert observations/history,
simulation inputs/results and autonomy decisions/certificates. Each owner needs
exact record identities, pin-before-reference writes, replay/crash handling and
release only after all retained references cease to require the evidence. Historical
backfill/reconciliation and independent coverage verification are still missing.
Do not register owners merely because these methods or tables exist.

## Assessment and migration

The new internal assessment accepts one workspace, aware `[start_time,end_time)`
observed-time window (at most 31 days), and at most 1000 records per batch. It uses
time-indexed ascending keysets and reports pinned, coverage-unknown and prospective
candidate IDs with a continuation tuple. Pinned rows are retained regardless of
registration/release by other owners. Rows predating registration by either observed
or creation time stay unknown; empty pins never certify historical safety. Every
result is a dry run, `deleted=0`; no archival object or restored copy is claimed.
The existing operations assessment remains conservative. Parent operations wiring,
archive serialization/integrity/restore, disk admission, transactional pin-vs-delete
coordination, complete historical coverage and retention execution remain open.

Migration adds only telemetry-owned tables and workspace/time/keyset indexes.
Downgrading destroys pin/coverage metadata and must never be used to infer absence
of evidence. It preserves telemetry rows and original unique keys. Index creation
uses transactional DDL and needs a scheduled lock/build window for large existing
tables. Partitioning remains a separate operator decision requiring a global event
deduplication design, FK/uniqueness analysis and measured migration/rollback plan.

## Validation

2026-09-20 validation:

- Cursor/owner/assessment unit tests and history API regressions: **63 passed**.
- Existing telemetry repository, persistence, query, history bounds, foundation,
  scaffold, consumers, counters, persistence flow, synthetic load and startup:
  **196 passed**.
- Real PostgreSQL18.6 on an isolated Unix-socket-only cluster: **5 passed** across
  `test_telemetry_lifecycle_postgres.py` and `test_telemetry_history_sql.py`.
  Covers duplicate-time keysets, tenant/network/metric/time filtering, higher-tuple
  and later-backfill exclusion, durable/replayed pins, concurrent pin issuance,
  rollback, multi-owner release isolation, registration/revocation, history blocked,
  prospective assessment pagination, FK protection and global event uniqueness.
- Real Alembic fresh `0001..0024`, `0024 -> 0023 -> 0024` executed successfully in
  that disposable cluster, including the separately owned0022/0023 predecessors.
- Scoped Ruff and whitespace checks pass. A rollback fixture initially accessed
  an expired ORM identity; fixed by retaining immutable IDs before rollback.
- Final combined scoped regression, including all five real PostgreSQL tests:
  **264 passed in 7.30s**, no skips. Isolated cluster shut down successfully.

Reproduce focused gates from `backend/`:

```sh
poetry run pytest --no-cov -q tests/unit/test_telemetry_lifecycle.py tests/integration/test_telemetry_endpoints.py
TELEMETRY_TEST_DSN='<isolated postgresql+asyncpg DSN>' poetry run pytest --no-cov -q tests/integration/test_telemetry_lifecycle_postgres.py tests/integration/test_telemetry_history_sql.py
```

Integration tests use unique schemas and remove them in `finally`; explicitly set
the DSN to an owned test database. The full-chain check used an in-process Alembic
settings injection to select the isolated Unix socket, since the existing settings
host validator deliberately accepts hostnames rather than socket paths. No shared
settings/environment files were changed. Parent composition remains responsible for
explicit owner wiring and adding pin models to its centralized metadata imports if
needed for autogeneration; migration0024 itself imports its owning models.

No shared database migration, Docker, training, commit or deployment qualification
was performed. The local cluster was stopped after verification.
