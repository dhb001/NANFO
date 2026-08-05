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
- `GET /api/v1/topology/graph`
- `GET /api/v1/topology/device/{id}/neighbors`
- `GET /api/v1/topology/impact/{id}`
- `POST /api/v1/topology/reconcile`

## 4. Data Model Notes
- Entity ownership: network module.
- Graph edges include `connected_to`, `depends_on`, `located_in`, `powered_by`.
- Avoid direct cross-module joins; consume domain events for updates.

## 5. Risks
- Stale relationships after partial discovery failure.
- Large graph traversal latency without indexing strategy.

## 6. Acceptance Criteria
- [ ] Graph endpoint returns complete topology for a campus.
- [ ] Neighbor query returns deterministic ordering and edge metadata.
- [ ] Impact query returns reachable dependency set with hop depth.
- [ ] Reconcile job emits success/failure audit event.
