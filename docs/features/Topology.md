# Feature PRD: Topology & Infrastructure Graph

## 1. Purpose
Provide a unified logical and physical topology feature that models device connectivity, containment hierarchy, and dependency relationships for troubleshooting, planning, and blast-radius analysis.

## 2. Requirements
- Render hierarchical topology views (Core -> Distribution -> Access -> Clients).
- Maintain topology entities in PostgreSQL and relationships in Neo4j.
- Support change-aware updates from telemetry and discovery pipelines.
- Provide graph queries for dependency and impact analysis.

## 3. API Endpoints
All endpoints must follow `docs/api/API_STANDARD.md`.

### Implemented — Vertical Slice 1
- `GET /api/v1/topology/graph` — Returns all device nodes and `CONNECTED_TO` edges for a given `network_id`. Implemented in VS1; pagination (`limit`, `cursor`) added in VS2.

### Vertical Slice 2 Scope
- `GET /api/v1/topology/nodes/{device_id}` — Returns a single device node and its direct 1-hop neighbours with edge metadata. VS2 implementation scope only.

  > **Scope note:** This endpoint is a targeted single-node view. It is distinct from and does not replace `GET /api/v1/topology/device/{id}/neighbors` (full PRD endpoint, deferred). The VS2 endpoint accepts an optional `depth` query parameter defaulting to `1` and returns the `neighbours` array with `edge_type` and `direction` per neighbour.

### Deferred — Full PRD (M4 full pass, not VS2)
- `GET /api/v1/topology/device/{id}/neighbors` — Full neighbour query with deterministic ordering and edge metadata. Deferred.
- `GET /api/v1/topology/impact/{id}` — Reachable dependency set with hop depth. Deferred.
- `POST /api/v1/topology/reconcile` — Reconciliation job with audit event emission. Deferred.

> **Guardrail:** No deferred endpoint may be implemented or stubbed in VS2 routing. The router must return 404 for any path matching the deferred pattern.

## 4. Data Model Notes
- Entity ownership: network module.
- Graph edges include `connected_to`, `depends_on`, `located_in`, `powered_by`.
- Avoid direct cross-module joins; consume domain events for updates.

## 5. Scope Phasing

| Endpoint | Milestone | Status |
|:--|:--|:--|
| `GET /topology/graph` | VS1 | ✅ Implemented |
| `GET /topology/graph` (paginated) | VS2 | Planned |
| `GET /topology/nodes/{device_id}` | VS2 | Planned |
| `GET /topology/device/{id}/neighbors` | M4 full | Deferred |
| `GET /topology/impact/{id}` | M4 full | Deferred |
| `POST /topology/reconcile` | M4 full | Deferred |

## 6. Neo4j Node Property Requirements

All `Device` nodes in Neo4j must carry the following properties. This is the authoritative property registry for the `Device` label.

| Property | Type | Required | Notes |
|:--|:--|:--|:--|
| `device_id` | String (UUID) | ✅ | Primary identifier. Used as merge key. |
| `network_id` | String (UUID) | ✅ | Logical reference to parent network. |
| `workspace_id` | String (UUID) | ✅ | Propagated from `network.device.added` payload. Required for multi-tenant graph isolation queries in VS3+. |
| `hostname` | String | ✅ | Human-readable device name. |
| `device_type` | String | ✅ | Device category (e.g., `router`, `switch`, `ap`). |
| `status` | String | ✅ | Lifecycle state: `active`, `offline`, `deleted`. |

> `workspace_id` must be set on every MERGE/SET operation in `TopologyQueryService.create_device_node()`. Absence of `workspace_id` on a node is a data integrity defect.

## 7. Risks
- Stale relationships after partial discovery failure.
- Large graph traversal latency without indexing strategy.
- Missing `workspace_id` on pre-VS2 nodes requires a one-time backfill query on upgrade.

## 8. Acceptance Criteria

### Full PRD (deferred)
- [ ] Neighbor query returns deterministic ordering and edge metadata.
- [ ] Impact query returns reachable dependency set with hop depth.
- [ ] Reconcile job emits success/failure audit event.

### VS2 Scope
- [ ] `GET /topology/graph` with `limit` returns paginated result with `next_cursor`.
- [ ] `GET /topology/nodes/{device_id}` returns node + 1-hop neighbours with `edge_type` and `direction`.
- [ ] All Device nodes in Neo4j carry `workspace_id` property after VS2 implementation.
- [ ] `GET /topology/graph` returns all nodes and edges for a given `network_id`.
