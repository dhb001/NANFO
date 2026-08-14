# Current Sprint State

## Active Goals
- Vertical Slice 1 Implementation: **COMPLETE** — all modules implemented, tested, and migrated.
- Vertical Slice 2 Implementation: **COMPLETE** — telemetry ingestion/persistence/read APIs and telemetry health counters + `/ws/telemetry` fanout delivered through Step 8.
- Vertical Slice 3 Implementation: **COMPLETE** — runtime collector reliability, adapter-path advancement beyond stub, backpressure/SLO hardening, and VS3 planning-governance closure delivered through **VS3 Step 28**.
- Vertical Slice 4 Implementation: **COMPLETE** — runtime adapter increment, SLO alerting/runbook operationalization, deferred-topology governed design start, and executable Digital Twin scenario-validation handoff baseline delivered through **VS4 Step 4**.
- Vertical Slice 5 Implementation: **COMPLETE** — digital twin websocket session-security hardening and governed simulation lifecycle event coverage delivered through **VS5 Step 4**, with closure regression gate complete.
- Vertical Slice 6 Implementation: **COMPLETE** — Digital Twin spatial-reference execution delivered through **VS6 Step 5** with closure regression gate complete.
- Vertical Slice 7 Implementation: **COMPLETE** — Simulation lifecycle baseline execution delivered through **VS7 Step 7** with branch/read/compare endpoints, lifecycle audit/contract alignment, and closure regression gate complete.
- Vertical Slice 8 Implementation: **COMPLETE** — Intent Engine recommendation/explainability baseline and frontend parity are delivered through VS8 closure gate with validated intent UX/realtime reconciliation, tenancy management parity, and full frontend quality gates.
- Vertical Slice 9 Implementation: **COMPLETE** — Hypervisor execution + rollback baseline and frontend execution-monitoring parity are delivered through VS9 closure gate with full backend/frontend validation evidence.
- Vertical Slice 10 Implementation: **IN PROGRESS** — Backend and frontend topology-analysis parity are implemented; final closure gate evidence and tracking finalization remain.

## Subsystem Progress — Vertical Slice 8

- [x] Step 1: Lock VS8 contract scope and execution scaffold (IntentEngine endpoint/event set, migration classification, validation matrix, and risk register) in `docs/project/IntentEngineExecutionPlan-VS8.md`
- [x] Step 2: Add intent lifecycle persistence baseline table/model/repository (required migration MIG-8.1)
- [x] Step 3: Add `POST /api/v1/intents/validate` with explicit validation reason contracts
- [x] Step 4: Add `POST /api/v1/intents/execute` lifecycle baseline with idempotent workflow semantics
- [x] Step 5: Add `GET /api/v1/intents/{id}` lifecycle/provenance read endpoint
- [x] Step 6: Add governed intent lifecycle event publication + consumer coverage (`intent.validated`, `intent.execution_started`, `intent.execution_completed`, `intent.execution_failed`) — producer publication now covers full lifecycle set with bounded terminal transition source in execute flow (`execution_completed` on queued handoff record, `execution_failed` on degraded handoff), with audit/ws consumer coverage intact
- [x] Step 7: Add explainability/confidence metadata baseline and focused coverage — baseline fields are present in validate/execute/detail contracts; focused fallback/contract coverage added for execution replay/detail serialization paths
- [x] Closure Gate: Final full backend regression pass + VS8 project tracking finalized (backend regression gate remained green; frontend parity implementation + lint/type/unit/e2e/build/perf evidence recorded)

### VS8 — Frontend Workstream (Required for VS8 Closure)
- UI scope: Intent validate/execute flows, intent detail lifecycle timeline, explainability/confidence rendering, and operator action affordances.
- UI states (`loading`, `empty`, `error`, `retry`, `success`): Skeleton/loading for validate/execute/detail requests; empty-state for no intent records; explicit error state with retry action; success states for validated/rejected/execution-started and terminal outcomes.
- Realtime behavior expectations: Consume intent lifecycle deltas on `/ws/digital-twin` (`intent.validated`, `intent.execution_started`, `intent.execution_completed`, `intent.execution_failed`) and reconcile pushed state with `GET /api/v1/intents/{id}`.
- Accessibility/responsiveness acceptance criteria: Keyboard-operable form/actions, status/error announcements for async transitions, AA-level contrast for lifecycle badges, and functional layouts for mobile and desktop breakpoints.
- Frontend tests required (`unit`, `component`, `e2e`): Unit tests for intent state mapping and retry logic; component tests for validate/execute/detail panels; e2e flow for validate -> execute -> realtime status transition including retry paths.
- API and WebSocket dependencies: `POST /api/v1/intents/validate`, `POST /api/v1/intents/execute`, `GET /api/v1/intents/{id}`, `/ws/digital-twin` intent lifecycle scene-delta contract.
- Current blocker: none.
- Latest frontend full-gate evidence (2026-08-14): `npm run lint` PASS, `npm run typecheck` PASS, `npm run test` PASS (`9 files, 25 tests`), `npm run test:e2e` PASS (`8/8`), `npm run build` PASS, `npm run perf:bundle` PASS.
- E2E stability follow-up applied before gate rerun: selector strictness hardening in VS2/VS7 specs and query-tolerant network session mocks for tenancy/workspace flows (`frontend/tests/e2e/vs2-telemetry.spec.ts`, `frontend/tests/e2e/vs7-branch-compare.spec.ts`, `frontend/tests/e2e/support/session.ts`).

## Post-VS8 Plan (Authoritative Remaining VS Plan)

### End-State (After Final Planned Slice)
- All documented PRD surfaces are delivered for Intent/Hypervisor, deferred Topology analysis, Alerts, Plugins, and Reporting.
- C5 workspace/org boundary validation and C6 deferred-topology governance remain intact.
- Canonical API/event contracts remain envelope-compliant and regression-verified.
- Milestone 10 closure gate is complete and release-readiness evidence is recorded.

### VS9 — Hypervisor Execution + Rollback Baseline
- Status: **COMPLETE**.
- Objective: Complete intent-to-hypervisor baseline execution with verification and rollback-ready lifecycle outcomes.
- Scope boundaries: Use existing intent API surface (`POST /api/v1/intents/execute`, `GET /api/v1/intents/{id}`); no `/api/v1/ai/*` additions; no C5/C6 relaxations.
- Acceptance criteria: Validated intents transition to terminal lifecycle outcomes (`execution_completed` or `execution_failed`), rollback metadata is persisted when applicable, and terminal intent lifecycle events are emitted/audited.
- Risks: Unsafe vendor dispatch behavior, partial rollback under degraded dependencies, and terminal-state drift across persistence/events.
- Dependencies: VS8 closure, ADR-008 simulation-before-deployment policy, and ADR-006 event-bus contract governance.
- Closure gate: Scoped Ruff + intent/hypervisor unit/integration coverage + migration gate when schema changes + `poetry run pytest tests -q`.
- Frontend Workstream:
  - UI scope: Intent execution monitoring UI with terminal-state visibility and rollback metadata/operator context.
  - UI states (`loading`, `empty`, `error`, `retry`, `success`): Loading and empty states for execution timeline views, explicit failed-execution error surfaces with retry affordances where allowed, and success states for completed/rolled-back outcomes.
  - Realtime behavior expectations: Live intent lifecycle progression from started to terminal states via `/ws/digital-twin`, with deterministic merge between pushed deltas and detail reads.
  - Accessibility/responsiveness acceptance criteria: Accessible status timeline semantics, keyboard navigation for execution controls, clear assistive messaging for failed/rolled-back outcomes, and mobile-safe execution detail layouts.
  - Frontend tests required (`unit`, `component`, `e2e`): Unit tests for terminal-state mapping and rollback metadata transforms; component tests for lifecycle timeline/cards; e2e tests covering execution start, completion/failure rendering, and retry UX.
  - API and WebSocket dependencies: `POST /api/v1/intents/execute`, `GET /api/v1/intents/{id}`, `/ws/digital-twin` intent lifecycle deltas.

## Subsystem Progress — Vertical Slice 9

- [x] Step 1: Add backend hypervisor execution baseline with verification + rollback-ready lifecycle metadata and execute-permission gate (`execute:rollback`) while preserving existing intent API surface and fail-open event publication semantics.
- [x] Step 2: Add VS9 frontend execution-monitoring parity for terminal-state visibility and rollback metadata context (logic + component + e2e updates) including rollback reference/failure diagnostics and realtime verification/rollback status rendering.
- [x] Closure Gate: Final scoped/frontend/backend validation pass and VS9 tracking finalization (`poetry run ruff check` scoped intent files ✅, VS9 targeted backend suite `63 passed` ✅, backend regression `poetry run pytest tests -q` `360 passed` ✅, frontend `npm run lint` ✅, `npm run typecheck` ✅, `npm run test` `28 passed` ✅, `npm run test:e2e` `8/8 passed` ✅, `npm run build` ✅, `npm run perf:bundle` ✅).

### VS10 — Deferred Topology Analysis Endpoints
- Status: **IN PROGRESS**.
- Objective: Deliver deferred topology analysis endpoints under C6 with deterministic query semantics.
- Scope boundaries: Implement only `GET /api/v1/topology/device/{id}/neighbors`, `GET /api/v1/topology/impact/{id}`, and `POST /api/v1/topology/reconcile`; no unapproved endpoint expansion.
- Acceptance criteria: Neighbor query returns deterministic ordering + edge metadata, impact query returns reachable dependency set with hop depth, and reconcile flow emits auditable lifecycle events.
- Risks: Graph query latency at scale, stale relationship reads during reconcile windows, and accidental route-surface creep.
- Dependencies: Existing topology graph baseline, VS3/VS4 deferred-topology governance artifacts, and EventAPI audit contract rules.
- Closure gate: Scoped Ruff + topology unit/integration coverage (including C6 route-surface assertions) + `poetry run pytest tests -q`.
- Frontend Workstream:
  - UI scope: Topology analysis views for neighbours, impact graph/list results, and reconcile action/status feedback.
  - UI states (`loading`, `empty`, `error`, `retry`, `success`): Loading indicators for analysis queries/jobs, empty-state messaging for no reachable neighbours/impact, explicit query/job failure states with retry actions, and success rendering with deterministic ordering.
  - Realtime behavior expectations: Topology analysis views respond to `/ws/topology` structural deltas by refreshing or invalidating stale analysis results; reconcile status reflects latest available backend lifecycle updates.
  - Accessibility/responsiveness acceptance criteria: Keyboard and screen-reader access for graph/list alternatives, touch-safe controls for reconcile actions, and responsive panel collapse/stack behavior across viewport sizes.
  - Frontend tests required (`unit`, `component`, `e2e`): Unit tests for query parameter/state normalization; component tests for neighbour/impact/reconcile states; e2e tests for successful analysis, empty analysis, and retry-on-error flows.
  - API and WebSocket dependencies: `GET /api/v1/topology/device/{id}/neighbors`, `GET /api/v1/topology/impact/{id}`, `POST /api/v1/topology/reconcile`, `/ws/topology`.
  - Current blocker: none.
  - Latest frontend full-gate evidence (2026-08-14): `npm run lint` PASS, `npm run typecheck` PASS, `npm run test` PASS (`11 files, 35 tests`), `npm run test:e2e` PASS (`10/10`), `npm run build` PASS, `npm run perf:bundle` PASS.

## Subsystem Progress — Vertical Slice 10

- [x] Step 1: Add backend deferred-topology endpoints (`GET /topology/device/{id}/neighbors`, `GET /topology/impact/{id}`, `POST /topology/reconcile`) with deterministic ordering, edge metadata/hop-depth semantics, and auditable reconcile lifecycle events under canonical envelope contracts.
- [x] Step 2: Add VS10 frontend topology-analysis parity (neighbors + impact + reconcile UI, async state coverage, realtime topology-delta invalidation behavior, and required unit/component/e2e updates) with navigation/hotkey/command wiring and validated test coverage.
- [ ] Closure Gate: Final scoped/frontend/backend validation pass and VS10 tracking finalization.

### VS11 — Alerts API Lifecycle Completion
- Status: **PLANNED**.
- Objective: Complete Alerts PRD API lifecycle and event parity for acknowledge/resolve workflows.
- Scope boundaries: Implement only `GET /api/v1/alerts`, `POST /api/v1/alerts/{id}/ack`, `POST /api/v1/alerts/{id}/resolve`; reuse existing `/ws/alerts` channel (no new channels).
- Acceptance criteria: Alerts list/read returns canonical envelope data, ack/resolve transitions are auditable with correlation IDs, and `alert.acknowledged` contract coverage is added with fail-open event handling preserved.
- Risks: Alert fatigue from noisy thresholds, duplicate lifecycle transitions, and stale acknowledgement races.
- Dependencies: Existing telemetry/alert lifecycle baseline (`alert.generated`, `alert.resolved`), audit consumer flow, and WebSocket alert fanout.
- Closure gate: Scoped Ruff + alerts unit/integration/event-flow coverage + `poetry run pytest tests -q`.
- Frontend Workstream:
  - UI scope: Alerts list/details, acknowledge/resolve actions, severity/correlation filters, and lifecycle badges.
  - UI states (`loading`, `empty`, `error`, `retry`, `success`): Loading and empty list states, action-level error states with retry affordances, and success transitions for acknowledged/resolved alerts.
  - Realtime behavior expectations: `/ws/alerts` deltas merge into current alert views with deterministic deduplication and status reconciliation.
  - Accessibility/responsiveness acceptance criteria: Accessible tabular/list semantics, keyboard-triggered ack/resolve actions with clear focus retention, readable severity indicators, and mobile-friendly alert action layout.
  - Frontend tests required (`unit`, `component`, `e2e`): Unit tests for severity/dedup/filter logic; component tests for alert list/action states; e2e tests for list -> ack -> resolve lifecycle with realtime updates.
  - API and WebSocket dependencies: `GET /api/v1/alerts`, `POST /api/v1/alerts/{id}/ack`, `POST /api/v1/alerts/{id}/resolve`, `/ws/alerts`.

### VS12 — Plugin Runtime Safety Baseline
- Status: **PLANNED**.
- Objective: Deliver plugin registry lifecycle with signature/dependency checks and fault isolation.
- Scope boundaries: Implement only PRD-listed plugin APIs (`list/install/enable/disable`) and lifecycle events; no unrestricted runtime execution path.
- Acceptance criteria: Invalid signatures are rejected, dependency incompatibility is explicit, and plugin failures do not crash core runtime paths.
- Risks: Sandbox escape or excessive plugin privileges, startup instability from plugin registration drift, and event contract/version churn.
- Dependencies: ADR-005 async runtime/worker baseline, security guardrails, and module ownership boundaries.
- Closure gate: Scoped Ruff + plugin manifest/lifecycle/isolation coverage + `poetry run pytest tests -q`.
- Frontend Workstream:
  - UI scope: Plugin catalog/registry views and install/enable/disable lifecycle controls with safety-state messaging.
  - UI states (`loading`, `empty`, `error`, `retry`, `success`): Loading and empty registry states, explicit signature/dependency failure states with retry guidance, and success states for lifecycle transitions.
  - Realtime behavior expectations: UI reflects lifecycle transitions immediately after action and reconciles status through near-real-time refresh/polling until terminal state (no new WebSocket channel assumed in this slice).
  - Accessibility/responsiveness acceptance criteria: Keyboard-operable lifecycle controls, assistive-readable safety warnings, non-color-only status indicators, and responsive card/table rendering.
  - Frontend tests required (`unit`, `component`, `e2e`): Unit tests for plugin status/safety mapping; component tests for lifecycle controls and failure states; e2e tests for install/enable/disable success and failure/retry flows.
  - API and WebSocket dependencies: `GET /api/v1/plugins`, `POST /api/v1/plugins/install`, `POST /api/v1/plugins/{id}/enable`, `POST /api/v1/plugins/{id}/disable`; WebSocket dependency: none documented for this slice.

### VS13 — Reporting Async Pipeline Baseline
- Status: **PLANNED**.
- Objective: Deliver report generation/status APIs with queue-backed artifact lifecycle tracking.
- Scope boundaries: Implement only `POST /api/v1/reports/generate` and `GET /api/v1/reports/{id}` with metadata/artifact references; no ad-hoc analytics endpoint expansion.
- Acceptance criteria: Requests produce stable report jobs, status endpoint reflects terminal states, and `report.requested|generated|failed` event contracts are covered.
- Risks: Long-running jobs starving worker pools, artifact reference integrity failures, and inconsistent output schema between formats.
- Dependencies: ADR-005 worker model, telemetry/simulation/alert data availability, and object-storage metadata conventions.
- Closure gate: Scoped Ruff + report unit/integration queue-to-artifact coverage + `poetry run pytest tests -q`.
- Frontend Workstream:
  - UI scope: Report request form, report status detail page, and artifact access/download presentation.
  - UI states (`loading`, `empty`, `error`, `retry`, `success`): Loading job-state polling views, empty-state for no generated artifacts, explicit failed-job states with retry actions, and success states with stable artifact metadata.
  - Realtime behavior expectations: Status views auto-refresh job lifecycle to terminal state and reconcile backend status transitions without requiring manual reload (no new WebSocket channel assumed in this slice).
  - Accessibility/responsiveness acceptance criteria: Accessible form labels/errors, keyboard-first report actions, screen-reader-friendly status changes, and responsive request/status layouts.
  - Frontend tests required (`unit`, `component`, `e2e`): Unit tests for report status mapping and retry triggers; component tests for generate/status views; e2e tests for request -> in-progress -> success/failure lifecycle.
  - API and WebSocket dependencies: `POST /api/v1/reports/generate`, `GET /api/v1/reports/{id}`; WebSocket dependency: none documented for this slice.

### VS14 — Production Readiness Closure Gate
- Status: **PLANNED**.
- Objective: Close M10 with operational hardening, validation evidence, and release-readiness sign-off.
- Scope boundaries: Hardening/verification only; no net-new product API/event surface unless required for defect remediation.
- Acceptance criteria: Performance/load thresholds are validated, security/risk checklist is satisfied, runbooks are current, and release checklist evidence is complete.
- Risks: Hidden cross-module regressions, environment parity gaps, and under-tested failure-recovery paths.
- Dependencies: VS9-VS13 closure completion and full project tracking parity.
- Closure gate: Full regression + targeted load/security gates + release-readiness checklist sign-off in project docs.
- Frontend Workstream:
  - UI scope: Cross-application hardening and completion pass for all VS8-VS13 flows, including shared error-boundary, navigation, and state-consistency behavior.
  - UI states (`loading`, `empty`, `error`, `retry`, `success`): Verify consistent treatment across all production user journeys and remove slice-specific state inconsistencies.
  - Realtime behavior expectations: Validate sustained correctness of all documented realtime channels (`/ws/topology`, `/ws/alerts`, `/ws/digital-twin`, `/ws/telemetry`) under reconnect, burst, and degraded backend conditions.
  - Accessibility/responsiveness acceptance criteria: Full accessibility regression pass across core journeys plus responsive verification for mobile/tablet/desktop breakpoints.
  - Frontend tests required (`unit`, `component`, `e2e`): Production readiness requires green frontend unit/component suites and e2e regression suite covering representative cross-slice journeys.
  - API and WebSocket dependencies: All documented REST and WebSocket contracts delivered in VS8-VS13 must remain integration-parity compliant.

## Remaining Work Master Checklist (Authoritative, Ordered, Non-Overlapping)

- [x] VS8 closure complete (frontend parity workstream + final closure tracking evidence recorded).
- [x] VS9 closure complete (hypervisor execution + rollback baseline with terminal intent lifecycle outcomes).
- [ ] VS10 closure complete (deferred topology analysis endpoint set delivered under C6 governance).
- [ ] VS11 closure complete (alerts API lifecycle + event parity delivered).
- [ ] VS12 closure complete (plugin lifecycle + sandbox safety baseline delivered).
- [ ] VS13 closure complete (reporting async generation/status baseline delivered).
- [ ] VS14 closure complete (M10 production readiness gate and release evidence finalized).

## Subsystem Progress — Vertical Slice 7

- [x] Step 1: Add simulation lifecycle persistence baseline table/model/repository (with required migration)
- [x] Step 2: Persist simulation start flow with C5-safe network/workspace validation and fail-open queue semantics
- [x] Step 3: Add `POST /api/v1/simulations/pause` and resume semantics via `POST /api/v1/simulations/start`
- [x] Step 4: Add `POST /api/v1/simulations/branch` with draft lineage persistence
- [x] Step 5: Add `GET /api/v1/simulations/{id}` read endpoint
- [x] Step 6: Add `GET /api/v1/simulations/{id}/compare/{baselineId}` deterministic compare deltas
- [x] Step 7: Add simulation lifecycle audit coverage and contract alignment updates
- [x] Closure Gate: Final full backend regression pass + VS7 project tracking finalized

## Subsystem Progress — Vertical Slice 6

- [x] Step 1: Add `spatial_ref_id` to Device model + API schemas + create-device flow (with required migration)
- [x] Step 2: Propagate `spatial_ref_id` through `network.device.added` event and topology node writes
- [x] Step 3: Add update flow for `spatial_ref_id` and `network.device.updated` delta semantics
- [x] Step 4: Extend digital twin payload mapping with spatial reference metadata where available
- [x] Step 5: Expose spatial reference on governed topology read paths where contracts allow
- [x] Closure Gate: Final full backend regression pass + VS6 project tracking finalized

## Subsystem Progress — Vertical Slice 5

- [x] Step 1: Enforce `/ws/digital-twin` JWT expiry revalidation on every scene-delta push with `WS_UNAUTHORIZED` close semantics
- [x] Step 2: Add `/ws/digital-twin` per-delta deny-list (`jti`) revalidation path before push delivery
- [x] Step 3: Add digital twin websocket session-security observability branches/counters for close reasons
- [x] Step 4: Expand simulation lifecycle event coverage beyond handoff/completion under governed simulation contract updates
- [x] Closure Gate: Final full backend regression pass + VS5 project tracking finalized

## Subsystem Progress — Vertical Slice 4

- [x] Step 1: Vendor-facing runtime adapter increment baseline (SNMP/gRPC deterministic modes) behind runtime adapter factory controls
- [x] Step 2: Operationalize runtime adapter SLO thresholds into alerting signals and runbook-backed response metadata
- [x] Step 3: Begin governed implementation design for deferred topology analysis endpoints (`/neighbors`, `/impact`, `/reconcile`) under C6
- [x] Step 4: Start executable Digital Twin baseline integration with scenario validation pipeline handoff

## Subsystem Progress — Vertical Slice 3

- [x] Step 1: Collector startup retry/backoff baseline
- [x] Step 2: Single-poll runtime retry wrapper
- [x] Step 3: Runtime collector loop harness
- [x] Step 4: Runtime loop lifecycle wiring in app startup/shutdown
- [x] Step 5: Sustained runtime exhaustion visibility in telemetry health
- [x] Step 6: Sustained runtime-failure transition internal events
- [x] Step 7: Audit consumption for sustained-failure transitions
- [x] Step 8: Alert event flow routing for sustained-failure transitions
- [x] Step 9: `/ws/alerts` fanout for alert lifecycle events
- [x] Step 10: Alert websocket fanout observability counters/log branches
- [x] Step 11: Minimal production collector adapter stub wired to runtime poll path
- [x] Step 12: Runtime adapter health/backpressure observability counters
- [x] Step 13: Runtime adapter SLO snapshot visibility in telemetry health internals
- [x] Step 14: Runtime adapter backpressure anomaly warning thresholds in health logging
- [x] Step 15: Runtime adapter rolling anomaly streak visibility in health logging
- [x] Step 16: Runtime adapter anomaly streak persisted via Redis health counters
- [x] Step 17: Runtime adapter anomaly streak transition metadata observability
- [x] Step 18: Runtime adapter SLO health rollup severity visibility
- [x] Step 19: Runtime adapter SLO trend-window transition visibility
- [x] Step 20: Runtime adapter SLO trend-threshold trigger visibility
- [x] Step 21: Runtime adapter SLO trend-threshold cooldown and recovery visibility
- [x] Step 22: Runtime adapter trend-threshold cooldown-state observability summary
- [x] Step 23: Runtime adapter cooldown-transition event visibility and coverage
- [x] Step 24: Runtime adapter cooldown-correlation snapshot aggregation and coverage
- [x] Step 25: Runtime adapter mode factory and deterministic seeded production adapter path
- [x] Step 26: Runtime adapter dropped-sample backpressure hardening and SLO visibility
- [x] Step 27: C6 deferred topology planning/governance closure and non-routability hardening
- [x] Step 28: Digital Twin baseline integration/scenario planning closure and VS3 completion gate

## Subsystem Progress — Vertical Slice 2

- [x] Step 5: Telemetry ingestion scaffold + collector lifecycle wiring
- [x] Step 6: `telemetry_records` persistence baseline
- [x] Step 7: Telemetry read APIs (`history`, `device`, `health`)
- [x] Step 8: Telemetry operational health counters + persisted-event telemetry WS delta fanout

## Subsystem Progress — Vertical Slice 1

- [x] Architecture & Rules Setup
- [x] Documentation Structure (`docs/` map + phases 1-3)
- [x] Feature PRD Baseline (Authentication, Topology, Simulation, Telemetry, Organization)
- [x] ADR Baseline (ADR-001 to ADR-008)
- [x] Roadmap/Milestones aligned to vertical-slice-first delivery
- [x] Vertical Slice 1 Design Package — initial pass
- [x] Vertical Slice 1 Design Package — corrected (canonical docs re-read, errata resolved)
- [x] Vertical Slice 1 Design Closure — WebSocket channel ambiguity resolved
- [x] Vertical Slice 1 Design Closure — JWT claim baseline added to `Authentication.md` §8
- [x] Vertical Slice 1 Design Closure — `Organization.md` PRD created
- [x] Architecture Review Gate — APPROVE-WITH-CONDITIONS → all conditions resolved
- [x] Backend scaffolding (FastAPI, modular monolith, async SQLAlchemy, lazy engine)
- [x] Identity module: User, Role, Permission models + AuthService + JWT + rate-limiting
- [x] Organization module: Org, Workspace, OrgMember models + OrgService + WorkspaceService
- [x] Network module: Network, Device models + NetworkService + DeviceService (C5 enforced)
- [x] Event Bus: Redis Streams consumer loop + audit/topology/ws_push handlers
- [x] WebSocket: `/ws/topology` endpoint + connection manager
- [x] API routers: auth, orgs, networks, topology (scoped), audit — all envelope-compliant
- [x] Exception handlers: HTTPException → canonical envelope (all 4xx/5xx wrapped)
- [x] Database migration: `0001_initial_schema` applied to live PostgreSQL 16.14
- [x] Test suite: **68/68 passing** (39 unit + 29 integration, no warnings)
- [x] C5 verified: workspace_id validated via WorkspaceService API, no SQL cross-joins
- [x] C6 verified: deferred endpoints (/neighbors, /impact, /reconcile) absent from routing
- [x] Docker infrastructure: PostgreSQL 16, Neo4j 5.25, Redis 7 — all healthy

## Blocked / Deferred
- Digital Twin spatial references — deferred to M6
- Performance load testing — deferred to post-VS2
- Repo-wide Ruff debt outside VS2 Step 8 scope remains and is tracked for later cleanup.

## Next Sprint Candidates
- TBD (next slice planning kickoff).
