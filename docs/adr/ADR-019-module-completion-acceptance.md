# ADR-019: Reports, Measured Alerts, Registry and Acceptance

- Status: Accepted for user-requested Steps 13 and 14
- Date: 2026-09-11

## Reports

Report owns durable jobs, snapshot/artifacts and lifecycle outbox (migration0017
after0016). A separate bounded worker is approved, following Simulation's I/O-worker
exception; no heavy rendering in HTTP or shared event consumers. Use real standard
CSV and a maintained PDF renderer (pin ReportLab if compatible), checksums/size from
actual bytes. Default storage is protected local filesystem behind authorized
download, not fictitious S3. Deployment may provide object storage later; never
publish a path or URI as evidence bytes exist. Atomic fsync/rename, bounded files,
no symlinks/traversal and content verification on reads. Preserve historical fake
artifact masking; newly versioned actual artifacts only may report generated.

Existing generate/status routes remain. Approve GET `/api/v1/reports?workspace_id`
with bounded pagination/history and GET `/api/v1/reports/{id}/download?workspace_id`
as a binary content exception to JSON envelope, authenticated current membership
and exact artifact identity. Errors retain JSON envelope; filenames safe, CSV
formula injection neutralized, PDF text escaped/handled by renderer. Report source
reads go through owning service contracts (Telemetry/Alert/Simulation/Intent), no
cross-module SQL. Freeze bounded date/scope filters and expose truncation/omissions.
Include actual telemetry, alerts, configured-model simulation outputs and intent
action/evidence records where scoped available; empty/missing sections are explicit.
Requested arbitrary report_type/scope/filters must be validated or rejected, not ignored.
Generation and terminal events commit with outbox; repeatable workers/leases and
idempotency. Recheck authority before generation/download; credentials never artifacts.

## Measured Alerts

Alert owns detector state, tenant/resource/rule identity, observation watermark,
history and outbox (migration0018 after0017). Consume existing telemetry.metric.ingested
only once persisted, via documented Alert public ingestion contract. Rules cover
utilization, RTT, probe loss and queue backlog with known units and source provenance.
Sustained threshold, distinct recovery threshold and duration/hysteresis prevent
storms. Missing, stale, out-of-order, duplicate, unknown-unit or synthetic data must
not resolve a measured incident. Correlate recovery to original alert ID and tenant/
network/device/port/peer/run/rule. Atomic one-active incident and immutable lifecycle
history; ack and recovery races deterministic. Existing alert lifecycle event names
only. GET `/api/v1/alerts/{id}/history` approved with current scoped permissions;
REST lists filter authorized scope before pagination, not after global limit.

## Plugin and Energy Scope

The delivered plugin feature is explicitly a metadata-only registry, not executable
extensions. Validate declaration schema; reject conflicting replay content; label
signature/dependency/sandbox status unverified/not_executed, including historical
overclaims. Existing enable/disable represent registry flags, never package execution.
Approve DELETE `/api/v1/plugins/{id}` for authorized soft-uninstall, preserving audit
history; no plugin.uninstalled event invented, registry removal recorded via existing
audit service contract. Do not add an arbitrary executable/package loader.

Energy remains research estimation only: a bounded pure scenario model may calculate
configured active/idle wattage and link-state alternatives, explicitly estimated,
but cannot claim measured consumption or enforce physical port sleep. If no safe
driver/measurement is installed, power-control acceptance is BLOCKED. Do not shut
ports merely to satisfy a checklist. No wireless or production expansion.

## Acceptance Campaign

Create a resumable-status, explicitly operator-launched campaign with finite stage
timeouts, unique evidence directory, exact owned resource cleanup and serialized
lab use. Run existing measured verifiers plus new reports/alerts/registry tests;
include scenario matrix for low/ramp/burst/overload/multiple bottlenecks, failures,
stale telemetry, disconnection/restart, unsafe proposals, overrides, rollback,
traffic classes and larger configured topology. Label each measured, modeled,
fixture or blocked; no combined green flag when required physical cases are blocked.
Report requested metrics with units, counts/raw references, nullable unavailable
measurements and comparator scope. Reuse historical heldout DRL evidence only as
historical, not a new run. DRL+safety end-to-end remains blocked until providers
and calibrated bounds are installed. No test-set retuning or new training.

## Deployment and Verification

Use migrations0017/0018 on disposable databases first; do not alter shared services
without operator approval. Preserve source, data and existing jobs outside scope.
Frontend displays real downloads/history, provenance, alert history and truthful
registry/energy state with permissions/mobile/error handling. Verify actual PDF/CSV
content, checksum/tamper/tenant denial, worker restart/outbox replay, sustained
network metric detection/recovery and lifecycle races. Full gates plus explicit
scope gaps recorded; no claim all network acceptance is complete when blocked.
