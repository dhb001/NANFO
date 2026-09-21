# P0 Network transactional inventory outbox — ADR021 handoff

## Delivery and ownership

Implemented in the Network-owned files below. No shared deployment/configuration,
central tracking, Network spatial models/schemas/repository, or application
composition changes are included. No commits, shared database or Docker operations
were run. A subsequently authorized private local PostgreSQL verification is
recorded below.

- `backend/app/modules/network/service.py`: inventory mutation sections.
- `backend/app/modules/network/outbox_models.py`: separate `NetworkOutbox` model.
- `backend/app/modules/network/outbox.py`: enqueue repository, leases and publisher.
- `backend/alembic/versions/0020_network_inventory_outbox.py`: additive0020 after0019.
- `backend/scripts/run_network_outbox_worker.py`: independent bounded worker.
- `backend/tests/unit/test_network_outbox.py`: offline fault/contract tests.
- `backend/tests/unit/test_network_service.py`: existing service regressions updated.
- `backend/tests/unit/test_emulation_inet_event.py`: existing JSON-safe INET regression.
- `backend/tests/integration/test_network_outbox_postgres.py`: opt-in database acceptance.

## Mutation audit and contract

| Inventory operation in `service.py` | Durable event |
| --- | --- |
| `NetworkService.create_network` | `network.network.created` |
| `DeviceService.add_device` | `network.device.added` |
| `DeviceService.update_device_spatial_ref` | `network.device.updated`; unchanged values enqueue nothing |
| `CampusBuildingService.upsert_buildings` | No domain event specified by Network PRD §5 |
| `CampusModelAssetService.upsert_asset` | No domain event specified by Network PRD §5 |
| `DeviceGroupService.upsert_groups` | No domain event specified by Network PRD §5 |

These are all six committing inventory service paths found during the audit.
Building/asset/group replacements include their existing soft deletes in the same
inventory transaction and remain read through their documented REST surfaces.
`topology.py` also publishes reconcile requested/failed/completed events, but those
describe Neo4j reconciliation, not PostgreSQL inventory mutations; this outbox does
not make that separate operation transactional.

The three lifecycle paths enqueue before their existing commit in the **same
AsyncSession/transaction**. Enqueue/commit failure rolls back and propagates;
Redis is never called on the mutation path. Responses retain their existing
schemas and authorization checks. Existing event names, payloads (including
JSON-safe INET handling), source `network`, version `1`, and request correlation
IDs are preserved.

Each row contains a generated event UUID and a persisted complete Redis field map:
`event_id`, `event_type`, `timestamp`, `source`, `correlation_id`, `version`, and
JSON-string `payload`. IDs/timestamps and serialized payload remain identical on
every retry. The worker uses `XADD stream:network` directly because the shared
`publish_event` helper creates a fresh timestamp on each call.

## Transactions, ordering and recovery

- `network_outbox` has an identity sequence, owning network UUID, JSONB envelope,
  creation/due timestamps, attempt count, lease token/expiry, publication timestamp,
  and sanitized last exception **class name**, with partial pending indexes.
- Device create/update acquire a transaction-scoped advisory lock per network
  before reading/mutating inventory. This serializes event sequence allocation
  with committed device writes. New network IDs are not visible before their
  creation/event commit. Lock hash collisions only reduce concurrency.
- A worker claims one due row with `FOR UPDATE SKIP LOCKED`, excluding any network
  with an older unpublished event. It persists a fresh UUID lease token and
  increments attempts, commits, then releases the database session before Redis I/O.
- Acknowledgement and retry updates are conditional on the current unexpired
  token and unpublished status. An old worker cannot complete/release a new lease.
- Redis I/O has an explicit timeout shorter than the lease. Redis failures defer
  with exponential retry (1s base, 300s cap by default). Failed publications are
  retained indefinitely rather than silently dropped after a retry count.
- Death/cancellation before publication, lost Redis acknowledgement, or a database
  acknowledgement failure leaves an expired lease reclaimable by another process.
  A lost acknowledgement can append the same event twice: delivery is **at-least-once**.
- Each iteration attempts at most32 events by default and uses the shared
  `worker_iteration("outbox")` deadline/heartbeat mechanism. A failed batch does
  not report healthy progress. Other due networks become eligible on later polls;
  an older failed event blocks only its own network.

## Required parent integration

1. Apply migration0020 **before deploying the inventory service changes**. Spatial
   migration0021 must declare `down_revision = "0020"`. Upgrade/downgrade0020 only
   adds/removes `network_outbox`; downgrade destroys its retained pending/history rows.
2. Explicitly import `NetworkOutbox` from
   `app.modules.network.outbox_models` in `backend/alembic/env.py` for canonical
   autogenerate metadata registration. The0020 migration itself already imports
   the separate model; service and worker import it through `outbox.py`.
3. Run the independent worker in the backend environment, with the same owning
   PostgreSQL/Redis configuration as the API:

   ```sh
   poetry run python -m scripts.run_network_outbox_worker
   # Bounded operator invocation; exits nonzero on publication failure:
   poetry run python -m scripts.run_network_outbox_worker --once --batch-size 32
   ```

   CLI options: `--poll-seconds` (0.5), `--lease-seconds` (30),
   `--publish-timeout` (5), `--retry-base-seconds` (1),
   `--retry-max-seconds` (300), `--batch-size` (32; maximum1024).
   No new dependencies or public endpoints are required. Use module invocation
   from `backend/` (or its image working directory) so `app` is importable.
4. Parent deployment wiring owns process restart policy, credentials, worker health
   file path, and image/composition inclusion. Add a `network` worker entry with
   `("outbox",)` to `runtime_health.WORKER_LOOPS`, and advance `SCHEMA_HEAD` to the
   final integrated migration revision (0021 when spatial is included). Configure
   the existing iteration timeout/heartbeat age consistently with batch/I/O bounds.
5. Ensure existing Network event consumers are running. The event bus deduplicates
   per handler by stable `event_id`; durable audit and topology projection have
   their own replay guards. Websocket delivery retains the shared bus's bounded
   completion-marker semantics; this change does not claim exactly-once delivery.
6. New event-bearing spatial mutations must reuse `lock_inventory(network_id)`
   **before** device mutation and `enqueue(...)` **before** their transaction commit
   if they produce an existing documented inventory event. Do not call the worker
   or Redis within an inventory transaction. New event names require PRD approval.
7. Run the opt-in PostgreSQL acceptance below against the disposable lab database,
   then integrated API/worker/consumer interrupted-publication acceptance.

## Verification

From `backend/`:

```sh
poetry run pytest --no-cov \
  tests/unit/test_network_outbox.py tests/unit/test_network_service.py \
  tests/unit/test_emulation_inet_event.py tests/unit/test_network_schemas.py \
  tests/integration/test_network_outbox_postgres.py tests/integration/test_network_endpoints.py

poetry run ruff check \
  app/modules/network/service.py app/modules/network/outbox.py \
  app/modules/network/outbox_models.py alembic/versions/0020_network_inventory_outbox.py \
  scripts/run_network_outbox_worker.py tests/unit/test_network_outbox.py \
  tests/unit/test_network_service.py tests/unit/test_emulation_inet_event.py \
  tests/integration/test_network_outbox_postgres.py
```

Initial offline scoped run: **146 passed, 4 skipped**; backend Ruff0.15.6 passed.
Worker `--help` import/CLI smoke check and scoped `git diff --check` passed.
An initial system Ruff invocation from the repository root picked up different
lint settings and reported import/suppression diagnostics; the supported backend
environment command above is the reported gate. No dependency files were changed.

Offline checks exercise mutation/event commit ordering for all three paths,
rollback on enqueue/commit failure, unchanged-update suppression, event payloads,
stable replay after lost acknowledgement, shared consumer deduplication, capped
backoff, cancellation, Redis timeout, stale-token SQL predicates and batch bounds.
The additional offline migration test renders upgrade/downgrade PostgreSQL DDL.

Database tests are explicitly skipped unless `NETWORK_OUTBOX_TEST_DSN` is set.
They create/drop only a random `network_outbox_test_<uuid>` schema and migrate
through0020, downgrade to0019, then upgrade again. They cover actual transaction
rollback, concurrent claims, per-network ordering, lease expiry/stale-token fencing,
due-time retry, and lost-ack restart replay. Redis is in-memory in these tests.

### Private PostgreSQL verification — 2026-09-19

User authorized local disposable PostgreSQL after the offline handoff. Used installed
**PostgreSQL18.6**, a new private cluster at
`/tmp/opencode/network-outbox-postgres-zlmgzh`, Unix socket port**55487**, empty
`listen_addresses` (no TCP), socket permissions0700. The spatial workstream's
cluster was only referenced in its handoff; it was not used or modified.

```sh
NETWORK_OUTBOX_TEST_DSN='postgresql://DHB@/postgres?host=/tmp/opencode/network-outbox-postgres-zlmgzh&port=55487' \
  poetry run pytest --no-cov -v tests/integration/test_network_outbox_postgres.py \
  --junitxml=/tmp/opencode/network-outbox-postgres-zlmgzh/interop-results.xml
```

- Original four tests: **4 passed in3.13s**, no skips/failures.
- Expanded suite with both interop schedules: **6 passed in4.50s**, no skips/failures.
- Only test changes were necessary: parameterized fixture migration target (default
  stays0020; interop cases use0021) and two forced-overlap integration cases.
- Scoped backend Ruff0.15.6 passed for the changed integration test.
- Before shutdown: `remaining_test_schemas=0`, `pg_stat_database.deadlocks=0`.
- `pg_ctl -m fast -w stop` completed; subsequent `pg_ctl status` returned
  `no server running`. Server log records clean shutdown at22:12:26 EAT.
- Retained evidence outside the repository: `initial-results.xml`,
  `interop-results.xml`, `verification-summary.md`, and `server.log` in the private
  cluster directory. No production-code fix was required by these checks.

### Spatial/inventory locking interop review

The current spatial implementation uses **row-level `FOR SHARE`**, not advisory
locks: network row, associated device rows sorted by UUID, then scene revision
insert/update, audit append, commit. Inventory spatial-reference updates acquire
the per-network advisory lock, read device, update device, enqueue event, commit.
The publisher only locks outbox rows and never acquires spatial/inventory locks.

No reverse acquisition dependency exists between these paths: the spatial writer
does not request the inventory advisory lock, and the inventory writer does not
request the scene row. Device creation's foreign-key network `KEY SHARE` lock is
compatible with spatial's network `SHARE` lock. Spatial membership validation can
reject a concurrently uncommitted new device; retry after its creation commits.

The two new PostgreSQL cases run the actual services and real Organization
membership checks. One holds spatial device SHARE locks while inventory attempts
its UPDATE; the other holds the inventory device UPDATE while spatial attempts
its SHARE lock. Each verifies the actual blocker PID with `pg_blocking_pids`,
releases the first writer, and requires both operations to finish within5s. Fresh
reads verify device `spatial_ref_id`, scene revision/device association, one spatial
audit record and one matching unpublished `network.device.updated` envelope.

There is intentionally no shared revision between canonical scene placement and
legacy `spatial_ref_id`: scene replacement does not change the inventory field or
emit a device event. These tests verify coexistence, not automatic synchronization.
Future paths acquiring both lock families must preserve a consistent order;
current no-op/error inventory transactions release their locks when the request
session closes. Direct service callers must likewise close/rollback their session.

## Limits and outstanding acceptance

- PostgreSQL migration/concurrency and spatial/inventory overlap are now verified
  locally. Redis remained in-memory; real Redis persistence/restart and integrated
  API/worker/consumer acceptance remain outstanding.
- Delivery durability after a successful `XADD` also depends on Redis persistence,
  stream retention, and consumer operation. A database `published_at` proves Redis
  acknowledged the append, not that all consumers applied it.
- A paused former lease owner can still send a duplicate after lease expiry;
  lease tokens fence database completion, not Redis itself. Stable IDs and existing
  consumer replay/ordering guards are necessary. No global ordering across networks
  or exactly-once guarantee is claimed; event clocks rely on synchronized hosts.
- Pending failures and published rows are retained with no automatic cleanup or
  quarantine endpoint. Operators must monitor oldest pending age, attempts,
  `last_error`, lease expiry and disk growth. A permanently failing envelope blocks
  that network until repaired through controlled owning-module operations.
- No historical backfill/recovery of events already lost before migration0020.
  Request-level idempotency for retried create HTTP requests is also unchanged.
- The standalone worker is required for eventual publication. An API-only rollout
  commits inventory successfully but accumulates unpublished events.
