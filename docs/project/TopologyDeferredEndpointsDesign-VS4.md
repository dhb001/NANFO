# VS4 Design: Deferred Topology Endpoints (C6)

## Purpose
Start governed implementation design for deferred topology analysis endpoints while keeping C6 enforcement active in runtime routing.

## Scope
- In scope: design handoff for future implementation of:
  - `GET /api/v1/topology/device/{id}/neighbors`
  - `GET /api/v1/topology/impact/{id}`
  - `POST /api/v1/topology/reconcile`
- Out of scope in this step:
  - registering any deferred endpoint route
  - changing API envelope contracts
  - schema migrations
  - changing existing topology endpoint behavior

## Guardrails
- Keep C6 active until a dedicated implementation step explicitly enables each endpoint.
- Preserve C5 data ownership and module boundaries (Network module owns topology queries).
- Use canonical API envelope and existing auth/dependency patterns.
- Keep fail-open startup/runtime behavior unchanged.

## Module Impact Plan

### Planned Route Layer
- `backend/app/api/v1/topology.py`
  - Add deferred endpoints only when implementation step starts.
  - Reuse existing dependency flow (`get_current_user`, request meta, Neo4j driver access).

### Planned Service Layer
- `backend/app/modules/network/topology.py`
  - Extend `TopologyQueryService` with:
    - full neighbors query (deterministic ordering + edge metadata)
    - impact traversal query (reachable dependency set + hop depth)
    - reconcile orchestration entrypoint (read/compare and status result)

### Planned Test Layer
- `backend/tests/integration/test_network_endpoints.py`
  - Convert current C6 non-routability assertions to route-level contract assertions only in the step that enables each endpoint.
- `backend/tests/unit/test_topology_flow.py`
  - Add deterministic unit coverage for neighbors/impact query shaping and reconcile path behavior.

## API Contract Notes
- Endpoint paths come from `docs/features/Topology.md` deferred scope section.
- Responses remain under canonical `{success, data, meta, errors}` envelope.
- Query semantics to preserve from PRD:
  - neighbors: deterministic ordering and edge metadata
  - impact: reachable dependency set with hop depth
  - reconcile: explicit success/failure outcome with audit visibility

## Data and Event Notes
- Data source remains Neo4j topology graph plus existing ownership IDs.
- No relational schema changes are expected for initial endpoint delivery.
- Reconcile success/failure audit signaling will reuse existing event bus + audit consumer patterns in implementation step.
- Event naming/payload details stay deferred until implementation to avoid premature contract invention.

## Risks and Mitigations
- Risk: accidental early route exposure before full validation.
  - Mitigation: keep explicit 404 integration tests until implementation cutover.
- Risk: heavy multi-hop impact traversals causing latency spikes.
  - Mitigation: bounded traversal defaults and deterministic pagination strategy in implementation step.
- Risk: reconcile side effects drifting into cross-module writes.
  - Mitigation: keep reconcile orchestration inside Network module boundaries and publish events for external reactions.

## Exit Criteria for Implementation Start
1. C6 deferred route guards are still green at start of implementation step.
2. Endpoint-by-endpoint activation plan is documented and test-backed.
3. Any new event payload fields are documented in owning PRD/DecisionLog at activation time.
