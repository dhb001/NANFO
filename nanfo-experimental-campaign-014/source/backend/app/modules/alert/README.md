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
Authority is rechecked using a fresh database session after detector/incident locks
and immediately before commit. The wall clock is sampled at both boundaries;
expiry, revoked membership or disabled actor rolls back observation/state/history/
outbox together, rather than resolving from pre-lock freshness or cached authority.
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
`limit=1..500` (default 200). **`total` and `status_counts` describe the returned
bounded items**, not all matches. Scope predicates run on Alert-owned payload JSON
before ORDER/LIMIT, using live workspace/org/network IDs from owning services.
No cross-module joins. Final access rechecks protect against revocation during
the request. Existing nested scope, workspace-only, network-only and org-only
records remain supported. Unknown/unscoped infrastructure alerts remain denied,
including claimless global Admin; this preserves the existing policy.

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
