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

### 3.2 Devices
- `POST /api/v1/networks/{network_id}/devices` — Create device in network.
- `GET /api/v1/networks/{network_id}/devices` — List devices in network.
- `PATCH /api/v1/networks/{network_id}/devices/{device_id}` — Update device spatial reference (`spatial_ref_id`).

### 3.3 Campus Building Persistence (Digital Twin Phase 5D)
- `GET /api/v1/networks/{network_id}/campus/buildings` — List active persisted campus-building records for network.
- `POST /api/v1/networks/{network_id}/campus/buildings` — Upsert campus-building records with optional `replace_existing` soft-replace behavior.

### 3.4 Campus Model Asset Persistence (Digital Twin residual closure)
- `GET /api/v1/networks/{network_id}/campus/model-assets` — List active persisted campus-model asset records for network.
- `POST /api/v1/networks/{network_id}/campus/model-assets` — Upsert campus-model asset record with optional `replace_existing` soft-replace behavior.

### 3.5 Device Groups (Network-owned targeting primitive)
- `GET /api/v1/networks/{network_id}/device-groups` — List active network-scoped device groups and resolved active members.
- `POST /api/v1/networks/{network_id}/device-groups` — Upsert device groups with optional `replace_existing` soft-replace behavior.

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
| `network.network.created` | network create flow | Audit consumer | `network_id`, `workspace_id`, `name`, `actor_id` |
| `network.device.added` | device create flow | Audit, topology, ws-push | `device_id`, `network_id`, `workspace_id`, `device_type`, `spatial_ref_id`, `actor_id` |
| `network.device.updated` | device spatial update flow | Audit, topology, ws-push | `device_id`, `network_id`, `workspace_id`, `changed_fields`, `actor_id` |

Campus-building/model-asset/group persistence currently does not publish dedicated domain events; state is read through the documented REST surfaces above.

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
