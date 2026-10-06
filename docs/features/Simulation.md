# Feature PRD: Simulation & Network Physics

## 1. Purpose
Enable safe what-if experimentation by cloning live state into isolated simulation branches and running deterministic physics-driven scenarios.

## 2. Requirements
- Support simulation lifecycle states: Draft -> Queued -> Running -> Paused -> Completed -> Cancelled. ADR-028 adds the terminal state `failed`: a run whose claim attempts are exhausted ends with `failure_reason=attempts_exhausted`, announced by `simulation.cancelled`.
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
- `GET /api/v1/simulations?workspace_id=UUID&network_id=UUID&page=1&page_size=20`
  (ADR026): authorized durable summary history, optional network filter, stable
  newest-first ordering and server count. Exact schema: `docs/api/WorkflowHistory.md`.
  The UI selects persisted runs with `simulation_id` and comparison `baseline_id`
  URL parameters; selection never starts/resumes/branches a run. Drafts and active
  tracking survive token rotation. Inspect history after an ambiguous start response
  before creating another run; starts are not automatically retried on transport loss.

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
ADR-017 installs a configured finite-buffer fluid evaluator with an independent
worker and migration0014. Requests with strict scenario_config persist queued work;
pause/resume/checkpoint/branch and compatible comparisons use actual modeled
outputs. Omitted configuration retains legacy cancelled/blocked unavailable behavior.
All modeled output carries source=operator_configured_model and
physical_safety_authorized=false. Completion and objective pass are separate.
Supplied action-bound simulation evidence is retained and revalidated before actual
dispatch; stale or mismatched evidence blocks without replacing manual approval.
Exact request/output schemas and model assumptions:
`backend/app/modules/simulation/README.md` and `MATH.md`.

ADR-028 (C18, C20; README "ADR-028 changes"):
- Detail adds `execution_policy: {policy_floors, limits_respect_policy}`. Only runs whose
  limits respect the server floors (`SIMULATION_POLICY_*`) count as execution evidence;
  evidence expires 300 s after completion.
- Starting or resuming a modeled run beyond `SIMULATION_MAX_ACTIVE_PER_WORKSPACE` (8)
  queued/running runs returns 429 `SIMULATION_QUOTA_EXCEEDED` (`Retry-After`). Workers
  claim the least-recently-active workspace first.
- Same-state pause/resume requests are no-ops.
- History `page` is 1..10000.

- [ ] Same seed + same inputs produce identical metric outputs.
- [ ] Pause/resume preserves simulation state integrity.
- [ ] Baseline compare returns latency, loss, and throughput deltas.
- [ ] Run records include model versions and audit provenance.
