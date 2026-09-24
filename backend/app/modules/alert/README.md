# ADR019 Measured Alerts

Review-blocker verification: full backend **2,054 passed,58 opt-in skipped**;
focused106 passed including31 disposable PostgreSQL cases. Nine lock-barrier cases
cover expiry/membership revocation/actor disable at detector lock, incident lock,
and precommit. Legacy tests cover concurrent suppression receipts, two tenants
sharing a key, scoped recovery, changed-content replay and replay after resolution.
Scoped Ruff/whitespace passed; owned test database removed. Live verifier invocation
was blocked by the parent campaign lock before resources or traffic were created.

Alert owns migration `0018`, directly after Report's `0017`. It adds
`alerts.detector_key`, `alert_detector_states`, `alert_observations`,
`alert_history`, and `alert_outbox`. No shared services are migrated by the tests.
The unreleased0018 also owns `alert_consumed_events`: every valid legacy generation
has a durable first-delivery receipt and incident link, even when suppressed by an
existing incident. Identical and changed-content event-ID replays are no-ops after
resolution; first-delivery content hashes are never replaced.
The unique partial incident index permits one unresolved incident per detector;
acknowledged incidents still occupy that slot. History UPDATE/DELETE is rejected
by a PostgreSQL trigger. Historical alerts are not backfilled with invented history.

## Detector Contract

| Persisted Metric | Unit | Breach | Recovery | Required Measurement Method |
| --- | --- | --- | --- | --- |
| `link_utilization_percent` | `%` | `>= 85` | `< 70` | `openflow_port_counter_delta` |
| `latency_ms` | `ms` | `>= 100` | `< 70` | `ping_rtt`, `latency_semantics=RTT` |
| `packet_loss_percent` | `%` | `>= 2` | `< 1` | `ping_probe`, `loss_semantics=probe` |
| `queue_backlog_packets` | `packets` | `>= 80` | `< 40` | `linux_qdisc_backlog` |

Both breach and recovery require **at least 3 distinct ordered samples spanning
at least 10 seconds**. A gap **greater than 10 seconds** resets the window; exactly
10 seconds is allowed. This is elapsed observation time, not sample count alone
or a requirement that each measurement interval last 10 seconds. The first sample
counts at its observation timestamp. Between-threshold samples reset the window.
Data older than 30 seconds or ahead of the detector clock is ignored; accepted
timestamps must strictly increase. Duplicate event IDs are persisted and ignored.
No missing-data timer resolves incidents. No automatic severity escalation is added;
these rules generate `warning` incidents.

Only persisted, finite, nonnegative, explicitly measured emulation observations
qualify: `source=emulation`, `tags.synthetic=false` (a boolean, not a string),
`execution_mode=emulation`, `quality=measured`, `freshness=fresh`, known unit/method,
and a valid `run_id`. Utilization needs measured rate, positive interval and bound
capacity; queue packets must be integral. Probe loss is 0..100 percent. Bytes are
not silently treated as packets, ratios are not silently treated as percentages,
and RTT is not presented as one-way latency.

Identity includes organization, workspace, network, device, port or peer, run,
metric, source and operator rule version. Different runs cannot recover previous
run incidents. Such incidents stay unresolved until authorized manual resolution.
Acknowledgement does not interrupt measured recovery. Manual resolution resets the
detector window on the next accepted sample and cannot be undone by delayed events.

Rules are fixed, not trained or adapted from observations. Configure process
environment JSON `ALERT_UTILIZATION`, `ALERT_LATENCY`, `ALERT_LOSS`, `ALERT_QUEUE`.
Defaults use `version=operator-v1`. Example:

```sh
export ALERT_UTILIZATION='{"version":"site-v2","breach":90,"recover":65,"min_samples":3,"duration_seconds":10,"max_gap_seconds":10,"max_age_seconds":30}'
```

Omitted optional rule fields retain defaults. A changed rule with the same
persisted identity/version is rejected, not silently retuned. A new version creates
a separate detector; operators must explicitly resolve old-version incidents.
Environment changes require process restart. There is no rule-edit REST endpoint.

## Integration And Authority

`handle_telemetry_event` calls Alert's `handle_persisted_metric_event` only after
Telemetry persistence succeeds, including duplicate delivery after a previous
partial failure. Alert's public `MeasuredAlertService.ingest_persisted_event(event)`
treats the event as a locator and re-reads exact-time device history through
`TelemetryQueryService.get_device_history`, matching the persisted event ID. It
does not use a replay's altered value as evidence. The lookup is bounded to 500
same-metric/device/timestamp records; an identity not found in that bounded result
fails closed. No direct cross-module SQL or repository access is used.

The current operator-owned binding is loaded by Network's `load_binding` contract.
ADR-028: the parsed binding is cached for 5 s per file revision (device, inode,
size, mtime, ctime) and the pre-lock authority answer for 5 s per (revision, actor,
network, workspace, devices); an unobservable binding file is never cached. The
pre-lock check only screens and supplies the organization for the detector
identity. The authoritative decision is **one** fresh-session authorization
immediately before every commit (including the duplicate-observation commit),
together with the wall clock; the clock is also re-sampled right after the
detector/incident locks, where expiry rolls back without authority I/O. Expiry,
revoked membership or disabled actor rolls back observation/state/history/outbox
together, rather than resolving from pre-lock freshness or cached authority.
Network/device/port/capacity/peer must match it. Its actor must remain active with
`read:telemetry`, `read:topology`, `write:config`, and current writable organization
membership. Network/Organization public services verify current resource scope;
Device's public inventory list verifies active device and probe peer. The backend
must have `EXECUTION_MODE=emulation`, `EMULATION_BINDING_PATH` and
`EMULATION_SNAPSHOT_PATH` configured. The detector never launches a collector or
opens the lab for control. Production-measured ingestion is not claimed.

The existing emulation collector remains the live source. Tests use measured-typed
fixtures and an injected clock, not real measured captures. The acceptance campaign
must separately run the collector and demonstrate sustained load and recovery.
No AI, frontend, report, plugin or emulation implementation is owned by this slice.

## Worker And Transactions

Detection/state, alert transition, immutable history and lifecycle outbox commit
together. Ack/resolve lock the incident before authorizing/transacting. Acknowledging
an already acknowledged incident or resolving an already resolved incident is a
replay; acknowledgement after resolution returns 409. Delayed lifecycle events
cannot modify measured incidents. Legacy external lifecycle transitions must match
all existing scope dimensions and not predate generation.
Legacy generation suppression and key-only recovery now query the same normalized
org/workspace/network/device/port/peer/run/rule identity in Alert-owned JSON. A
transaction advisory lock serializes legacy generation for that exact identity.
Unknown-scope legacy events cannot select a measured incident. Nested and top-level
scope conflicts are rejected; rules are compared as JSON, not serialized key order.
Detector keys, legacy identity locks and first-delivery payload hashes use
`detector.nan_tolerant_identity_sha256`, deliberately not `app.core.canonical`
(legacy payloads may carry NaN/Infinity; persisted keys keep their exact bytes).

Correlation (ADR-028): ack/resolve request ids and inbound event correlation ids
use `app.core.correlation.normalize_audit_correlation` (UUIDs unchanged, opaque ids
map deterministically by UUIDv5, never a random UUID). An opaque or non-canonical
original is kept as `request_id` in that transition's immutable history/event
payload only, never merged into the alert's current payload.

Run from `backend`, with the application's configured PostgreSQL and Redis settings:

```sh
poetry run alembic -c alembic/alembic.ini upgrade 0018
PYTHONPATH=. poetry run python scripts/run_alert_worker.py
PYTHONPATH=. poetry run python scripts/run_alert_worker.py --once
```

Migration requires explicit operator approval on any non-disposable database.
The separate lightweight outbox worker drains at most 32 events per iteration;
`--once` performs one bounded drain. Redis publication is bounded to 5 seconds.
An Alert-specific transaction advisory lock serializes publishers so an incident's
generated/acknowledged/resolved messages are delivered in lifecycle order. Worker
failure before DB commit leaves the row pending; retry uses the **same event ID**.
The existing Identity audit consumer deduplicates that ID. Delivery is at-least-once,
not exactly-once. Consumers must tolerate duplicate messages. No heavy work occurs
in HTTP or shared event handlers, and no extra main mounts are necessary.

## Frontend Handoff

All routes use the existing JSON envelope `{success,data,meta,errors}`. Permissions
and current memberships apply; JWT workspace/org scope only narrows access.
No frontend files were changed by this slice.

| Route | Permission | Data |
| --- | --- | --- |
| `GET /api/v1/alerts` | `read:telemetry` | Existing `AlertListResponse` |
| `GET /api/v1/alerts/{id}` | `read:telemetry` | `AlertRecordResponse` |
| `GET /api/v1/alerts/{id}/history` | `read:telemetry` | `AlertHistoryResponse` |
| `POST /api/v1/alerts/{id}/ack` | `write:config` plus current writable membership | `AlertActionResponse` |
| `POST /api/v1/alerts/{id}/resolve` | `write:config` plus current writable membership | `AlertActionResponse` |

Lists preserve `status`, `severity`, `source`, `correlation_id`, `search`, and
`limit=1..500` (default 200). ADR-028 (**semantics change**): `total` and
`status_counts` count **every** authorized match of the filters (exact SQL
aggregate), while `items` stays bounded by `limit`; rows the final recheck removes
from the page are subtracted and no count is ever below the returned items.

Tenancy lives in Alert-owned `alerts.org_id/workspace_id/network_id` columns
(migration 0030, backfilled from the payload), written on create and every
transition from the recorded scope (top-level value first, else nested `scope`;
all NULL when any present value is not a UUID). The list query runs two ordered,
limited branches merged by `UNION ALL`: the workspace-column branch (one workspace
is an equality served by `(workspace_id, updated_at DESC, alert_id DESC)`; several
bind as ONE array, `workspace_id = ANY(:ids)`, paired per organization with
`org_id IS NULL OR org_id = :org`, so statement text never depends on how many
workspaces a user has) and rows without a
workspace column (legacy network-only rows via their resolved networks, org-only
rows, and the historical JSON predicate only for rows whose columns are all NULL).
Rows sort by `updated_at DESC, alert_id DESC` (the index order; `created_at` is no
longer a tie-breaker). Scope comes from live owner memberships with O(organizations)
owner calls (one when narrowed) plus, only when legacy network-only rows exist, one
owner check per distinct legacy network (or one network listing per authorized
workspace when cheaper) — never per row. The final recheck is batched: one fresh
live-membership read, one Network listing per distinct recorded workspace whose
rows carry a network (a row's network must still exist inside its recorded,
authorized workspace), then an exact in-memory check of each recorded payload
scope. Detail/history/ack/resolve keep their per-record owner checks.

`search` is at most 200 characters (422 at the API), trimmed, matched as a literal
case-insensitive substring (`%`, `_`, `\` escaped) over `alert_key`, `source`, the
correlation UUID and the payload text fields `message`, `title`, `metric`,
`device_id`, `peer_host`, `severity_reason`, `runbook_playbook`,
`resolution_reason`, `measurement_method` — never the whole serialized payload.
No cross-module joins. Existing nested scope, workspace-only, network-only and
org-only records remain supported. Unknown/unscoped infrastructure alerts remain
denied, including claimless global Admin; this preserves the existing policy.

Platform-scoped alerts (ADR-028, Telemetry runtime-adapter SLO alerts): a payload
with top-level `alert_scope: "platform"` and no recorded workspace is never
tenant-visible — not even to members of an organization the payload may name.
Only a global Admin (live Identity role `Admin`) using a token without org or
workspace claims lists them (and only when no `workspace_id`/`network_id`
selection narrows the list) and reads their detail/history. They are read-only:
their lifecycle belongs to the SLO evaluator (`alert.generated`/`alert.resolved`),
so acknowledge/resolve answer 403 for every caller. The payload, including
`evaluation_window`, passes through unchanged. Report sources never include them.
Platform rows are not enumerated as tenant evidence by
`measured.telemetry_reference_page` (the owner guard refuses unscoped telemetry
identities, so they cannot hold tenant evidence).

Event consumers (ADR-028 C14, `app/events/consumers/alert_consumer.py`): poison
events raise `DeterministicEventError` and are dead-lettered on the first delivery
— a non-object payload, an invalid/conflicting recorded scope, a generation without
an event id (`AlertEventRejected` reasons `payload_not_object`,
`invalid_alert_scope`, `missing_event_id`), or a 4xx owner answer about the event's
own identifiers. Transient failures (PostgreSQL/Redis outages, timeouts, uniqueness
races, 408/425/429/5xx owner answers) propagate and stay pending for reclaim.
Well-formed events that do not apply (non-measured telemetry, Alert's own measured
echoes, lifecycle for another scope) are acknowledged and ignored. The measured
locator maps opaque correlation ids with `app.core.correlation.correlation_uuid`.

Observation-receipt retention (ADR-028): `alert_observations` gains one row per
accepted sample. `python -m scripts.run_alert_worker` (not `--once`) runs
`app.modules.alert.retention.ObservationRetention` at most every
`ALERT_OBSERVATION_PURGE_INTERVAL_SECONDS` (300): up to
`ALERT_OBSERVATION_PURGE_MAX_BATCHES` (10) committed batches of
`ALERT_OBSERVATION_PURGE_BATCH_SIZE` (1000) receipts older than
`ALERT_OBSERVATION_RETENTION_DAYS` (30; `0` disables) are deleted, except receipts
of a detector with an unresolved incident, receipts inside the detector's current
phase run, and receipts named by incident history (`observation_event_id`). No
sample can be applied twice after its receipt is purged (rules reject samples
older than `max_age_seconds` <= 300 s first). Telemetry pins taken when a sample
was applied are not released. Settings are read with `getattr` and clamped.

ADR026 adds optional `workspace_id`/`network_id` UUID list filters. Selection is
checked through current owning services and cannot broaden JWT claims. Network
selection excludes non-network records and is applied before LIMIT; workspace
selection uses the existing narrowed authorization scopes. No filters retains
all-authorized semantics. Ordering adds descending alert UUID as a deterministic
tie-breaker. No pagination cursor/offset or new lifecycle endpoint is added.
Canonical query contract: `docs/api/Alerts.md`.

`AlertRecordResponse` retains `alert_id`, `alert_key`, `source`, `status`, `severity`,
`correlation_id`, `payload`, acknowledged/resolved actor IDs and timestamps,
`created_at`, `updated_at`. New measured `payload` fields include:

```typescript
type MeasuredAlertEvidence = {
  org_id: string; workspace_id: string; network_id: string; device_id: string;
  port_no: number | null; peer_host: string | null; run_id: string;
  metric: string; source: 'emulation'; rule_version: string; detector_key: string;
  synthetic: false; execution_mode: 'emulation'; quality: 'measured';
  rule: { version: string; breach: number; recover: number; min_samples: number;
    duration_seconds: number; max_gap_seconds: number; max_age_seconds: number };
  observation_event_id: string; observed_at: string; value: number; unit: string;
  measurement_method: string; sample_count: number; window_started_at: string;
  resolution_reason?: 'measured_recovery';
};
type AlertHistoryResponse = {
  alert_id: string; total: number;
  items: Array<{ event_id: string; alert_id: string;
    event_type: 'alert.generated' | 'alert.acknowledged' | 'alert.resolved';
    correlation_id: string; occurred_at: string; payload: Record<string, unknown> }>;
};
```

History is chronological, with full immutable transition payloads. Empty history
on a historical alert means no recorded history, not a fabricated generation.
Actual new ack/resolve responses have `queue_status=deferred`,
`warning=event_delivery_pending`, `stream_entry_id=null` while the durable worker
delivers them. The **state is already committed**, not failed. Repeats retain
`queue_status=replayed`, `idempotent_replay=true`. Existing `alert.generated`,
`alert.acknowledged`, `alert.resolved` events and `/ws/alerts` carry the same evidence;
no new event names are introduced. Refetch scoped detail/history after reconnect.

## Verification

Use a disposable PostgreSQL DSN only:

```sh
ALERT_TEST_DSN=postgresql+asyncpg://USER@HOST:PORT/DATABASE poetry run pytest tests/integration/test_alert_postgres.py -q
poetry run pytest tests/unit/test_alert_detector.py tests/unit/test_alert_service.py tests/integration/test_alerts_endpoints.py -q
poetry run pytest tests -q
```

Tests exercise the actual migration chain through0018, persisted consumer fixtures,
current binding owner membership, threshold/duration/gaps/stale/nonfinite/units,
deduplication/order/run separation, concurrent generation, unique incident index,
ack/resolve versus recovery, rollback and immutable history, outbox disconnect after
publication/retry/audit event-ID deduplication, and scope-before-limit isolation.
They do not attest a live lab metric capture, physical acceptance, or worker
deployment. See the task handoff for the final aggregate test results and any
concurrent-workstream failures.

Latest verification (2026-09-12): focused gate **106 passed**, including **20**
disposable PostgreSQL cases. Full backend **2,017 passed, 58 opt-in skipped** with
`ALERT_TEST_DSN` configured; scoped Ruff and `git diff --check` passed. Earlier
report-workstream failures were corrected by that workstream before the latest
full run. No full-repository lint or live physical acceptance claim is made.

Step13 live verifier preparation is now available in
`backend/scripts/verify_measured_alerts.py`; exact parent admission/command and
evidence contract are in `backend/scripts/VERIFY_MEASURED_ALERTS.md`. It uses actual
iperf/OpenFlow sources and migrations0019 in isolated services, not measured-typed
fixtures. It has **not been live-run**: parent campaign slot release is mandatory.
