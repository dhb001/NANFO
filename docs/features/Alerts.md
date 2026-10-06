# Feature PRD: Alerts

## Purpose
Provide actionable, severity-aware incident alerting across telemetry, simulation, and execution events.

## Business Goal
Reduce detection latency and improve operator response quality.

## Functional Requirements
- Generate alerts from documented thresholds and event triggers.
- Support acknowledge, resolve, and escalation workflows.
- Link alerts to affected objects and correlation identifiers.

## Non-Functional Requirements
- Low-latency propagation to subscribed clients.
- Deterministic severity mapping and deduplication behavior.

## API
- `GET /api/v1/alerts`
- `POST /api/v1/alerts/{id}/ack`
- `POST /api/v1/alerts/{id}/resolve`
- `GET /api/v1/alerts/{id}`
- `GET /api/v1/alerts/{id}/history` - scoped immutable lifecycle evidence (ADR-019).

## Database
- Alert entity with immutable lifecycle history.

## Events
- `alert.generated`, `alert.acknowledged`, `alert.resolved`

## Risks
- Alert fatigue from noisy thresholds.

## Acceptance Criteria
- [ ] Alerts emitted with correlation IDs.
- [ ] Ack/resolve transitions are auditable.

## Tests
- Unit: severity rules, deduplication.
- Integration: event-to-alert pipeline.

## ADR-026 operator filtering and scope

- The Reliability UI submits `status`, `search`, `source`, and `severity` to the
  existing list route. Text filters apply on form submission; status buttons apply
  immediately. The server filters before its bounded limit, so an older active
  incident remains discoverable behind 200 newer resolved records.
- Optional `workspace_id` and `network_id` UUID query parameters narrow current
  owning-service membership and token authority. A selected network must belong
  to the selected/token workspace. Missing filters preserve all-authorized-scope
  behavior for existing API callers. Explicit unauthorized selections return
  403; missing/deleted resources return 404.
- UI requires a selected workspace and uses the selected network when present,
  matching realtime selection. Each alert labels source, organization, workspace
  and network from recorded top-level/nested scope; absent provenance is explicitly
  “not recorded.” Changing identity/organization/workspace/network resets filters
  and expanded details; token rotation preserves drafts.
- `total` and `status_counts` were **returned, filtered-loaded** counts under ADR-026;
  **ADR-028 supersedes this**: both now count every authorized match (exact SQL
  aggregate) while `items` stays bounded by `limit`, and ordering is `updated_at` then
  alert UUID descending. The UI loads at most 200. There is no approved list cursor or
  offset; no history paging endpoint is introduced. Operators refine filters to locate
  older incidents. Existing immutable per-alert history is unchanged.
- Contract: `docs/api/Alerts.md`. Verification/handoff:
  `docs/project/AuditRepair-AlertAudit.md`.

## ADR-028 changes

- Tenancy is stored in Alert-owned `org_id`/`workspace_id`/`network_id` columns
  (migration 0030, backfilled from the payload). Several workspaces bind as one array;
  scope comes from live memberships and the final recheck is batched.
- `search` is at most 200 characters and matches named payload text fields only, never
  the whole serialized payload.
- Telemetry SLO alerts are platform-scoped (`alert_scope: "platform"`). Only a global
  Admin with an unscoped token can list and read them, and they are read-only
  (acknowledge/resolve return 403); `evaluation_window` passes through.
- Poison events are dead-lettered on first delivery (`DeterministicEventError`);
  transient failures stay pending.
- `alert_observations` receipts are purged in bounded batches after
  `ALERT_OBSERVATION_RETENTION_DAYS` (30). Receipts of open incidents, of the current
  window and those named by history are kept.
