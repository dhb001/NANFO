# Feature PRD: Simulation & Network Physics

## 1. Purpose
Enable safe what-if experimentation by cloning live state into isolated simulation branches and running deterministic physics-driven scenarios.

## 2. Requirements
- Support simulation lifecycle states: Draft -> Queued -> Running -> Paused -> Completed -> Cancelled.
- Run synchronized tick pipeline across physics, network, wireless, users, and AI layers.
- Persist scenario metadata, run outputs, and baseline deltas.
- Expose branch compare views for decision support.

## 3. API Endpoints
All endpoints must follow `docs/api/API_STANDARD.md`.
- `POST /api/v1/simulations/start`
- `POST /api/v1/simulations/pause`
- `POST /api/v1/simulations/branch`
- `GET /api/v1/simulations/{id}`
- `GET /api/v1/simulations/{id}/compare/{baselineId}`

## 3.1 Event Contracts (Baseline)
- `simulation.started` — emitted when a scenario validation handoff is queued for simulation-before-deployment processing.
- `simulation.completed` — emitted when a scenario run reaches completed state and final state deltas can be propagated.
- `simulation.paused` — emitted when an active/queued simulation transitions to paused state.
- `simulation.cancelled` — emitted when a simulation transitions to cancelled state.
- `simulation.branch_created` — emitted when a draft branch simulation is created from a parent simulation lineage.

Baseline payload fields for digital twin synchronization:
- `simulation_id`
- `scenario_id`
- `network_id`
- `scene_object_id`
- `state`
- `status`
- `risk_gate`
- `validation` (object with pipeline stage and required checks)

## 4. Data Model Notes
- Simulation metadata in PostgreSQL.
- Time-series outputs in TimescaleDB.
- Scenario relationships and lineage in Neo4j.

## 5. Risks
- Non-determinism from unseeded random generators.
- Cost spikes from unbounded scenario complexity.

## 6. Acceptance Criteria
- [ ] Same seed + same inputs produce identical metric outputs.
- [ ] Pause/resume preserves simulation state integrity.
- [ ] Baseline compare returns latency, loss, and throughput deltas.
- [ ] Run records include model versions and audit provenance.
