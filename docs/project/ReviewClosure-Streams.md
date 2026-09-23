# ADR027 / R04 — Domain-stream retention handoff

## Delivered scope

`backend/app/events/retention.py`, `retention_lua.py`, and `retention_archive.py`
implement operator-only bounded archive-before-delete. Entry point:
`backend/scripts/stream_retention.py`. No startup registration: deletion is **off
by default**. No main/config/compose, publisher/bus, REST, or migration changes.
ADR027 is the approval; EventAPI §4, ADR010 recovery and the existing private
telemetry archive's filesystem protection contract informed this implementation.

Only the nine domain streams registered in `bus.STREAM_GROUPS` are accepted.
`stream:dead_letter` and lossy realtime fanout are excluded. Neither `MAXLEN` nor
`XTRIM` is used. DLQ inspection/recovery/retention remains a separate operation.

## Eligibility and concurrency

1. Each invocation supplies **all** approved group names explicitly. The observed
   group set must equal that allowlist; zero, missing, unknown or additional groups
   block retention. Never auto-enroll a newly discovered group.
2. A fixed age cutoff is derived from **Redis TIME**, using the stream ID's
   millisecond component, not a producer-supplied event timestamp. Only IDs strictly
   below that cutoff, at/below every group's last-delivered ID and **strictly below
   every group's earliest pending ID**, are eligible. ACKed holes above an older
   pending entry deliberately remain. Unread/new and pending entries remain.
3. Redis Lua obtains a coherent group/PEL snapshot and a bounded candidate page.
   Unknown entries-read/lag or malformed state fails closed. IDs are compared as
   uint64 decimal pairs, never floating-point numbers.
4. A verified archive containing its manifest is durably published before deletion.
   A second Lua script atomically enumerates all groups again, validates the exact
   group/delivery/entries-read/pending/min-pending/consumer-count snapshot, rechecks
   every ID boundary, and compares **every raw field byte in order** before one
   `XDEL`. All validation precedes the first mutation. Group creation/destruction,
   rewinds, forced pending entries, consumer-count changes and changed/missing
   entries observed at this point refuse the whole batch. Concurrent ordinary
   publishing does not invalidate the snapshot; those new entries stay untouched.

### Exact limits of the safety claim

- Redis does **not** retain a historical ACK ledger. This policy requires the
  existing bus contract: `XREADGROUP` without `NOACK`, durable handler effect or
  confirmed untrimmed DLQ append before `XACK`, groups initially created at `0`.
  Administrative `SETID`, skipped-history `$` enrollment, `NOACK`, `DELCONSUMER`
  with pending work, destroy/recreate and destructive stream operations invalidate
  that contract. Do not use them on enrolled groups. Redis cannot distinguish
  previously skipped/dropped PEL history from ACKed history; this implementation
  cannot retroactively prove it or detect an indistinguishable complete ABA reset.
  Audit existing groups before opting in; use least-privilege consumer accounts.
- The Lua operation linearizes deletion against consumer/group operations on one
  authoritative Redis primary. A group created **after** deletion cannot demand
  already archived history from the live stream: provision it from a reviewed
  recovery/bootstrap procedure. Separate writable primaries and external Redis
  key deletion/eviction are outside this guarantee. Apply refuses an observed
  eviction policy other than `noeviction`; keep Redis configuration access restricted.
- ACK is the application's processing completion boundary, not a disk durability
  barrier. Configure and back up Redis persistence (AOF/fsync and recovery policy)
  and owning stores. No new replication consensus/WAIT/WAITAOF guarantee is claimed.
- Redis/filesystem cannot share a transaction. A crash can leave a complete archive
  with entries still present, or a successful deletion with its reply lost. Both are
  recoverable from the archive. Earlier batches can commit before a later refusal.
  A bundle's `archived_before_delete` status **is not a deletion receipt**.

## Archive and recovery contract

Provision an absolute, current-UID-owned **0700** archive directory on persistent
local POSIX storage. Every path component is walked with directory descriptors and
`O_NOFOLLOW`, with device/inode binding rechecked. Ancestors must be root/current-UID
owned and not group/world writable except sticky directories. Symlink paths,
replacement roots/ancestors, nonregular files, foreign ownership, extra hardlinks
and permissions other than **0400/0600** on archive files are refused.

Each SHA-256-named file is a single canonical JSON **bundle**, atomically containing
both manifest and entries. Each entry records its original stream ID plus a flat
ordered base64 field/value vector. Repeated field names, arbitrary binary data,
malformed UTF-8, empty fields and JSON whitespace are preserved exactly. No envelope
decode/re-encode occurs. The manifest records source stream, approved groups,
opaque group-state snapshot, exclusive cutoff, first/last ID, count, canonical entry
byte length and SHA-256. The filename hashes the entire bundle. This is exact field
data archival, not a byte-for-byte Redis RDB/AOF image or consumer-group backup.

Publication: disk admission → exclusive0600 temporary → file fsync → no-overwrite
atomic hardlink → remove temporary → directory fsync → exact readback/hash/path
verification. The caller reads and verifies the published bundle again immediately
before deletion. A nonblocking directory flock serializes operators sharing a root.
Trusted owner/root tampering **after** verification cannot be prevented; preserve
the volume and coordinate relocation/backups. Hashes detect corruption, not a
malicious trusted owner rewriting data plus hashes. Partial `.pending-*` files never
authorize deletion; inspect/remove orphans only as a separately reviewed operation.

`restore` verifies a bundle and imports original IDs into an explicitly named
`recovery:...` stream with **no consumer groups**. It never replays into production.
Use a fresh target per source stream. Import bundles in ascending original ID order.
An existing ID with identical ordered raw bytes is an idempotent no-op; differing
bytes refuse the batch. Missing IDs below the target's last-generated ID refuse
the batch because Redis cannot insert historical gaps. A repeated `event_id` in
distinct stream entries is preserved, never collapsed. Subsequent reviewed replay
must retain event identity and owning-module durable deduplication. Consumer caches
expire; at-least-once external effects can repeat. Recovery does not restore PELs,
group cursors, completion caches or module databases. Restore under memory/transport
failure may partially import a batch; identical-byte retry remains safe.

## Operator invocation / optional deploy integration

From `backend/`, use the deployed Poetry environment or equivalent backend image:

```sh
# Credentials come only from the protected operator environment; never argv/logs.
# STREAM_RETENTION_REDIS_URL must point to the intended authoritative Redis DB.
poetry run python -m scripts.stream_retention health \
  --stream stream:telemetry --group nanfo-consumers --min-age-seconds 604800 \
  --archive-root /var/lib/nanfo/stream-archive

poetry run python -m scripts.stream_retention dry-run \
  --stream stream:telemetry --group nanfo-consumers --min-age-seconds 604800 \
  --archive-root /var/lib/nanfo/stream-archive \
  --batch-size 100 --max-batches 10 --max-entries 1000 --max-seconds 30 \
  --max-archive-bytes 16777216 --min-free-bytes 1073741824

# Explicitly replace dry-run with apply after reviewing group/persistence/history
# and capacity. Repeat --group for EVERY approved group. One stream per invocation.

poetry run python -m scripts.stream_retention restore \
  --stream stream:telemetry --group nanfo-consumers --min-age-seconds 604800 \
  --archive-root /var/lib/nanfo/stream-archive \
  --digest "$BUNDLE_SHA256" --target recovery:telemetry-incident-001
```

Integration owner may add an **optional** one-shot timer/CronJob using the same
source-matched backend, Redis credentials/DB, unprivileged archive UID, and a private
persistent archive mount. Schedule `health`/`dry-run` first. Enable bounded `apply`
only by explicit operator policy; no automatic schedule or deletion flag is installed
here. Avoid overlapping invocations; lock contention refuses immediately. Configure
job wall-time and service restart policy without blind restore retries. Include
the archive volume in encrypted backups and fresh-restore qualification alongside
Redis and owning stores. Existing deploy retention still preserves streams: this
is a separately opt-in operator, not a replacement for that command.

Redis ACL needs TIME, INFO, XINFO, XPENDING, XRANGE and EVAL for inspection, plus XDEL
for apply; recovery additionally needs EXISTS and XADD on isolated recovery keys.
Constrain keys to approved domain streams/recovery targets. Redis7+ is required for
known lag/entries-read. Do not give application consumers administrative group-reset
or retention credentials. The archive mount must not be exposed to web clients.

### Health / alert integration

JSON diagnostics expose stream length/oldest entry age; each group's lag, pending
count, delivery ID, oldest pending **entry age**, and that entry's delivery idle ms;
Redis global used/max bytes and ratio; archive free bytes and reserve. Entry age is
not the same as maximum consumer idle. This is a bounded observation, not an atomic
health snapshot or a backlog-wide maximum-idle search.

- Alert on unknown groups/state, any refused/incomplete run, absent expected job
  success, exhausted repeated budgets with continuing growth, old pending work,
  sustained lag, disk pressure, unsafe eviction, or unbounded Redis capacity.
- Defaults: Redis memory ratio ≥0.8; group lag ≥10000; oldest pending entry age
  ≥3600s; archive free < reserve +2MiB. CLI threshold options are explicit.
- Exit0: completed/healthy; exit2: warning diagnostics (apply may have completed);
  exit1: refused or incomplete (earlier batches may have committed). No raw event
  data, Redis URL, secrets, exception text or stack traces appear in CLI failures.
- On capacity pressure, reduce/stop ingestion through the owning operational
  controls, recover stuck consumers, and provision capacity. This code supplies
  diagnostics/admission, **not automatic producer throttling**. Pending/unread/DLQ
  backlog and archives can grow indefinitely; safety is preferred over data loss.
  Do not solve pressure with eviction, MAXLEN or indiscriminate archive removal.

## Precise work and capacity bounds

| Bound | Default | Accepted / enforced |
|---|---:|---|
| Streams per invocation | required | exactly1 registered domain stream |
| Approved groups | required | 1–64 unique names, each1–128 ASCII safe characters |
| Consumers per group | — | ≤64, otherwise refuse bounded inspection |
| Minimum age | required | 60–315360000 seconds, Redis-time fixed cutoff |
| Entries per batch | 100 | 1–100 |
| Batches per run | 10 | 1–1000 |
| Entries per run | 1000 | 1–100000 |
| Run time | 30s | 1–300s admission/async deadline |
| Raw entry | — | ≤65536 bytes including ID, ≤128 field/value pairs |
| Raw candidate page | — | ≤1MiB, read one entry at a time |
| Atomic archive bundle | — | ≤2MiB including manifest/base64 |
| Archive bytes per run | 16MiB | 1 byte–1GiB; whole next bundle must fit |
| Disk free reserve | 1GiB | 1MiB–1PiB; admission reserves rounded file allocation +4 blocks |
| Redis CLI socket/connect wait | 3s | fixed, no timeout retry |
| Restore | one bundle | ≤100 entries, ≤2MiB, explicit isolated target |

The run deadline stops new work and is rechecked after synchronous archive I/O
before deletion. It is **not** a hard wall-clock bound on a stalled kernel fsync,
an already-issued Redis script, or client cleanup; an external supervisor may
terminate an uncertain job, leaving verified archive recovery. Lua itself is
bounded by entries/groups/field counts, but fetching an already-existing oversized
entry must allocate that one Redis value before rejecting it. No new publisher
payload limit is imposed. Diagnostics XINFO STREAM also observes first/last entries.
Filesystem reserve admission is not a quota against unrelated writers; fsync/write
errors still prevent deletion. `max_archive_bytes` bounds this invocation's attempted
archive content, not total historical disk consumption. One successfully written
but not deleted batch can remain on interruption/refusal, within that budget.
Group churn/unknown historical state/oversized first entries can deliberately stall
progress. Time, batch, entry and byte budgets do not mean all eligible history was
drained. Re-run from the beginning safely; no persisted cursor is necessary.

## Verification

Real Redis uses **only** the existing `LocalLab` / `DockerRedis` exact-disposable
helper, an explicitly supplied already-installed image digest, generated private
credentials, new labelled container/volume, verified loopback port and exact cleanup.
No shared services, pulls, migrations, API processes or lab actuation are used.

```sh
STREAM_RETENTION_TEST_IMAGE=sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2 \
  poetry run pytest tests/unit/test_stream_retention.py \
  tests/integration/test_stream_retention_redis.py \
  tests/unit/test_event_recovery.py -q --no-cov
```

Coverage includes all-group ACK eligibility, pending/unread/fresh entries, unknown
and newly enrolled groups, reset/destroy/new-group/consumer/forced-PEL/deleted-entry
races between archive and deletion, binary/repeated-field exact recovery, conflict
and duplicate-ID recovery, >2^53 ID comparison, archive failure/tamper/fsync/path
replacement, disk/byte/time/entry/batch admission, lost delete reply, concurrent
appends, actual CLI operations and five100-entry capacity reuse cycles. This is
bounded fixture evidence, not representative production throughput qualification.

Executed 2026-09-21: **63 passed, zero skipped, 4.01s** across the new unit/real-Redis
gates and existing event-recovery regressions. Scoped Ruff passed. The disposable
fixture asserted exact container/volume removal, closed Redis port and removed
private tree. The initial expanded gate's one failure was a test expecting zero
deletions rather than the correct fail-closed error for a newly created group's
unknown entries-read; corrected that expectation. The final63-test gate also
includes malformed recovery-bundle structure rejection and passed in full.
Global sprint, journal, release integration and source-matched deploy acceptance
remain coordinator owned under ADR027. No commits performed.
