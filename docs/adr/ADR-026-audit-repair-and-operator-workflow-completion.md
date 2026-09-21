# ADR-026: Audit Repair and Operator Workflow Completion

- Status: Accepted within the user's explicit 2026-09-20 instruction to implement
  all findings and missing workflows in parallel.
- Source: `docs/project/FrontendBackendAudit-2026-09-20.md`, A01–A17 and capability map.

## Ownership and scope

Preserve modular ownership, current authorization and immutable evidence. Complete
existing workflows and the following additive public contracts. No experimental-lab
public mode, physical actuation expansion, model training or safety-policy change.
Existing uncommitted work is preserved. Migrations, if necessary, start after0028;
prefer existing columns and atomic Identity audit boundary over new schema/workers.

## Approved contract additions

Canonical success/error envelopes apply; deletion returns204. All list pages are
bounded, ordered deterministically, and scoped before pagination. Page>=1;
page_size1..200 for new public lists (existing internal500-page callers may remain).

### Network inventory (Network ownership)

- `PATCH /api/v1/networks/{network_id}` accepts a nonempty subset of
  `{name, description, cidr}`, returns existing NetworkResponse.
- `DELETE /api/v1/networks/{network_id}` soft-deletes inventory. Retains historical
  evidence. Reject409 when owned dependent active resources prevent safe deletion;
  device-containing networks may require devices to be removed explicitly first.
- Existing device PATCH extends to nonempty subsets of `{hostname, ip_address,
  device_type, vendor, model, location_hint, spatial_ref_id}`. Explicit null clears
  nullable fields; omission leaves unchanged. Existing spatial-only requests work.
- `DELETE /api/v1/networks/{network_id}/devices/{device_id}` soft-deletes and publishes
  existing `network.device.deleted`, routed to existing topology removal handling.
- Mutations require write:config and current writable org membership, claims narrowed
  as existing routes. Read access requires read:topology/current membership.
- Inventory event payloads add authoritative `org_id` from Organization service;
  `network.network.updated` and `network.network.deleted` are approved audit events
  carrying network/workspace/org/actor and changed_fields for update.
- Device updates publish existing `network.device.updated` with exact changed_fields;
  consumers retain and map hostname/type/IP changes as well as spatial references.
- No fabricated names/location. Bounded IP/CIDR/nonempty names validated before DB.

Deletion-completion clarification: `DELETE /api/v1/networks/{network_id}/campus/model-assets/{asset_id}`
soft-retires Network-owned active asset metadata (204) with the same writable scope
checks; immutable historical bytes/scene history remain retained. UI confirms the
chosen record, clears restored local state only when appropriate and refreshes the
selection. Existing replace/upsert APIs support explicitly confirmed clearing of
campus buildings and groups; do not add hard deletion/asset garbage collection.
Completed/failed intent dependencies may be released only when the Intent owner's
detail proves exact verified compensation/restoration; summary status alone is not
proof. These additions close dependencies that otherwise made inventory deletion
unreachable for legitimately configured networks.

### Durable history (Simulation and Intent ownership)

- `GET /api/v1/simulations?workspace_id=UUID&network_id=UUID&page=1&page_size=20`
- `GET /api/v1/intents?workspace_id=UUID&network_id=UUID&page=1&page_size=20`
- workspace_id required; network_id optional, verified within that workspace.
  Require read:topology and current scope membership; optional token claims narrow.
- Return data `{items,total,page,page_size}`. Simulation summaries use existing
  `{simulation_id,network_id,workspace_id,scenario_name,status,created_at,updated_at}`;
  Intent summaries use existing `{intent_id,network_id,workspace_id,status,created_at,
  updated_at,intent_payload}` (bounded existing payload) or narrower action field
  documented by owner. Exact adapters follow owner's published schema.
- New routes precede UUID detail routes. Deep links select persisted IDs but never
  auto-approve/execute. List actions load existing detail and lifecycle controls.

### Alert scope and audit query

- Existing GET `/alerts` adds optional workspace_id/network_id UUID filters, verified
  via owning services/current membership and applied before LIMIT. Existing clients
  without those params retain authorized-all-scope semantics. UI explicitly scopes
  selected network/workspace and labels source. Existing status/search filters are
  sent to backend, rather than filtering a truncated unfiltered page.
- Existing audit GET retains actor_id/resource_type/org_id/page/page_size; add optional
  bounded `search` text matching event/correlation/resource identity within org.
  Return existing fields. UI shows actor/resource/metadata and complete pagination.

## Identity, organization and audit repair

Global capability matrix: Admin retains seeded full permissions; Operator gets
read:topology/read:telemetry/write:config/execute:rollback; Read-Only gets only the
two read capabilities. Current org role still restricts writes; org administration
requires org Admin, and global Operator is not platform Admin. This implements the
explicit requested Operator-workflow fix without granting platform Admin privileges.
Test fixtures must reflect the actual backend map. No new permission names.

Member restoration uses transactional conflict-safe reactivation of a soft-deleted
membership, never duplicate insertion. Deleted organization slugs remain reserved;
reuse/conflict returns409. Slugs3..63 characters. Organization lifecycle audit is
committed atomically via Identity's existing append boundary with stable event ID;
best-effort external publication cannot remove that durable record. Audit consumer
deduplicates the same event and uses event-specific actor/resource attribution.
Historical records are never silently rewritten; any recovery uses an explicit
append-only correction record linked to original evidence and verified owner scope.

## UI and verification

Keep drafts/immutable in-flight IDs over token rotation; identity/tenant changes
still reset and authority changes invalidate approvals. Real inventory forms,
organization/workspace edit/delete, paginated selectors, audit details, guided
scene geometry/custom groups and persisted asset selection use approved contracts.
Inputs, failures and ambiguous outcomes are visible; no optimistic execution claim.
Preserve shared atlas design, keyboard accessibility and reduced-motion support.

Require targeted regressions plus full frontend/backend and disposable PostgreSQL
checks. Keep historical0027 release checks distinct from repository migration head.
Do not raise bundle limits to hide feature growth; optimize/split owned code first.
No changes to deployed shared services or privileged lab campaigns in this repair.
