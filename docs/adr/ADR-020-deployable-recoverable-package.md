# ADR-020: Deployable and Recoverable Application Package

- Status: Accepted for user-requested Step 15
- Date: 2026-09-12

## Package

Add deploy/ full-stack Docker builds and Compose for frontend gateway, one API,
simulation/report/alert/execution/autonomy workers and PostgreSQL/Redis/Neo4j. Pin
base image digests and dependency locks; no source .env/venv/artifacts in image
contexts. Fixed non-root application UID, read-only root, bounded tmpfs/resources/
logs and dropped capabilities. Stores expose no host ports; gateway binds loopback
by default, with TLS/reverse-proxy instructions before nonlocal exposure. Redact
query strings so websocket tokens never appear in access logs. No Docker socket,
host PID/network/filesystem authority in API or workers.

Secrets are explicit protected files with no development fallback. Deployment
entrypoint loads allowlisted secret variables then execs existing service commands;
secret contents never printed. Use distinct migration/admin and runtime DB roles;
runtime cannot migrate/drop schema. Explicit one-shot init/migrate before writers.
Encode credentials correctly in database/Redis DSNs and Alembic interpolation.

Separate opt-in lab overlay/profile retains disconnected privileged container,
operator binding/digest, and separate output/command/result volumes with minimum
read/write mounts. Controls off until explicitly enabled. Optional frozen model
diagnostics need the exact independent AI runtime and read-only artifact registry;
never install backend packages into frozen AI environment. Missing model/calibration
providers remain unavailable. Packaging does not claim Step9/10 activation.

## Readiness and Diagnostics

Keep /health as liveness. Approve GET /ready with canonical envelope and bounded
Postgres query/schema-head, Redis, Neo4j and API lease/consumer checks. 503 on missing
required dependency, no credentials/internal stack traces. Optional lab/model
capabilities explicitly unavailable do not pretend configured-ready. Worker health
uses actual loop progress heartbeat written by loop, not a timer detached from work;
healthcheck probes dependency and heartbeat freshness without performing jobs.
Deployment diagnose command exposes status/outbox/pending age/counts without secrets.

## Backup/Restore

Operator-explicit coordinated maintenance backup. Refuse unresolved physical
execution/override state unless safely restored; no killing recovery to get a dump.
Quiesce application writers, verify consistent boundary; stop stores before cold
backup as appropriate. Preserve PostgreSQL, Neo4j application/system DBs, Redis
durable streams, report files, binding/mailbox/journal, models/registry and exact
manifest/image metadata. No tar of a live database. Hash manifest and validate
bounded safe archive entries before restore. Protected backups include sensitive
data; require encrypted transport/off-host storage; do not include secret plaintext
in reports/logs. Document local encryption if not implemented.

Restore only to newly initialized explicit fresh target volumes/project; never
overwrite existing application deployment. Verify checksums/schema/report receipts
and datastore readiness before opening gateway. Invalidate only auth:session:*
families and safe API liveness lease after confirmed all old owners stopped; do not
FLUSHDB or discard streams/pending jobs. Reconcile durable jobs before enabling lab
control; never replay a physical command into a new run automatically. End-to-end
restore includes a new login, report download and persisted workflow state checks.

## Retention

Explicit bounded operator policy and dry-run before apply. Owner-service retention
may remove aged raw telemetry in bounded batches and proven orphan report attempt
files after grace period/absence of active jobs. Do not delete immutable audits,
alert/config/diagnostic histories, referenced reports/models or active/uncertain
execution/rollback evidence. Do not trim pending streams or unresolved DLQs blindly.
Disk/queue caps refuse new work and expose capacity alerts rather than silently
discard necessary evidence. Retention cannot break required audit/report lineage.

## Verification

Build from empty image environments, boot fresh scoped stores, migrate to0019,
seed only dedicated actor with generated protected credentials, exercise HTTPS or
loopback gateway UI/API/login plus configured simulation/report and actual lab
congestion/readback where supported. Restart API/workers, verify resumed progress,
take maintenance backup, restore into a different fresh stack, invalidate old
sessions, verify same report bytes and persistent state. Never modify original
nanfo_* services, stopped lab or unrelated containers. Track all owned IDs/volumes
and clean only those. Report unsupported optional capabilities honestly.
