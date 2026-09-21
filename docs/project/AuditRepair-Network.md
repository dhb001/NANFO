# ADR-026 Network workstream handoff

## P2 mapping UUID identity repair

- New asset mappings parse device keys as UUIDs and persist canonical lowercase
  hyphenated spelling. Equivalent uppercase/compact/braced/URN keys with equal
  trimmed values collapse into one mapping; conflicting equivalent keys reject422
  before persistence. Invalid UUIDs reject at the request schema boundary.
- Deletion retains the fast canonical-key check, then inspects all active assets
  in200-row UUID-keyset pages using read-only normalization. Historical valid UUID
  spellings block the same device. Malformed or conflicting historical mappings
  fail closed with409; retire/correct the active record explicitly to resolve them.
  No SQL cast of historical JSON keys, migration, historical rewrite or blob change.
- Real PostgreSQL tests seed uppercase, compact, braced, invalid and conflicting
  historical mappings: device delete returns409, leaves the device and original
  mapping unchanged and creates no outbox event; after explicit asset retirement
  deletion succeeds and original mapping remains retained. A separate persistence
  test verifies canonicalization of new keys and conflicting-alias rejection.
- PostgreSQL targeted inventory/outbox run: **19 passed**, isolated instance
  children reaped, private tree removed and ports closed. Final inventory/asset/
  spatial/projection/emulation unit and endpoint run: **538 passed**. Scoped Ruff
  and whitespace checks passed. Changes confined to Network code, relevant tests
  and Network-owned documentation; no migration or commit.

Status: implemented and targeted verification passed (2026-09-20).

## Cross-workstream coordination

### Asset retirement contract (ADR026 completion, implemented and verified)

- `DELETE /api/v1/networks/{network_id}/campus/model-assets/{asset_id}`.
- No body. Success204, empty response. Requires `write:config`, current writable
  Organization membership and optional org/workspace token narrowing.
- `asset_id` is the existing `campus_model_asset_id` UUID, scoped to `network_id`.
  Missing, foreign-network, or already-retired asset returns404. Authority denial403;
  malformed UUID422. Errors retain the canonical envelope.
- Soft-retire only the selected active metadata row. Retain bytes, hashes,
  registration, device mapping and scene history; no blob deletion/garbage collection.
  Retired rows disappear from active list/download and no longer block inventory
  deletion. Other active assets and current scene associations remain authoritative.
- UI handoff: refresh asset list after204; clear local restored asset state only
  if it corresponds to this exact selected identity. No new asset lifecycle event
  is introduced (matching existing asset upsert event behavior).

- Audit owner handoff (verified in the shared worktree): route `network.network.updated`, `network.network.deleted`, and
  `network.device.deleted` to the existing deduplicated audit append handler.
  All future inventory lifecycle payloads carry authoritative `org_id`,
  `workspace_id`, `network_id`, and `actor_id`; device events also carry `device_id`.
  Updates carry exact changed values in `changed_fields`. Network owner does not
  edit `audit_consumer.py`. Historical events/audits are not rewritten.
- Simulation/Intent integration: Network uses the new owner `HistoryService.list_page`
  contracts to check dependencies, conservatively network-wide for device deletion.
  No additional foreign-module method is required. Nonterminal simulations block;
  intents are conservatively blocked unless rejected/cancelled/compensated (a
  completed execution may still require compensation). Completed/failed summary
  statuses now additionally consult owning Intent detail as specified below. Autonomy uses its existing
  public snapshot service to reject active mode, execution, uncertain cancellation,
  or unresolved timed overrides. No cross-module SQL is used.
- No new migration is planned. Existing soft-delete columns and Network outbox
  carry mutations atomically.

## Exact HTTP schema

All URLs below are under `/api/v1/networks`. Existing success/error envelopes
remain; DELETE is 204 with an empty body. Validation is 422, permission denial 403,
missing/deleted inventory 404, active dependency conflict 409 with code
`INVENTORY_DEPENDENCIES_ACTIVE`.

| Method/path | Request | Success data |
|---|---|---|
| POST `/` | `{workspace_id: UUID, name: string, description?: string|null, cidr?: string|null}` | NetworkResponse, 201 |
| PATCH `/{network_id}` | Nonempty subset `{name,description,cidr}` | NetworkResponse, 200 |
| DELETE `/{network_id}` | No body | Empty, 204 |
| POST `/{network_id}/devices` | `{hostname: string, device_type: string, ip_address?: string|null, vendor?: string|null, model?: string|null, location_hint?: string|null, spatial_ref_id?: string|null}` | DeviceResponse, 201 |
| PATCH `/{network_id}/devices/{device_id}` | Nonempty subset of device create fields | DeviceResponse, 200 |
| DELETE `/{network_id}/devices/{device_id}` | No body | Empty, 204 |
| DELETE `/{network_id}/campus/model-assets/{asset_id}` | No body; asset_id is campus_model_asset_id | Empty, 204 |
| GET `/?workspace_id=UUID` and `/{network_id}/devices` | `page=1`, `page_size=20`; page>=1, size1..200 | `{items,total,page,page_size}`, 200 |

NetworkResponse: `{network_id,workspace_id,name,description,cidr,created_at}`.
DeviceResponse: `{device_id,network_id,hostname,ip_address,device_type,vendor,model,
location_hint,spatial_ref_id,status,created_at}`. IDs are UUID strings; timestamps
are ISO8601. Optional inventory fields above are always present and nullable in
responses. Page ordering is `created_at ASC, primary UUID ASC`; internal page sizes
up to500 remain accepted. Tenant filtering precedes count and pagination.

Names/hostnames: trimmed1..253 chars. Type: trimmed1..64, open vendor-neutral
vocabulary (router/switch/ap/host/firewall/server/custom values allowed). Vendor and
model: nullable trimmed1..253. Location hint: nullable trimmed1..1024. Spatial ref:
nullable trimmed1..512. Description: nullable0..4096 chars, untrimmed. IP: IPv4/IPv6
host only, max45 input chars; no CIDR suffix or scoped `%interface`. CIDR: explicit
IPv4/IPv6 prefix with network address (no host bits), max49 chars. IP/CIDR normalize
to canonical strings. Unknown fields, empty PATCH and null required fields reject.
PATCH omission preserves; explicit null clears nullable fields. A no-op emits no
event. Existing `{spatial_ref_id: string|null}` requests continue to work.

Mutations require global `write:config` and Organization-service current writable
membership, with optional claim narrowing. Reads require `read:topology` and current
membership. Inventory writes hold the parent row before child/scene locks and reload
authority after lock waits. Delete rechecks authority after foreign-service checks.

## Exact deletion policy

- Network: block any active device, campus building, campus model asset, device
  group, or nonempty current scene objects. Delete devices explicitly first.
- Device: block active group membership, active asset mapping, or a current scene
  object referencing it. Remove/replace those references first.
- Both: inspect all pages of network-scoped simulation and intent history using
  the owning HistoryService APIs. Safe simulation statuses are exactly `completed`,
  `cancelled`, `failed`. Safe intent statuses are exactly `rejected`, `cancelled`,
  `compensated`, `execution_cancelled`, `execution_compensated`. All other statuses,
  except execution_completed/execution_failed, block conservatively. Those two
  statuses require exact owning Intent detail proof under the completion rules below;
  summaries cannot prove rollback/release of a previously applied configuration.
- Autonomy snapshot must have mode `monitor`, no `active_execution_id`, no
  cancellation status `requested`/`uncertain`, and no `timed_override_unresolved`
  reason. This uses the owning service, without dispatching any action.
- Soft deletion sets deleted_at; device status becomes `deleted`. Current lists and
  lookups exclude these records. Historical audits, outbox messages, simulations,
  intents, scene revisions, and telemetry remain stored. Historical scene references
  alone do not prevent deletion. Repeat deletion returns404.

## Events and projection

All six lifecycle events are in `INVENTORY_EVENTS` and atomically stored alongside
the mutation. Every future payload includes authoritative org/workspace/network/
actor IDs; device events include device ID. `changed_fields` contains exactly changed
new values, including nulls. Neo4j accepts hostname/type/IP/vendor/model/location/
spatial updates, retaining its revision/tombstone protections; websocket updates
preserve the same delta. Added websocket nodes now include IP and spatial reference.
Network update/delete are audit-only; device delete uses existing graph/removal WS
routing. Real PostgreSQL regression verifies audit routing supplied by the audit
owner, duplicate processing yields exactly one row/event, and org-filtered history
remains visible after soft-deleting the parent.

## Verification

- Targeted backend suite: **397 passed** covering existing network/schema/outbox/
  endpoints, new inventory/schema/authority/deletion tests, graph/ws projection,
  and preserved spatial/asset service tests. After adding six dependency-page and
  Autonomy-blocker regressions, the final focused inventory unit run passed
  **58 tests** (overlapping the broader suite; not an additive total).
- Disposable PostgreSQL: **10 passed** (four new inventory regressions plus six
  existing outbox tests), full0028 schema for current-service tests. Tested exact
  IP/type/name/null persistence,41-row deterministic pages and internal500 calls,
  cross-tenant denial, current-role revocation while waiting on an inventory lock,
  deletion conflict, rollback after an outbox flush failure, retained spatial
  history, same-transaction lifecycle events, retry ordering and audit dedup/scope.
- PostgreSQL wrapper: `/tmp/opencode/run_network_inventory_pg.py`, invoking
  `tests/integration/test_network_inventory_postgres.py` and
  `tests/integration/test_network_outbox_postgres.py`. The wrapper created/reaped its
  own PostgreSQL; cleanup confirmed private tree removed and ports closed. Regular
  runs opt in with `NETWORK_OUTBOX_TEST_DSN`; no shared store was migrated.
- Scoped Ruff and `git diff --check` passed. Live Neo4j delivery is not claimed; Cypher parameters and
  websocket payload propagation are covered by transactional-driver/push mocks.
- No commits. No edits to audit_consumer, Identity/Organization, main/deploy,
  frontend, or global tracking by this workstream. Other owners' existing and
  concurrent changes are retained, including full current-schema fixture repair.

## Integrated follow-up: INET regression and deletion usability review

### Fix and verification

- Removed `_authorized_org_id` mutable service-instance state. Network's private
  authorization helper returns `(network, org_id)`; its public
  `assert_network_workspace_access` still returns the network for existing callers.
  Device's private helper returns the same explicit pair. Event writers capture
  org identity locally from the successful authorization result.
- The INET emulation test now mocks the Network repository and Organization service
  boundaries, exercising the actual authorization helper, and asserts the org ID
  as well as JSON-safe IPv4/null payloads. No fallback or fabricated tenant identity.
- Follow-up inventory/emulation suite: **479 passed**, including all five emulation
  test files, inventory/schema/outbox/endpoints, graph/WS, spatial and asset service
  regressions. Disposable inventory/outbox PostgreSQL rerun: **10 passed**, owned
  children reaped, private tree removed and ports closed. Scoped Ruff and whitespace
  checks passed. This does not claim a rerun of the full integrated backend suite.
- No changes to scope-lock behavior, Identity/Organization, measured alert locking,
  frontend implementation or deletion restrictions during this follow-up.

### Independent deletion usability findings (source review)

Historical findings below describe the pre-completion review. The approved asset
retirement and Intent proof fixes are implemented in the completion section below;
Twin owner is implementing group/building empty-replacement controls.

**The current restriction policy is not fully resolvable through the UI.** A409
message telling operators to remove dependencies is insufficient for these cases:

1. **Persisted assets permanently block network deletion under the current public
   contract.** Every active asset blocks, even with no device mapping. The asset
   upsert API requires a valid asset and replacement always leaves an active asset;
   there is no asset delete/clear endpoint. Twin asset persistence uses
   `replace_existing:false` (`TwinPageContent.tsx`, persistImportedModelAsset), and
   the UI has no removal control. Device mapping can be replaced by a newly
   imported sidecar, but older active assets can retain references; non-replace
   persistence updates only the latest matching body or appends another asset.
   Handoff: an approved owner asset-retirement contract or a reviewed network-owned
   cascade policy is needed. Do not delete historical revisions or blob evidence.
2. **Groups have an API escape path but incomplete UI controls.**
   `POST .../device-groups` with `{replace_existing:true,groups:[]}` can clear all
   active groups. `CustomGroupEditor.tsx` always submits `replaceExisting:false`,
   edits only custom groups, and cannot save an empty final membership without a
   selector (the backend per-group schema also rejects that). Removing a member
   works only while the saved definition remains valid, and selectors may re-add
   it. There is no group removal control. Thus a one-device group or noncustom
   group can block device deletion, and any group blocks network deletion, without
   an actionable UI path. Handoff: expose the existing full-replacement contract
   with retained-group review, or obtain approval for targeted deletion.
3. **Persisted campus buildings have an API escape path but no UI clear action.**
   `POST .../campus/buildings` with `{replace_existing:true,buildings:[]}` clears
   active records. `TwinPageContent.tsx` returns early when the imported building
   list is empty, so operators cannot persist that clearing operation in the UI.
4. **Canonical scene references are clearable.** Guided editing provides “Clear
   device association” and “Remove object from draft”; saving the full replacement
   persists those changes. Advanced JSON also permits `objects:[]`. Historical
   scene revisions are intentionally not blockers. Clearing inventory
   `spatial_ref_id` alone does not remove canonical scene associations.
5. **Intent terminal-status mismatch creates a deletion dead end.**
   `intent/execution.py::project_execution` projects every released non-completed
   job—including verified cancellation/compensation—as `execution_failed`.
   The deletion guard blocks that status and accepts cancellation/compensation
   names that this projector does not emit. UI compensation therefore need not
   clear the blocker. Validated-but-unexecuted intents also block while the current
   cancel path requires a durable execution. Handoff: Intent owner should expose a
   deletion-safety query based on authoritative execution/release evidence; do not
   simply whitelist all `execution_failed` or execute work just to unblock deletion.
6. **Simulation clearing is indirect.** Draft/paused simulations block; UI offers
   resume/start but no discard/cancel contract. A successful terminal run clears
   the blocker, but there is no direct abandon action. Autonomy has monitor/stop/
   reconciliation controls; unresolved execution/override restrictions must remain
   until owning-service evidence establishes release.

These are handoff findings, not completed UI/removal capabilities. The conservative
guard preserves evidence but should not be presented as a universally completable
operator deletion workflow until the owner gaps above are resolved.

## ADR026 deletion completion

### Implementation

- Added selected metadata retirement via CampusModelAssetService/repository and
  the exact DELETE contract published at the top of this handoff. Serializes with
  existing asset upserts using the same parent lock, reloads current authority
  after lock waits and after flush, commits soft deletion atomically, rolls back
  failures. No storage read/write/delete is performed. No migration or new event.
- For `execution_failed` and `execution_completed` history entries, Network calls
  `IntentExecutionService.get_intent_detail(workspace_id,intent_id,user_id)`.
  No Intent tables are queried by Network. A detail must match exact intent,
  network and workspace IDs; `manual_lab_v1` provenance must have explicit
  `blocks_lab:false`, `uncertain:false`, and status matching detail.
- Execution/run UUIDs, binding/plan SHA256 digests, timezone-aware approved/completed
  timestamps in order and not in the future, and an owner-valid LabPlan whose
  canonical digest equals `plan_hash` are required. Missing/malformed evidence blocks.
- Failed/cancelled phase with `execution_failed` is released only when Intent's
  `verified_rollback` validates explicit verified readback SHA256. This uses the
  owner projection of its exact fenced/matched execution receipt; bare failure,
  uncertainty, or `verified:true` without a digest cannot release inventory.
- Completed phase with `execution_completed` is released only for the exact
  approved `restore` operation, with Intent's `verified_completion` plus probe
  source/destination matching that approved plan. An ordinary successfully applied
  shape/reroute policy remains blocking. A separate restore record never clears
  an unrelated earlier intent; its own exact dependency needs compensation proof.
- Rejected/unexecuted and simulation policies otherwise retain their prior documented
  behavior. No actuation, cancellation, or fabricated success occurs during deletion.

### Completion verification

- **520 targeted tests passed** across inventory, asset endpoints/service, schema,
  outbox, restoration evidence, graph/WS, spatial, and emulation tests.
- **13 disposable PostgreSQL tests passed**: prior10 plus asset-retirement rollback,
  scoped denial, retained bytes/metadata, removal from active lists and dependency
  checks, and two real owning-Intent-detail compensation/restore deletion flows.
  These use seeded evidence and real services/serialization, not physical execution.
- New unit regressions deny malformed/uncertain/mismatched identity/plan/time/
  rollback evidence and successful ordinary applied policies; validate exact
  compensation and restored-plan paths. Retirement endpoint tests cover204,
  repeated/foreign404, permission/revocation403, malformed UUID422 and retired
  download404. Service tests include revocation after lock/flush and commit failure.
- Scoped Ruff passed. Disposable PostgreSQL cleanup confirmed private tree removed,
  children reaped and ports closed. No frontend, Identity, deployment or global
  tracking changes; no commits.
