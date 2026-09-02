# Feature PRD: Network & Device Inventory

## 1. Purpose
Provide network/workspace-scoped inventory management for logical networks, devices, and persisted Digital Twin campus-building metadata, while preserving strict C5 tenancy boundaries and canonical API envelopes.

## 2. Requirements
- Manage networks under workspace ownership with claim-aware access enforcement.
- Manage device inventory under a network with deterministic `spatial_ref_id` compatibility for Digital Twin mapping.
- Persist network-owned campus-building geometry/material metadata for Digital Twin campus overlays and synthetic RF attenuation baselines.
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

## 4. Data Model & Ownership
Network module owns:

| Table | Purpose | Notes |
|:--|:--|:--|
| `networks` | Workspace-scoped logical network metadata | `workspace_id` is a logical reference (no FK to Organization tables). |
| `devices` | Network-scoped device inventory | Includes optional `spatial_ref_id` for Digital Twin mapping. |
| `campus_buildings` | Network-scoped persisted campus-building geometry/material metadata | Includes `geometry`, dimensions, `footprint`, `wall_material`, `attenuation_db`, and `source`. |

Cross-module rule: workspace/org access is validated via Organization service APIs only (ADR-004 / C5).

## 5. Event Contracts
Event envelope rules are governed by `docs/api/EventAPI.md`.

| Event Type | Producer Path | Consumer(s) | Payload Highlights |
|:--|:--|:--|:--|
| `network.network.created` | network create flow | Audit consumer | `network_id`, `workspace_id`, `name`, `actor_id` |
| `network.device.added` | device create flow | Audit, topology, ws-push | `device_id`, `network_id`, `workspace_id`, `device_type`, `spatial_ref_id`, `actor_id` |
| `network.device.updated` | device spatial update flow | Audit, topology, ws-push | `device_id`, `network_id`, `workspace_id`, `changed_fields`, `actor_id` |

Campus-building persistence currently does not publish a dedicated domain event; state is read through the documented REST surface above.

## 6. Risks
- Tenant leakage if workspace/org claim checks are bypassed in network-scoped flows.
- Invalid footprint/material input can degrade Digital Twin overlays if validation is weakened.
- Campus-building geometry remains operator-imported metadata and is not authoritative BIM/physics output.

## 7. Acceptance Criteria
- [ ] All network/device/campus-building endpoints return canonical API envelopes and status codes.
- [ ] Workspace/org claim mismatches are denied with deterministic `403 Insufficient permissions.` responses.
- [ ] Invalid campus-building payloads (geometry, footprint, attenuation bounds) fail validation with 422.
- [ ] Device spatial updates keep `spatial_ref_id` compatibility and emit `network.device.updated` with `changed_fields`.
- [ ] Campus-building upsert/list persists and returns deterministic records under network scope.

## 8. Testing Requirements
- Add/maintain unit tests for network/device/campus-building service validation and fail-open behavior where applicable.
- Add/maintain integration tests for network endpoints, auth scope handling, and canonical envelopes.
- Add/maintain regression tests for campus-building persistence payload validation and list/upsert behavior.
