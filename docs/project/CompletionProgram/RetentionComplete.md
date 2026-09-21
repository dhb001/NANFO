# ADR023 cross-owner telemetry retention

## Design and ownership

Migration **0025**, after0024, is reserved for Telemetry archive receipts, permanent
global event tombstones and bounded reconciliation progress. Parent owns main/config/
deployment composition; fleet0026 must ingest through `TelemetryPersistenceService`.

Owner services (Report, Intent, Alert, Simulation, Autonomy) install transaction-local
pin-before-reference guards and expose bounded keyset historical enumeration. Guards
call Telemetry's public contract using the same database transaction; they never
query Telemetry tables themselves. Reference identity binds owner object, source
field and canonical evidence bytes. Changed evidence obtains a different identity.

All ever-pinned rows remain indefinitely, even after logical release: the existing
RESTRICT FK and released-pin audit remain valid. Archive/delete locks telemetry rows
exclusively; pin takes a shared row lock. The loser either retains the row or refuses
the reference. No owner reference may commit pointing at deleted telemetry.

Coverage is registered only after the installed owner guard and actual bounded owner
enumeration/reconciliation complete. Unknown/unparseable legacy references are
reported explicitly and old data stays retained. Coverage permits only new rows
created and observed after the latest owner enrollment; backfill stays retained.

Canonical full-row archive bytes are durably stored in a private content-addressed
filesystem and read back/checksummed before deletion. Receipts and permanent event
tombstones commit with deletion. Restore validates tenant, identity, size and checksum
and preserves original row identities. Replay ingestion uses global event exclusion
and checks both active rows and permanent tombstones.

## Delivered behavior

- `references.py` supplies a bounded evidence parser and same-transaction ORM
  `before_flush` contract. Each owner service installs its own extractor. The hook
  runs in AsyncSession's greenlet and calls Telemetry's public synchronous contract
  using the owner's connection **before any reference INSERT/UPDATE**. Evidence
  versions use UUIDv5 over object/field/canonical-content SHA256; status changes do
  not retarget identities. Alert measured ingestion explicitly resolves/pins its
  persisted event before accepting the observation receipt/window update.
- Real bounded public `telemetry_reference_page` contracts enumerate Report frozen
  snapshots; Intent payload/provenance/executions/outbox; Alert observations,
  incidents/history (including unknown scope); Simulation current/branch metadata
  and outbox; Autonomy controls, decisions, overrides and optional0027 observation,
  execution and provider-state tables. Joins, where needed, stay inside each owner.
  Autonomy0027 provider frame insertion already explicitly pins its samples through
  the Telemetry contract; its files were inspected, not edited by this workstream.
- Reconciliation records cursor, scanned count, unknown count and completion in
  Telemetry storage. Missing locators, malformed evidence and non-enumerable legacy
  rows are explicitly unknown. Known references are pinned even in a partially
  unknown item. No historical completeness claim makes old rows deletable.
  Migration0025 revokes manually enrolled0024 coverage; registration now requires
  installed wiring and a completed real reconciliation. Enrollment time, not the
  start of a multi-batch scan, establishes prospective eligibility.
- `TelemetryRetentionService.apply` performs actual bounded deletion of eligible
  unreferenced new rows. Coverage read locks serialize revocation; global event
  advisory exclusion serializes archive/ingest/restore; telemetry row shared versus
  exclusive locks and a fresh pin check exclude pin/delete races. The RESTRICT FK
  remains the final guard. All ever-pinned rows are retained indefinitely.
- Archive files are private owner-only, no-symlink, content-addressed canonical full
  rows (maximum2MiB each). File fsync, atomic publication, directory fsync and exact
  readback precede receipt/tombstone/delete. A crash leaves either original rows or
  recoverable receipt-backed bytes; uncommitted orphan archive bytes are harmless.
  Restore checks receipt scope, size, SHA256, canonical representation and original
  identities; permanent global event tombstones are never removed.
- `TelemetryPersistenceService.persist_event` is the authoritative dedup path:
  transaction advisory lock, tombstone check, active-row check, validated insert.
  Fleet must use this service rather than direct repository/SQL insertion. Tombstone
  replay returns `False`, including a reused event UUID with another tenant payload.

## Operator CLI and bounded worker

From `backend/`, provision a private0700 archive directory owned by the backend UID,
then configure `TELEMETRY_RETENTION_DSN` through the operator environment. It is not
accepted as a command-line credential. Use the deployed schema0025 or later.

```bash
# Repeat for report, intent, alert, simulation and autonomy until complete=true.
poetry run python scripts/telemetry_retention.py reconcile \
  --workspace-id "$WORKSPACE" --owner report --batch-size 100 --max-batches 10

poetry run python scripts/telemetry_retention.py dry-run \
  --workspace-id "$WORKSPACE" --start-time "$START" --end-time "$END" \
  --batch-size 100 --max-batches 10

poetry run python scripts/telemetry_retention.py apply \
  --workspace-id "$WORKSPACE" --start-time "$START" --end-time "$END" \
  --batch-size 100 --max-batches 10 --archive-root "$ARCHIVE_ROOT"

poetry run python scripts/telemetry_retention.py restore \
  --workspace-id "$WORKSPACE" --record-id "$RECORD" --archive-root "$ARCHIVE_ROOT"
```

Windows are at most31 days; batches1..1000 records, reconciliation pages1..100
owner objects. `--after` accepts the JSON `next_position` of a capped sweep; keep
the same window/workspace. Omit it to rescan safely. Reconciliation resumes its
durable owner cursor automatically. Each batch has its own transaction and timeout
(default30s, maximum300s). `TelemetryRetentionWorker` accepts a session factory and
validated `RetentionWorkerSettings`: finite1..1000 batches, default10, configurable
0..3600s inter-batch delay. Scheduler invocation supplies explicit workspace/window,
apply mode and archive root. The CLI defaults to no mutation through `dry-run`;
`apply`, `restore` and `reconcile` are explicit operations. Restore does not extend
the retention age of an unpinned row; repeat sweeps may archive it again.

## Verification (2026-09-20)

- New disposable PostgreSQL integration gate: **11 passed**. Full Alembic chain to
  0025, actual deletion/restore, all five owner write hooks and bounded historical
  enumeration, Report source-service capture/crash/replay, released-pin FK retention,
  pin-first/delete-first concurrent transactions, tenant rejection, checksum tamper,
  archive-ack loss/rollback/replay, global old-event and concurrent ingestion dedup,
  bounded worker, CLI dry-run/apply/restore, optional0027 owner model enumeration.
- Combined lifecycle/retention/report unit+PostgreSQL+actual disposable Redis gate:
  **53 passed** before the final additional CLI test. Existing Alert PostgreSQL
  gate plus retention gate: **40 passed**; Alert fixtures now persist their actual
  source evidence before calling the measured owner boundary. Report Redis lost-ack
  replay and report lease/outbox tests pass with the permanent-pin behavior.
- Broad backend regression: **2845 passed,174 skipped**, excluding the parent-owned
  `tests/unit/test_verify_measured_twin.py`. Its pre-existing acceptance constant
  still asserts schema0024 while parallel migrations advance the head to0027.
  Earlier failures from unconfigured tombstone mocks and source-free Alert fixtures
  were corrected and rerun. Scope lint and `git diff --check` pass.
- Only newly created `nanfo-retention-adr023-pg` and `nanfo-retention-adr023-redis`
  containers were used. Tests create/drop unique schemas and private temporary
  archive files. Both disposable containers were stopped and auto-removed after
  verification. No shared databases migrated, shared rows deleted or lab executed.

Reproduce the decisive gate with an explicitly disposable DSN:

```bash
RETENTION_TEST_DSN="$DISPOSABLE_PG_DSN" poetry run pytest \
  tests/integration/test_retention_complete_postgres.py -q --no-cov
```

## Parent handoff and operating limits

### Review finding7 correction (2026-09-20)

- Replaced constructor-only `resolve()` plus final-component `O_NOFOLLOW` with a
  descriptor walk from `/` for every admission/read/write. Every component uses
  `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`; per-store device/inode identities bind the
  entire path. Publication and readback retain the same root descriptor. Before
  returning success, retained descriptor permissions and a fresh path walk must
  still match, so a renamed root/ancestor cannot authorize SQL deletion.
- Archive root now requires exact0700/current UID. Files require0400 or0600/current
  UID and regular-file type. Ancestors must belong to root/current UID and reject
  group/world write except sticky directories. Provision deployment paths to those
  actual constraints; no parent config/deploy changes were made in this correction.
- **77 passed**: full actual disposable-PostgreSQL retention/lifecycle plus unit
  gates. Includes twelve replacement timing/type/target combinations asserting no
  deletion call or receipt/tombstone effect, followed by repaired-path restart,
  actual deletion and restore. Read substitutions, identical-byte impostors and
  permission changes also reject. Existing safe archive/tamper/tenant/owner/race
  gates pass. The original defect-asserting reviewer repro now refuses its symlink.
- Finding6 replay/fanout and optional service accessor remain with the distributed
  agent. `telemetry/service.py` and `telemetry_consumer.py` were untouched by this
  correction. Full reviewer outcome: `ADR023Review.md`, finding7.
- Protection is checked through the archive operation's successful return; as with
  the archive bytes themselves, subsequent intentional relocation/removal by the
  trusted filesystem owner requires coordinated deployment/backup management.
  Directory handles cannot prohibit a privileged operator from moving a volume.

1. Import `app.modules.telemetry.archive_models` in Alembic metadata composition;
   upgrade0025 before running modified ingestion, owners or retention. Fleet0026
   follows0025. No main/config/deploy files were edited here.
2. Deploy the owner services/worker imports together and drain old binaries before
   enrollment. Do not enable deletion while an old unpinned writer can still run.
   ORM bulk SQL reference writes bypass `before_flush` and must explicitly call
   `TelemetryEvidenceService` before writing; current audited owner reference paths
   use guards or the explicit Alert/provider-frame contracts.
3. Schedule bounded worker sweeps for selected workspaces and age windows, using a
   protected persistent archive volume. Back up archive bytes with database receipts
   and tombstones; losing either is not a verified restore. This code does not mount
   volumes or register a global scheduler in parent composition.
4. All pre-enrollment/backfilled rows, unknown history and ever-pinned data remain.
   This deliberately trades space for audit safety. Tombstones/receipts/pins are
   permanent; no unsafe garbage collector or expiry is provided. Downgrade0025 is
   refused once archive receipts exist because dropping them would lose dedup/audit.
5. Update parent source-matched acceptance schema expectations and run final composed
   deployment acceptance at the final migration head. No deployment completion or
   physical measurement qualification is inferred from the software gates above.
