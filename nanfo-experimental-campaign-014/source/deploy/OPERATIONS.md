# ADR020 Operations Interface

These tools require host Python 3.12+, `cryptography`, Docker and Compose v2.
No application packages are installed into the frozen AI runtime. Run from the
repository root, or invoke the scripts by absolute path. All Docker operations
require an explicit `nanfo-deploy-*` project, Compose file(s), and env file.

## Backup

Provision a separate owner-only file containing exactly 32 random raw key bytes
through the operator's secret manager. This tool does not generate or recover the
key. Keep it outside the backup directory, mode 0600, and escrow it separately.
The existing destination directory must be operator-owned, empty, mode 0700.

```sh
python3 deploy/backup_restore.py backup \
  --project nanfo-deploy-source \
  --compose-file deploy/compose.yaml \
  --env-file /protected/source/deployment.env \
  --directory /protected/backups/checkpoint \
  --encryption-key-file /protected/keys/backup.key
```

Repeat `--compose-file` for each deployed overlay, including lab/AI. Freeze
host-side model/registry/binding producers and serialize operator/Docker activity
for the entire operation. Docker inspection cannot fence an unrelated host process.
Do not use `manage.py stop` as a substitute for the safety checkpoint.

The tool stops gateway/API admission first. Intent/Autonomy owner services refuse
unresolved execution, uncertain cancellation, active controls and unresolved timed
overrides before recovery workers are stopped. On refusal, recovery workers and
stores remain available; gateway/API remain stopped. Resolve through their existing
owner workflows, not SQL updates or forced successful status. After all writers
stop, a second checkpoint precedes clean store shutdown. Every owned local named
volume is copied, including PostgreSQL, Redis AOF/streams, Neo4j application/system
data, reports, command/result/output mailboxes and encrypted runtime/init secrets.
No migration, logical-only dump, stream trim, FLUSHDB or physical command replay.

Read-only external binding/model/registry directories receive separate encrypted
archives in `manifest.binds`. Unknown regular bind mounts, anonymous/external
volumes, dirty store shutdowns and uncovered persisted model references are refused.
Compose secret files and the Redis entrypoint script are keyed-fingerprinted;
restore requires their original identical bytes. Source host paths are not exposed.

Each archive uses streaming AES-256-GCM with project/archive/volume identity as AAD.
The manifest has an HMAC-SHA256 signature and ciphertext SHA256s. Files are 0600.
Archives are decrypted into anonymous local temporary files and fully validated
before a completed manifest is published or restore extraction begins. Regular
files/directories and root-confined links are supported; traversal, parent-relative
links, duplicates, special permission bits and device/FIFO/sparse entries fail
closed. Default cap is 100 GiB per archive, configurable up to 1 TiB; validation
also caps entries at one million. Reserve staging disk for decrypted restore data.
Use an encrypted local filesystem/swap and authenticated encrypted off-host transfer.

## Restore

Use the same command with `restore`, a different explicit fresh project/env file,
and the existing backup directory. First prepare configuration only, not `start`
or `initialize`. Reuse exact source image IDs/OS/architecture and original external
secret/config bytes. Bind targets must be different, existing empty directories.
No target containers or volumes may exist. All source owners must remain stopped.
Do not run source and restored physical controllers together.

`verify` authenticates and validates archives without Docker mutation. `restore`
validates every archive before creating any volume. It then starts only the three
stores, checks readiness/schema and report receipt/bytes through Report ownership,
compares inventory checkpoint counts, invalidates bounded `auth:session:*` families,
and removes only the API realtime lease. Durable streams/jobs/evidence remain.
This is an exact-version cold restore, not a cross-platform or cross-version export.

Failure leaves partial fresh targets for explicit investigation, never removes
resources or automatically resumes services. Successful restore also leaves all
application writers/gateway/lab stopped. Review the recorded image/configuration,
reconcile durable jobs and bindings, then explicitly start the approved services
without initialization/migration. A new login, download with original report hash,
and persisted workflow/telemetry checks are still required for live acceptance.
Do not call an unmarked `manage.py start` on restored volumes: its initialization
path belongs only to empty deployments. The parent package owns resume integration.

## Retention And Diagnostics

```sh
python3 deploy/retention.py --project nanfo-deploy-source \
  --compose-file deploy/compose.yaml --env-file /protected/source/deployment.env \
  --grace-hours 24 --batch-size 100 --telemetry-days 30
python3 deploy/diagnostics.py --project nanfo-deploy-source \
  --compose-file deploy/compose.yaml --env-file /protected/source/deployment.env
```

Retention is dry-run by default and requires stopped application/lab writers with
stores available. Inspect the dry-run before adding `--apply --backup-manifest
/protected/backups/checkpoint/manifest.json --encryption-key-file /protected/keys/backup.key`.
Apply requires an authenticated same-project backup less than 24 hours old. Report
ownership verifies current receipts, refuses any active/legacy job, and pins every
registered filename before bounded descriptor-relative cleanup of canonical
UUID-UUID CSV/PDF attempt files at least 24 hours old. Symlinks, hardlinks, unknown
names, recent files and uncertain inventories are never cleanup candidates.

Telemetry retention is assessment-only and reports a bounded aged-row count.
Deletion is BLOCKED until every evidence owner supplies complete reference/pin
contracts. No audits, diagnostics/config/alert histories, models, pending streams
or DLQs are removed. Diagnostics expose dependency/schema state, outbox counts,
bounded queue/pending/idle samples and PostgreSQL size without payloads or secrets.
Redis's package `noeviction` memory cap refuses new writes rather than evict evidence.
These tools do not implement a PostgreSQL/report disk admission cap; operators must
monitor provisioned storage and stop new work before exhausting it.

## Verification Scope

`deploy/tests/test_operations.py` covers isolated crypto, archive safety, strict
resource scope, cold ordering/refusal, fresh restore, bounded session invalidation,
model mount requirements, telemetry assessment and report cleanup protections.
Run with the backend interpreter from the repository root. These tests use no live
Docker resources and do not establish full-stack recovery acceptance; the parent
`deploy/verify.py` campaign owns that verification after package integration.
