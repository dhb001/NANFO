# Feature PRD: Network & Device Inventory

## 1. Purpose
Provide network/workspace-scoped inventory management for logical networks, devices, persisted Digital Twin campus-building metadata, campus model assets, and native network-scoped device groups, while preserving strict C5 tenancy boundaries and canonical API envelopes.

## 2. Requirements
- Manage networks under workspace ownership with claim-aware access enforcement.
- Manage device inventory under a network with deterministic `spatial_ref_id` compatibility for Digital Twin mapping.
- Persist network-owned campus-building geometry/material metadata for Digital Twin campus overlays and synthetic RF attenuation baselines.
- Persist network-owned campus model assets (GLB/GLTF payload metadata + mapping metadata) for deterministic scene reload continuity.
- Manage network-owned device groups (selector + explicit member semantics) for operator targeting workflows.
- Enforce Organization-module workspace membership checks through service boundaries (no cross-module SQL joins).
- Publish network domain events only for documented lifecycle paths used by topology/audit consumers.

## 3. API Endpoints
All endpoints must follow `docs/api/API_STANDARD.md` (`success`, `data`, `meta`, `errors`).

### 3.1 Networks
- `POST /api/v1/networks` — Create network in a workspace.
- `GET /api/v1/networks?workspace_id={uuid}` — List networks for a workspace.
- `PATCH /api/v1/networks/{network_id}` — Edit a nonempty subset of `name`, `description`, `cidr`; return `NetworkResponse`.
- `DELETE /api/v1/networks/{network_id}` — Soft-delete an empty, dependency-free network; return 204.

### 3.2 Devices
- `POST /api/v1/networks/{network_id}/devices` — Create device in network.
- `GET /api/v1/networks/{network_id}/devices` — List devices in network.
- `PATCH /api/v1/networks/{network_id}/devices/{device_id}` — Edit a nonempty subset of `hostname`, `ip_address`, `device_type`, `vendor`, `model`, `location_hint`, `spatial_ref_id`; return `DeviceResponse`. Spatial-only patches remain valid.
- `DELETE /api/v1/networks/{network_id}/devices/{device_id}` — Soft-delete a dependency-free device; return 204.

#### Inventory validation and paging (ADR-026)

Create and PATCH reject unknown fields. Names/hostnames are trimmed, nonempty,
and at most 253 characters. Device types are trimmed, nonempty open vocabulary
up to 64 characters (e.g. `router`, `switch`, `ap`, `host`, `firewall`, `server`,
or an operator-defined type); this preserves existing vendor-neutral inventory.
Vendor/model are nullable trimmed nonempty strings up to 253 characters;
location hints up to 1024, spatial references up to 512. Description is nullable
text up to 4096 characters (empty text is valid). No location is generated.
IP accepts IPv4/IPv6 addresses only, at most 45 input characters; scoped addresses
and prefix suffixes are rejected. CIDR accepts IPv4/IPv6 network notation with an
explicit prefix, at most 49 input characters; host bits and scope IDs are rejected.
Addresses/CIDRs are returned in canonical form. Invalid request values return 422.

In PATCH, omission preserves a field; explicit null clears nullable fields.
`name`, `hostname`, and `device_type` cannot be null. `{}` is invalid. Submitting
unchanged values returns the existing representation without a new event.
Network and device lists use `page` 1..10000 (ADR-028 `PageNumber`), `page_size=1..200` (default 1/20), sorted
by `created_at ASC, primary UUID ASC`, scoped before pagination. Internal service
and repository callers retain batches up to 500. Data remains
`{items,total,page,page_size}`; out-of-range pages return empty items and the total.

#### Authority and deletion restrictions

Reads require `read:topology`, current Organization membership and any token
workspace/org narrowing; mutations require `write:config` and current writable
Organization membership through WorkspaceService. Cross-tenant device IDs return
404 within an authorized network. Soft-deleted resources return 404 on repeat
mutation. Deletion never physically removes historical evidence or rewrites audits.

409 `INVENTORY_DEPENDENCIES_ACTIVE` blocks network deletion with active devices,
campus buildings, campus model assets, device groups, or nonempty spatial objects.
Device deletion is blocked by active group membership, campus asset device mapping,
or current spatial scene association. Replace/remove those active references first;
historical spatial revisions alone do not block deletion.

Both deletion paths conservatively check network-wide Simulation/Intent history
through their owning services. Only completed/cancelled/failed simulations and
rejected/cancelled/compensated intents are safe from summary status alone.
`execution_failed`/`execution_completed` intents require owning Intent detail proving
exact verified rollback or completion of a verified restore plan, respectively.
Uncertain, unverified, merely applied, or mismatched executions remain blocked. Autonomy
must be in monitor mode with no active execution, requested/uncertain cancellation,
or unresolved timed override. The full exact safe-status list is in
`docs/project/AuditRepair-Network.md`. No cross-owner SQL is used.

Parent row locks serialize inventory deletion against spatial associations, asset
mapping, building/group writes and write-authorized workflow creation; durable
outbox writes retain per-network ordering. Mutation and event commit atomically.

### 3.3 Campus Building Persistence (Digital Twin Phase 5D)
- `GET /api/v1/networks/{network_id}/campus/buildings` — List active persisted campus-building records for network.
- `POST /api/v1/networks/{network_id}/campus/buildings` — Upsert campus-building records with optional `replace_existing` soft-replace behavior.

### 3.4 Campus Model Asset Persistence (Digital Twin residual closure)
New `mapping_by_device_id` keys are canonical lowercase hyphenated device UUIDs.
Equivalent UUID spellings with identical trimmed values deduplicate; conflicting
values for equivalent UUIDs reject422. Historical mappings retain their spelling;
deletion compares UUID identity across all active mappings and blocks409 on matching,
malformed or ambiguous historical references. Retirement explicitly removes an
active mapping from dependency checks without rewriting the retained metadata.

- `GET /api/v1/networks/{network_id}/campus/model-assets` — List active persisted campus-model asset records for network. Since ADR-028 C4 (**BREAKING default**) this returns metadata pages by default (`include_data=false`); see §3.6.
- `POST /api/v1/networks/{network_id}/campus/model-assets` — Upsert campus-model asset record with optional `replace_existing` soft-replace behavior. The response is metadata only (ADR-028).
- `GET /api/v1/networks/{network_id}/campus-model-assets/{asset_id}/download` — Verified binary download (ADR-022/027), with a digest ETag and, since ADR-028, 304 support.
- `DELETE /api/v1/networks/{network_id}/campus/model-assets/{asset_id}` — Retire exactly one active metadata row, returning204 with no body. Requires current writable scope and `write:config`. Missing, foreign-network and already-retired assets return404. Retains bytes, hashes, registration, mappings and scene history; retirement never deletes stored bytes. (The ADR-028 collector `python -m app.modules.network.asset_gc` removes only objects that no asset row, active, retired or inline, references.) Retirement removes the row from active lists/downloads and inventory-deletion dependency checks. No new domain event is emitted, consistent with asset upsert.

### 3.5 Device Groups (Network-owned targeting primitive)
- `GET /api/v1/networks/{network_id}/device-groups` — List active network-scoped device groups and resolved active members.
- `POST /api/v1/networks/{network_id}/device-groups` — Upsert device groups with optional `replace_existing` soft-replace behavior.

### 3.6 ADR-028 contract changes (C4, C8, C13)

Contract index: `docs/api/ADR028-ContractChanges.md`.

- **Campus model assets (C4, BREAKING default).** Lists default to metadata pages
  `{items,total,page,page_size}` (`page` 1..10000, `page_size` 1..100, default 20), without
  `model_data_base64`.
  - `include_data=true` is an explicit opt-in: `page_size <= 10` (else 400
    `CAMPUS_MODEL_ASSET_INLINE_PAGE_TOO_LARGE`), and at most 32 MiB of bodies per page,
    checked from metadata before any body is read (else 400
    `CAMPUS_MODEL_ASSET_INLINE_LIMIT_EXCEEDED`).
  - The upload body limit is 12 MiB.
  - Per-network quotas are counted in the database from active rows:
    `NETWORK_ASSET_NETWORK_MAX_ACTIVE_BYTES` (256 MiB) and
    `NETWORK_ASSET_NETWORK_MAX_ACTIVE_ASSETS` (64). They and the global store caps return
    507 `CAMPUS_MODEL_ASSET_QUOTA_EXCEEDED`.
  - Downloads send `ETag: "sha256:<hex>"` and answer a matching `If-None-Match` with 304.
  - `NETWORK_ASSET_*` settings are read from the process environment only.
- **Device groups (C8).** Each upsert item may carry `expected_updated_at` (ISO-8601 with
  a UTC offset, copied from the listed `updated_at`). A changed or missing active group
  returns 409 `DEVICE_GROUP_CONFLICT`. Responses always carry the real `updated_at`.
  Device-type selectors use the shared device-type normaliser.
- **Campus buildings.** Buildings are upserted in place under the inventory lock.
  Migration 0030 enforces one active row per `(network_id, building_id)`; older duplicate
  active rows were soft-deleted.
- **Deletion.** Network deletion is also blocked (409 `INVENTORY_DEPENDENCIES_ACTIVE`)
  while an autonomous execution of the network is unreleased. A verified execution stays
  unreleased because its policy is still applied on the device. Owner answers come from
  the read-only `{simulation,intent,autonomy}/queries.py` functions.
- **Topology.** Deleted devices are excluded from every graph query and lose their edges.
  Neighbour and impact traversal is a bounded breadth-first walk. Reconcile
  (`POST /api/v1/topology/reconcile`) resynchronises Neo4j from PostgreSQL and adds
  `active_devices`, `upserted_nodes`, `tombstoned_nodes`, `skipped_newer_nodes` and
  `watermark_sequence`.
- **Public owner reads for other modules.**
  - `NetworkService.get_device_for_owner(...)`;
  - `NetworkService.get_devices_for_owner(...)` (up to 1000 IDs);
  - `NetworkService.has_active_networks(workspace_id=, actor_user_id=)`;
  - `app.modules.network.emulation.build_emulation_discovery(...)`.
  All authorize through the single `NetworkAccessGuard`.

## 4. Data Model & Ownership
Network module owns:

| Table | Purpose | Notes |
|:--|:--|:--|
| `networks` | Workspace-scoped logical network metadata | `workspace_id` is a logical reference (no FK to Organization tables). |
| `devices` | Network-scoped device inventory | Includes optional `spatial_ref_id` for Digital Twin mapping. |
| `campus_buildings` | Network-scoped persisted campus-building geometry/material metadata | Includes `geometry`, dimensions, `footprint`, `wall_material`, `attenuation_db`, and `source`. |
| `campus_model_assets` | Network-scoped persisted campus model asset metadata | Includes `model_file_name`, `model_mime_type`, payload integrity fields, optional source metadata, and mapping by device id. |
| `device_groups` | Network-scoped group definitions | Includes normalized `group_key`, `group_type`, optional description, and selector metadata. |
| `device_group_members` | Network-scoped group membership edges | Tracks explicit active device memberships for each group with soft-delete lifecycle semantics. |

Cross-module rule: workspace/org access is validated via Organization service APIs only (ADR-004 / C5).

## 5. Event Contracts
Event envelope rules are governed by `docs/api/EventAPI.md`.

| Event Type | Producer Path | Consumer(s) | Payload Highlights |
|:--|:--|:--|:--|
| `network.network.created` | network create flow | Audit consumer | `network_id`, `workspace_id`, `org_id`, `name`, `actor_id` |
| `network.network.updated` | network PATCH | Audit consumer | `network_id`, `workspace_id`, `org_id`, `changed_fields`, `actor_id` |
| `network.network.deleted` | network DELETE | Audit consumer | `network_id`, `workspace_id`, `org_id`, `actor_id` |
| `network.device.added` | device create flow | Audit, topology, ws-push | `device_id`, `network_id`, `workspace_id`, `org_id`, `hostname`, `ip_address`, `device_type`, `spatial_ref_id`, `actor_id` |
| `network.device.updated` | device PATCH | Audit, topology, ws-push | `device_id`, `network_id`, `workspace_id`, `org_id`, `changed_fields`, `actor_id` |
| `network.device.deleted` | device DELETE | Audit, topology, ws-push | `device_id`, `network_id`, `workspace_id`, `org_id`, `actor_id` |

All six inventory events use the existing durable Network outbox and `stream:network`.
`org_id` is resolved from the authorized WorkspaceService response, never a client
payload or assumed token claim. Update `changed_fields` contains only effective
changed fields with their new values, including explicit nulls. Neo4j and websocket
device deltas retain hostname/type/IP/vendor/model/location/spatial changes. Existing
events and historical audits without org scope are preserved; no backfill is implicit.

Campus-building/model-asset/group persistence currently does not publish dedicated domain events; state is read through the documented REST surfaces above. Since ADR-028 these writes append audit-only actions with the org id (`network.campus_model_asset.uploaded`, `network.campus_model_asset.retired`, `network.campus_buildings.upserted`, `network.device_groups.upserted`, and the existing `network.spatial_scene.replaced`). These are not bus events.

ADR-028 C13: every inventory event payload also carries `sequence` (the per-network outbox sequence). Consumers order by `(network_id, sequence)` and fall back to the timestamp for older events (`docs/api/EventAPI.md` §6).

## 6. Risks
- Tenant leakage if workspace/org claim checks are bypassed in network-scoped flows.
- Invalid footprint/material input can degrade Digital Twin overlays if validation is weakened.
- Invalid model payload integrity (`size`/`sha256`/base64) or stale mapping device references can corrupt model-to-device continuity.
- Group selector misuse can produce unexpected membership sets if conventions drift from inventory metadata.
- Campus-building geometry remains operator-imported metadata and is not authoritative BIM/physics output.

## 7. Acceptance Criteria
- [ ] All network/device/campus-building endpoints return canonical API envelopes and status codes.
- [ ] All campus-model-asset and device-group endpoints return canonical API envelopes and status codes.
- [ ] Workspace/org claim mismatches are denied with deterministic `403 Insufficient permissions.` responses.
- [ ] Invalid campus-building payloads (geometry, footprint, attenuation bounds) fail validation with 422.
- [ ] Invalid campus-model payloads (mime/type/sha/size/base64 integrity and mapping device scope) fail validation with 422.
- [ ] Device group upsert/list flows persist deterministic group definitions and active member resolution under network scope.
- [ ] Device spatial updates keep `spatial_ref_id` compatibility and emit `network.device.updated` with `changed_fields`.
- [ ] Campus-building upsert/list persists and returns deterministic records under network scope.

## 8. Testing Requirements
- Add/maintain unit tests for network/device/campus-building service validation and fail-open behavior where applicable.
- Add/maintain unit tests for campus-model-asset and device-group schema/service validation (payload integrity, mapping device scope, selector/member semantics).
- Add/maintain integration tests for network endpoints, auth scope handling, and canonical envelopes.
- Add/maintain regression tests for campus-building/campus-model-asset/device-group persistence payload validation and list/upsert behavior.
