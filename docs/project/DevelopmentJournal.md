# Development Journal

## [2026-08-14] - Vertical Slice 13 Closure Gate Complete

- **Completed:** Closed VS13 after finishing backend reporting async lifecycle delivery and frontend reporting parity.
- **Backend closure validation:** Scoped Ruff on VS13 report module/tests passed; VS13 targeted backend suite passed (`54` tests); final backend regression gate passed (`poetry run pytest tests -q`, `455 passed`).
- **Frontend closure validation:** Full frontend quality gate passed (`npm run lint`, `npm run typecheck`, `npm run test` with `67` tests, `npm run test:e2e` with `15/15` specs, `npm run build`, `npm run perf:bundle`).
- **Scope/governance confirmation:** No endpoint expansion beyond VS13-approved reporting routes, no REST envelope drift, no C5/C6 boundary relaxation, no undocumented event/channel additions, and no new websocket channels for this slice.
- **Performance note:** Build/perf gates remain green with existing large `three` chunk warning unchanged from prior baseline.

## [2026-08-14] - Vertical Slice 13 Step 2 (Frontend Reporting Parity)

- **Implemented (VS13 frontend parity):** Added a dedicated reports operator surface (`/ops/reports`) with report request form, lifecycle status view, artifact metadata rendering, failed-job diagnostics, and retry flow.
- **Client/hook contract alignment:** Added typed reporting REST client + hooks for `POST /reports/generate` and `GET /reports/{id}` preserving canonical envelope usage, `workspace_id` status-query contract, and `Idempotency-Key` request handling.
- **Navigation/accessibility parity:** Added reports navigation across app shell, command palette, and keyboard shortcuts (`y`, `g y`) to preserve keyboard-first workflows.
- **Failure/retry behavior:** Added explicit JSON/date-range client validation, surfaced idempotency conflict and terminal failure context, and implemented retry path with regenerated idempotency key for failed report requests.
- **Coverage updates:** Added VS13 frontend logic/API/component coverage and new Playwright lifecycle spec for generated and failed->retry report flows; extended shared e2e session mocks for reporting endpoints and idempotency semantics.
- **Validation:** Frontend quality gates passed (`npm run lint`, `npm run typecheck`, `npm run test` `19 files, 67 tests`, `npm run test:e2e` `15/15`, `npm run build`, `npm run perf:bundle`).
- **Scope/governance:** No backend API/event/channel changes in Step 2 and no contract/envelope drift.

## [2026-08-14] - Vertical Slice 13 Step 1 (Reporting Async Pipeline Backend Baseline)

- **Implemented (VS13 backend):** Added reporting API endpoints `POST /api/v1/reports/generate` (`202`) and `GET /api/v1/reports/{id}` under canonical `{success,data,meta,errors}` envelope responses.
- **Persistence baseline:** Added migration `0008_reporting_async_pipeline_baseline` and Report module ORM/repository/service foundation for lifecycle state, idempotency replay/conflict handling, output format/date-range validation, and artifact/error metadata.
- **Event/audit parity:** Added report stream routing and consumer-group registration, report lifecycle consumer handling for `report.requested` terminal transitions, and audit mapping coverage for `report.requested|report.generated|report.failed`.
- **Fail-open behavior:** Reporting lifecycle publish failures remain warning-only (`queue_status=deferred`, `warning=event_queue_unavailable`) with persisted lifecycle continuity and non-fatal API responses.
- **Coverage updates:** Added reporting service + consumer unit suites, reporting endpoint integration suite, and parity assertions in existing event-contract/audit/startup registration tests.
- **Validation:** Scoped Ruff passed for VS13 report scope; VS13 targeted backend suite passed (`54 passed`); full backend regression gate passed (`455 passed`).
- **Scope/governance:** No unapproved API/channel additions, no cross-module SQL join drift, and no C5/C6 boundary relaxations.

## [2026-08-14] - Vertical Slice 12 Closure Gate Complete

- **Completed:** Closed VS12 after finishing backend plugin runtime safety delivery and frontend plugin lifecycle parity.
- **Backend closure validation:** Scoped Ruff on VS12 plugin/event/audit files passed; VS12 targeted backend suite passed (`51` tests); final backend regression gate passed (`poetry run pytest tests -q`, `427 passed`).
- **Frontend closure validation:** Full frontend quality gate passed (`npm run lint`, `npm run typecheck`, `npm run test` with `56` tests, `npm run test:e2e` with `13/13` specs, `npm run build`, `npm run perf:bundle`).
- **Scope/governance confirmation:** No endpoint expansion beyond VS12-approved plugin routes, no REST envelope drift, no C5/C6 boundary relaxation, no undocumented event/channel additions, and no new websocket channels for this slice.
- **Performance note:** Build/perf gates remain green with existing large `three` chunk warning unchanged from prior baseline.

## [2026-08-14] - Vertical Slice 12 Step 2 (Frontend Plugin Lifecycle Parity)

- **Implemented (VS12 frontend parity):** Added a dedicated plugins runtime safety surface (`/ops/plugins`) with install form, registry list, enable/disable controls, safety badges, and explicit failure/warning messaging.
- **Client/hook contract alignment:** Added typed plugins REST client + React Query hooks for `GET /plugins`, `POST /plugins/install`, `POST /plugins/{id}/enable`, and `POST /plugins/{id}/disable`, preserving canonical envelope consumption and queue metadata handling.
- **Navigation/accessibility parity:** Added plugins navigation across app shell, command palette, and keyboard shortcuts (`u`, `g u`) to preserve keyboard-first operator flows.
- **Failure-path parity:** Added install permission pre-validation UX and action-level handling for signature/dependency/sandbox denial responses with retry-safe operator feedback.
- **Coverage updates:** Added VS12 frontend API/unit/component coverage and new Playwright lifecycle spec (`install -> enable -> disable` plus failure/retry paths); expanded shared e2e session mocks for plugin APIs and safety failure semantics.
- **Validation:** Frontend quality gates passed (`npm run lint`, `npm run typecheck`, `npm run test` `16 files, 56 tests`, `npm run test:e2e` `13/13`, `npm run build`, `npm run perf:bundle`).
- **Scope/governance:** No backend API/event/channel changes in Step 2 and no contract/envelope drift.

## [2026-08-14] - Vertical Slice 12 Step 1 (Plugin Runtime Safety Backend Baseline)

- **Implemented (VS12 backend):** Added plugin lifecycle API endpoints `GET /api/v1/plugins`, `POST /api/v1/plugins/install`, `POST /api/v1/plugins/{id}/enable`, and `POST /api/v1/plugins/{id}/disable` under canonical `{success,data,meta,errors}` envelope responses.
- **Persistence baseline:** Added migration `0007_plugin_lifecycle_baseline` and Plugin module ORM/repository/service foundation for lifecycle state, signature/dependency/sandbox validation, idempotent lifecycle semantics, and registry query filtering.
- **Event/audit parity:** Added plugin stream routing, consumer-group registration, and audit mapping coverage for `plugin.installed|plugin.enabled|plugin.disabled|plugin.failed` events.
- **Fail-open behavior:** Plugin lifecycle publish failures remain warning-only (`queue_status=deferred`, `warning=event_queue_unavailable`) with persisted lifecycle continuity and non-fatal API responses.
- **Coverage updates:** Added plugin service unit suite, plugin endpoint integration suite, and parity assertions in existing event-contract/audit/startup registration tests.
- **Validation:** Scoped Ruff passed; VS12 targeted backend suite passed (`51 passed`); full backend regression gate passed (`427 passed`).
- **Scope/governance:** No unapproved API/channel additions, no cross-module SQL join drift, and no C5/C6 boundary relaxations.

## [2026-08-14] - Vertical Slice 11 Closure Gate Complete

- **Completed:** Closed VS11 after finishing both backend alerts lifecycle API delivery and frontend reliability alerts lifecycle parity.
- **Backend closure validation:** Scoped Ruff on VS11 alerts/audit/ws files passed; VS11 targeted alerts suite passed (`58` tests); final backend regression gate passed (`poetry run pytest tests -q`, `398 passed`).
- **Frontend closure validation:** Full frontend quality gate passed (`npm run lint`, `npm run typecheck`, `npm run test` with `42` tests, `npm run test:e2e` with `11/11` specs, `npm run build`, `npm run perf:bundle`).
- **Stability note:** Earlier intermittent `vs4-simulation` e2e timeout did not reproduce on closure rerun; final evidence uses the all-green `11/11` run.
- **Scope/governance confirmation:** No endpoint expansion beyond VS11-approved alerts routes, no REST envelope drift, no C5/C6 boundary relaxation, no undocumented event/channel additions, and `/ws/alerts` reuse preserved (no new websocket channels).
- **Performance note:** Build/perf gates remain green with existing large `three` chunk warning unchanged from prior baseline.

## [2026-08-14] - Vertical Slice 11 Step 2 (Frontend Alerts Lifecycle Parity)

- **Implemented (VS11 frontend parity):** Reworked the reliability surface to consume `/api/v1/alerts` lifecycle data directly, including actionable alert cards with acknowledge/resolve controls, status filtering, and correlation/search affordances.
- **Client/hook contract alignment:** Added typed alerts REST client + React Query hooks for `GET /alerts`, `POST /alerts/{id}/ack`, and `POST /alerts/{id}/resolve`, preserving canonical envelope consumption and action-level queue metadata handling.
- **Realtime parity update:** Added `/ws/alerts` acknowledged lifecycle delta support (`delta_type: ack`) and deterministic UI status normalization (`ack` -> `acknowledged`) for merged realtime/list reconciliation.
- **Navigation/accessibility parity:** Added reliability aliases across hotkeys (`l`, `g l`), app-shell hints, and command-palette command (`Go to Alerts Lifecycle`) to keep keyboard-first operator navigation consistent.
- **Coverage updates:** Added/expanded VS11 frontend unit/component tests for reliability API/page actions, alert helpers, realtime alert ack acceptance, hotkey alias mapping, command palette alias filtering, and VS11 e2e lifecycle flow (`list -> ack -> resolve`).
- **Validation:** Frontend quality gates passed (`npm run lint`, `npm run typecheck`, `npm run test` `13 files, 42 tests`, `npm run test:e2e` `11/11`, `npm run build`, `npm run perf:bundle`).
- **Scope/governance:** No backend API/event/channel changes in Step 2 and no contract/envelope drift.

## [2026-08-14] - Vertical Slice 11 Step 1 (Alerts API Lifecycle Backend Baseline)

- **Implemented (VS11 backend):** Added alerts lifecycle API endpoints `GET /api/v1/alerts`, `POST /api/v1/alerts/{id}/ack`, and `POST /api/v1/alerts/{id}/resolve` under canonical `{success,data,meta,errors}` envelope responses.
- **Persistence baseline:** Added migration `0006_alert_lifecycle_baseline` and Alert module ORM/repository/service foundation for lifecycle state, deduplication, status filtering/search, and auditable acknowledge/resolve transitions.
- **Event/audit/ws parity:** Added dedicated alert lifecycle consumer wiring, extended audit mapping for `alert.generated|alert.acknowledged|alert.resolved` (with actor/resource resolution), and extended `/ws/alerts` fanout parity for `alert.acknowledged` (`delta_type=ack`) plus success counters.
- **Fail-open behavior:** Alert lifecycle publish failures remain warning-only (`queue_status=deferred`, `warning=event_queue_unavailable`) with persisted state continuity and non-fatal API responses.
- **Coverage updates:** Added alert service + consumer unit suites, alert endpoint integration suite, and parity assertions in existing ws/audit unit suites for acknowledged lifecycle handling.
- **Validation:** Scoped Ruff passed; VS11 targeted backend suite passed (`58 passed`); full backend regression gate passed (`398 passed`).
- **Scope/governance:** No unapproved API/channel additions, no cross-module SQL join drift, and no C5/C6 boundary relaxations.

## [2026-08-14] - Vertical Slice 10 Closure Gate Complete

- **Completed:** Closed VS10 after finishing both backend deferred endpoint activation and frontend topology analysis parity.
- **Backend closure validation:** Scoped Ruff on topology/audit files passed; VS10 targeted topology/audit/network suite passed (`62` tests); final backend regression gate passed (`poetry run pytest tests -q`, `375 passed`).
- **Frontend closure validation:** Full frontend quality gate passed (`npm run lint`, `npm run typecheck`, `npm run test` with `35` tests, `npm run test:e2e` with `10/10` specs, `npm run build`, `npm run perf:bundle`).
- **Scope/governance confirmation:** No endpoint expansion beyond VS10-approved set, no REST envelope drift, no C5/C6 boundary relaxation, no schema migration, and no new WebSocket channel additions.
- **Performance note:** Build/perf gates remain green with existing large `three` chunk warning unchanged from prior baseline.

## [2026-08-14] - Vertical Slice 10 Step 2 (Frontend Topology Analysis Parity)

- **Implemented (VS10 frontend parity):** Added a dedicated topology analysis workspace route (`/ops/topology-analysis`) with neighbours and impact tabs, reconcile action/status rendering, and deterministic analysis summaries aligned to VS10 endpoint contracts.
- **Navigation/runtime wiring:** Added route/nav command affordances across App shell, command palette, and keyboard chords (`p`, `g p`) so operators can reach topology analysis from existing navigation paths.
- **Client/hook contract alignment:** Extended topology API client and React Query hooks to cover `GET /topology/device/{id}/neighbors`, `GET /topology/impact/{id}`, and `POST /topology/reconcile` with typed payloads and topology cache invalidation on reconcile success.
- **Realtime stale-data handling:** Topology analysis now watches `/ws/topology` device-delta fingerprints and triggers neighbour/impact refetch for the selected device with deduplicated fingerprint guard; depth/max-hop inputs are range-sanitized to bounded query values.
- **Coverage updates:** Added VS10-specific unit tests (topology logic + hotkey mapping), component tests for neighbour/impact/reconcile/realtime refresh behavior, and a new Playwright e2e spec for success and empty-state analysis flows.
- **Validation:** Backend regression gate passed (`poetry run pytest tests -q`, `375 passed`); frontend full gate passed (`npm run lint`, `npm run typecheck`, `npm run test` `11 files, 35 tests`, `npm run test:e2e` `10/10`, `npm run build`, `npm run perf:bundle`).
- **Scope/governance:** No backend API/event/channel changes in Step 2, no envelope drift, no C5/C6 boundary relaxation, and no schema migration required.

## [2026-08-14] - Vertical Slice 10 Step 1 (Deferred Topology Analysis Endpoints Backend Baseline)

- **Implemented (VS10 backend):** Enabled deferred topology analysis routes `GET /api/v1/topology/device/{id}/neighbors`, `GET /api/v1/topology/impact/{id}`, and `POST /api/v1/topology/reconcile` in the existing topology router with canonical `{success,data,meta,errors}` envelope responses.
- **Neighbours query semantics:** Added deterministic neighbor analysis in `TopologyQueryService.get_device_neighbours(...)` with bounded traversal depth, stable ordering, edge metadata (`edge_metadata`) and directional/hop-depth context per neighbour.
- **Impact query semantics:** Added reachable dependency analysis in `TopologyQueryService.get_impact_analysis(...)` returning deterministic impacted-node ordering by hop depth then device id.
- **Reconcile baseline + auditability:** Added `TopologyQueryService.reconcile_network(...)` with network ownership validation, per-network topology count/backfill checks, and auditable lifecycle event publication (`network.topology.reconcile_requested|completed|failed`) with fail-open handling for event publication degradation.
- **Audit integration:** Extended audit consumer mapping to persist reconcile lifecycle events as `resource_type=network` entries.
- **Coverage updates:** Expanded topology unit tests for neighbors/impact/reconcile logic, route integration tests for enabled endpoint surfaces/envelopes/not-found behavior, and audit consumer unit tests for reconcile lifecycle event persistence mapping.
- **Validation:** Scoped Ruff passed; targeted backend suite passed (`62 passed`); full backend regression gate passed (`375 passed`); frontend quality gates remained green on rerun (`lint`, `typecheck`, `test`, `test:e2e`, `build`, `perf:bundle`).
- **Scope/governance:** No schema migration required, no API envelope drift, no new websocket channel additions, and changes remained confined to VS10 topology scope.

## [2026-08-14] - Vertical Slice 9 Closure Gate Complete

- **Completed:** Closed VS9 after completing both backend hypervisor execution baseline delivery and frontend execution-monitoring parity with rollback diagnostics.
- **Backend closure validation:** Scoped Ruff for VS9 intent/hypervisor files passed; VS9 targeted backend suite passed (`63` tests); final backend regression gate passed (`poetry run pytest tests -q`, `360` passed).
- **Frontend closure validation:** Full frontend gate passed (`npm run lint`, `npm run typecheck`, `npm run test` with `28` tests, `npm run test:e2e` with `8/8` specs, `npm run build`, `npm run perf:bundle`).
- **Stability note:** One intermediate `test:e2e` run showed a transient VS2 inspector-option timeout; immediate rerun passed `8/8` without code changes and final closure evidence uses the all-green run.
- **Governance/scope confirmation:** No new API routes/channels/events beyond documented VS9 contracts, no REST envelope drift, no C5/C6 relaxation, and no schema migration required for VS9.

## [2026-08-14] - Vertical Slice 9 Step 2 (Frontend Execution Monitoring + Rollback Metadata Parity)

- **Implemented (VS9 frontend parity):** Extended intent execution monitoring UI to surface verification and rollback diagnostics from `execution_provenance`, including rollback reference, failure reason, and event publication warnings in `Intent Detail`.
- **Realtime visibility update:** Realtime intent cards now render optional `verification_status` and `rollback_status` hints from `/ws/digital-twin` `changed_fields` while preserving existing status-first badge semantics.
- **Failure-state UX hardening:** Added explicit failed-execution async state rendering when execution provenance carries terminal failure reason, keeping retry-safe execution flow and existing guardrails intact.
- **Test coverage updates:** Added logic tests for execution diagnostics extraction and explainability summary precedence, component tests for failed-execution diagnostics rendering, and e2e VS8/VS9-aligned flow assertions for execution-failed terminal state with rollback reference visibility.
- **Validation:** Scoped frontend lint passed; targeted frontend tests passed (`15` tests across intent logic/component/helpers); targeted Playwright intent e2e passed (`1` test).
- **Scope/governance:** No backend API contract changes, no envelope drift, no new channels/events, and no unrelated frontend refactors.

## [2026-08-14] - Vertical Slice 9 Step 1 (Hypervisor Execution + Rollback Backend Baseline)

- **Implemented (Step 1 backend baseline):** Added a dedicated hypervisor execution service (`backend/app/modules/intent/hypervisor.py`) that deterministically produces terminal execution outcomes with verification metadata and rollback metadata on verification failure, without introducing new API routes/channels/events.
- **Execution service integration:** `IntentExecutionService.execute_intent(...)` now routes validated intents through the VS9 hypervisor baseline outcome model, persists verification/rollback provenance under `execution_provenance`, and emits governed terminal lifecycle events (`intent.execution_completed` / `intent.execution_failed`) aligned to actual hypervisor baseline outcome.
- **Permission hardening:** Added execute permission gate requiring `execute:rollback` for `POST /api/v1/intents/execute` via existing JWT permission claims path; denial returns canonical 403 error (`INTENT_EXECUTION_PERMISSION_DENIED`) without envelope drift.
- **Realtime/audit contract continuity:** Extended ws intent delta mapping to include optional `verification_status` and `rollback_status` fields from execution provenance for operator visibility while preserving `/ws/digital-twin` scene delta contract shape and fail-open handling.
- **Coverage additions:** Added new unit suite for hypervisor baseline service and expanded intent execution/audit/ws/integration tests to cover successful verification, verification-failure rollback, fail-open started-event publication degradation, and execute-permission denial.
- **Validation:** Scoped Ruff passed for all touched backend files; targeted VS9 tests passed (`63 passed`); full backend regression gate passed (`360 passed`).
- **Scope/governance:** No `/api/v1/ai/*` additions, no API envelope drift, no C5/C6 relaxations, no schema migration required in Step 1, and no unrelated module refactors.

## [2026-08-14] - Frontend Full Quality Gate Pass + Evidence Refresh

- **Implemented (frontend-scope hardening):** Finalized Playwright stability fixes by removing strict-mode ambiguous locators in VS2/VS7 and making session network mocks query-tolerant + workspace-aware for tenancy flows.
- **Frontend files touched for stabilization:** `frontend/tests/e2e/vs2-telemetry.spec.ts`, `frontend/tests/e2e/vs7-branch-compare.spec.ts`, `frontend/tests/e2e/support/session.ts`.
- **Validation evidence (full gate rerun):** `npm run lint` ✅, `npm run typecheck` ✅, `npm run test` ✅ (`9 files, 25 tests`), `npm run test:e2e` ✅ (`8 passed`), `npm run build` ✅, `npm run perf:bundle` ✅.
- **Scope/governance compliance:** No backend refactors, no API contract changes, and no C5/C6 scope drift; work remained inside frontend test hardening and project evidence docs.
- **Performance note:** Build + perf bundle remain green with existing large `three` chunk warning unchanged from prior baseline.

## [2026-08-13] - Vertical Slice 8 Frontend Parity + Closure Gate Complete

- **Implemented (VS8 frontend parity):** Added a dedicated tenancy management surface (`/ops/tenancy`) covering organization/workspace/member create/select/remove flows with explicit loading/empty/error/retry/success behavior and keyboard-operable controls.
- **Intent UX hardening:** Improved VS8 intent validate/execute form safety with JSON-object validation, idempotency-conflict handling (`INTENT_IDEMPOTENCY_CONFLICT`), terminal-state execute guard, and clearer operator feedback via toasts + inline async states.
- **Realtime reconciliation:** Added deterministic detail refetch logic when `/ws/digital-twin` intent deltas move lifecycle status, ensuring pushed state and `GET /api/v1/intents/{id}` stay synchronized.
- **Runtime robustness updates:** Hardened websocket hook subscription stability (callback refs + stable filter key) and added explicit no-content request helper for `DELETE` org-member flow while keeping canonical envelope behavior for envelope-backed endpoints.
- **Frontend test delivery:** Added VS8-targeted test coverage across layers — unit logic (`intent/tenancy`), component behavior (`IntentPage`), and e2e flow (`validate -> execute -> retry -> terminal status`) with Playwright web-server orchestration.
- **Validation evidence (frontend gates):** `npm run lint` ✅, `npm run typecheck` ✅, `npm run test` ✅ (`13 passed`), `npm run test:e2e` ✅ (`1 passed`), `npm run build` ✅, `npm run perf:bundle` ✅.
- **Performance note:** Bundle build remains successful but emits large-chunk warning for the `three` chunk (expected with current Digital Twin dependency footprint); no contract/runtime regressions observed.

## [2026-08-13] - Vertical Slice 8 Step 7 Focused Explainability/Confidence Coverage Closure

- **Implemented (Step 7 closure):** Finalized focused explainability/confidence fallback coverage for execute replay/detail serialization paths while preserving existing baseline contract fields.
- **Coverage additions:** Added unit assertions for idempotent replay confidence-band fallback derivation from score when persisted band is absent, and detail-read fallback normalization for non-dict lifecycle metadata (`validation_result`, `execution_provenance`, `explainability`) plus confidence defaults.
- **Contract behavior preserved:** No API surface changes; explainability/confidence payload fields remain baseline-compatible and envelope-compliant for validate/execute/detail endpoints.
- **Validation:** Scoped Ruff passed; targeted intent/audit/ws unit+integration suite passed (`59 passed`); full backend regression gate passed (`351 passed`).
- **Open blocker:** VS8 frontend parity remains blocked in this workspace because the frontend implementation repository/path is not present.

## [2026-08-13] - Vertical Slice 8 Step 6 Producer Closure (Intent Terminal Lifecycle Events)

- **Implemented (Step 6 closure):** Completed producer-side lifecycle publication for the full governed intent event set by adding terminal execute-flow transition sources for `intent.execution_completed` and `intent.execution_failed`.
- **Execution transition behavior:** `POST /api/v1/intents/execute` now persists and emits `intent.execution_started`, then performs a bounded terminal transition in the same flow (`execution_completed` on queued handoff record, `execution_failed` on degraded handoff) with updated provenance/explainability metadata.
- **Fail-open handling:** Terminal event publish failures are warning-only and non-fatal (`intent_terminal_event_publish_failed`), preserving API availability and commit completion while retaining persisted lifecycle state.
- **Coverage updates:** Expanded unit coverage for execute lifecycle expectations to assert started + terminal publish paths and degraded terminal failure behavior.
- **Validation:** Scoped Ruff passed; targeted intent/audit/ws unit+integration suite passed (`57 passed`); full backend regression gate passed (`349 passed`).
- **Open blocker:** VS8 frontend parity remains blocked in this workspace because the frontend implementation repository/path is not present.

## [2026-08-13] - Frontend Completion Criteria Added to Remaining Slice Plan (Planning)

- **Planned:** Added explicit frontend implementation criteria to every remaining slice (`VS8` onward) so closure means full application completion, not backend-only status.
- **Scope update:** Each remaining slice now includes a frontend workstream covering UI scope, required UI states (`loading`, `empty`, `error`, `retry`, `success`), realtime behavior expectations, accessibility/responsiveness acceptance, frontend test requirements (`unit`, `component`, `e2e`), and API/WebSocket dependencies.
- **Governance update:** Recorded an authoritative completion rule in `DecisionLog.md` that a slice cannot be marked complete unless frontend acceptance criteria also pass.
- **Constraints preserved:** Docs-only update; no backend/frontend feature code changes; existing C5/C6 and API/WebSocket contract guardrails unchanged.

## [2026-08-13] - Post-VS8 Planning Baseline (VS9-VS14)

- **Planned:** Defined a finite post-VS8 vertical-slice sequence (`VS9` through `VS14`) with explicit end-state, per-slice objective/scope boundaries/acceptance criteria/risks/dependencies/closure gates, and an authoritative remaining-work checklist.
- **Tracking alignment:** Added a new `Post-VS8 Plan` section and ordered master checklist in `docs/project/CurrentSprint.md`; aligned roadmap and milestone docs to reflect the same VS sequence and closure progression.
- **Governance continuity:** Planning assumptions preserve C5/C6 constraints, canonical API envelope expectations, documented event naming, and modular ownership boundaries; no implementation commitments were marked as done.
- **Assumption handling:** Where PRDs define outcomes but not detailed rollout internals (notably hypervisor execution/rollback and production-readiness gate composition), assumptions were made explicit and recorded in `DecisionLog.md`.
- **Validation pass:** Performed docs-only consistency checks for heading structure, status language (`PLANNED`), and cross-file reference parity (`CurrentSprint`/`Roadmap`/`Milestones`/`AGENTS`).

## [2026-08-13] - Vertical Slice 8 Steps 4-5 Complete + Step 6 In Progress (Execute/Detail + Lifecycle Event Baseline)

- **Implemented (Step 4):** Added `POST /api/v1/intents/execute` (`202`) with idempotent replay behavior, idempotency-key conflict semantics, executable-state conflict checks, and persisted execution lifecycle provenance updates.
- **Implemented (Step 5):** Added `GET /api/v1/intents/{id}` lifecycle/provenance read endpoint with canonical envelope typing and C5-safe workspace boundary validation.
- **Event baseline progress (Step 6):** Intent lifecycle publication now includes `intent.validated` (from validate flow) and `intent.execution_started` (from execute flow) with fail-open queue degradation semantics (`queue_status=deferred`, `warning=event_queue_unavailable`).
- **Consumer coverage:** Intent stream registration (`stream:intent`) is wired in publisher/consumer-group config; audit + `/ws/digital-twin` consumer mappings/tests now cover the full governed intent lifecycle event set (`validated`, `execution_started`, `execution_completed`, `execution_failed`).
- **Open scope (Step 6):** Producer transition sources for `intent.execution_completed` and `intent.execution_failed` remain pending because VS8 baseline currently stops at execution-started lifecycle (hypervisor execution/rollback remains out of VS8 scope).
- **Validation:** Scoped Ruff passed; targeted intent/audit/ws unit+integration suite passed (`61 passed`); migration gate re-verified with `POSTGRES_PASSWORD=CHANGE_ME`; full backend regression passed (`349 passed`).

## [2026-08-13] - Vertical Slice 8 Step 3 (Intent Validate Endpoint Baseline)

- **Implemented:** Added `POST /api/v1/intents/validate` under canonical envelope with explicit validation-reason contracts and persisted validation lifecycle metadata.
- **Validation behavior:** Baseline UNIL validation now enforces action support, non-empty scope, optional-constraints object typing, and C5-safe network/workspace boundary checks before producing `validated` or `rejected` outcomes.
- **Explainability/confidence baseline:** Validation responses now include baseline explainability fields (`summary`, `evidence`, `alternatives_considered`, `policy_reference`) plus confidence posture (`score`, `band`, `approval_required`) aligned to AIOS safety thresholds.
- **Persistence flow:** Validation endpoint writes intent lifecycle records through the Intent repository baseline (`status`, `validation_result`, `execution_provenance`, `explainability`, confidence metadata) with migration-backed schema from Step 2.
- **Governance/constraints:** Endpoint/event scope remains locked to `IntentEngine.md` (no `/api/v1/ai/*` additions), canonical API envelope preserved, no new websocket channels, no cross-module SQL joins, and C6 deferred topology non-routability remains unchanged.
- **Validation:** Scoped Ruff passed; targeted intent unit/integration suite passed (`9 passed`); migration gate re-verified with `POSTGRES_PASSWORD=CHANGE_ME`; full backend regression passed (`322 passed`).

## [2026-08-13] - Vertical Slice 8 Step 2 (Intent Lifecycle Persistence Baseline)

- **Implemented:** Added VS8 persistence foundation with a dedicated `intents` relational table and new Intent module ORM/repository baseline.
- **Schema/model updates:** Added Alembic migration `0005_intent_lifecycle_baseline` plus `Intent` model fields for lifecycle state, validation/execution provenance, explainability metadata, confidence posture, queue outcome, idempotency key, and request timestamps.
- **Repository baseline:** Added `IntentRepository` create/read/idempotency lookup/status-update primitives with deterministic unit coverage.
- **Governance/constraints:** Required migration (MIG-8.1) delivered with downgrade path; no REST/WebSocket endpoint additions in Step 2, no undocumented event names, no C5/C6 contract drift, and no cross-module SQL join introduction.
- **Validation:** Scoped Ruff passed; targeted unit suite passed (`4 passed`); migration gate passed with `POSTGRES_PASSWORD=CHANGE_ME` (upgrade/downgrade/upgrade); full backend regression passed (`317 passed`).

## [2026-08-13] - Vertical Slice 7 Closure (Simulation Lifecycle Baseline Complete)

- **Completed:** Closed remaining VS7 scope (Steps 4-7) with branch creation, simulation detail read, deterministic compare deltas, and lifecycle audit/contract alignment.
- **Contract closure:** Simulation API surface now includes all PRD-listed endpoints (`start`, `pause`, `branch`, `{id}`, `{id}/compare/{baselineId}`) under canonical envelope responses.
- **Lifecycle alignment:** Branch creation now emits `simulation.branch_created`; audit and digital twin websocket consumer mappings include the full implemented simulation lifecycle event set.
- **Governance/constraints:** No C5/C6 drift, no schema migration beyond Step 1 baseline, no undocumented channel additions, and fail-open behavior preserved for queue publish degradation branches.
- **Validation closure:** Required scoped Ruff + targeted suites passed for Step 7 scope (`67 passed`); final backend full regression gate passed (`313 passed`).

## [2026-08-13] - Vertical Slice 7 Step 7 (Lifecycle Audit Coverage + Contract Alignment)

- **Implemented:** Aligned lifecycle event contracts by adding `simulation.branch_created` publication on branch creation and extending governed consumers to handle the new simulation lifecycle event.
- **Audit coverage:** Audit consumer mapping now includes simulation lifecycle events (`simulation.started`, `simulation.completed`, `simulation.paused`, `simulation.cancelled`, `simulation.branch_created`) with simulation resource attribution.
- **WebSocket contract alignment:** `/ws/digital-twin` simulation event translation now includes `simulation.branch_created` using the existing scene-delta `update` shape (no channel or envelope drift).
- **Governance/constraints:** Event naming follows PRD/EventAPI conventions, no new endpoint beyond approved Simulation PRD surface, no schema migration required, and C5/C6 constraints unchanged.
- **Validation:** Scoped Ruff passed; expanded simulation/audit/ws target suite passed (`67 passed`); full backend regression passed (`313 passed`).

## [2026-08-13] - Vertical Slice 7 Step 6 (Compare Endpoint Deterministic Deltas)

- **Implemented:** Added `GET /api/v1/simulations/{id}/compare/{baselineId}` with deterministic baseline deltas for `latency_ms`, `loss_pct`, and `throughput_mbps`.
- **Service behavior:** Compare flow now enforces parent simulation/baseline existence, C5 workspace validation for both records, and same-network conflict checks before computing deltas.
- **Deterministic output:** Metric extraction normalizes missing/non-numeric values to `0.0` to preserve stable compare semantics and predictable envelope contracts.
- **Governance/constraints:** Endpoint and compare fields align to Simulation PRD ACs; no schema migration, no websocket contract changes, and no C6 scope changes.
- **Validation:** Scoped Ruff passed; simulation-targeted unit/integration suite passed (`41 passed`); full backend regression passed (`309 passed`).

## [2026-08-13] - Vertical Slice 7 Step 5 (Simulation Detail Read Endpoint)

- **Implemented:** Added `GET /api/v1/simulations/{id}` with canonical envelope typing and service-layer read flow for persisted lifecycle records.
- **Read contract:** Response now exposes lifecycle lineage/state plus persisted run metadata (`validation`, `run_output`, `model_versions`, `audit_provenance`, queue outcome fields, and timestamps).
- **Boundary enforcement:** Detail read validates simulation existence and preserves C5 workspace boundary checks through Organization service boundary before returning data.
- **Governance/constraints:** Endpoint is explicitly listed in Simulation PRD, no schema migration required, and no event/channel contract changes for Step 5 scope.
- **Validation:** Scoped Ruff passed; simulation-targeted unit/integration suite passed (`35 passed`); full backend regression passed (`303 passed`).

## [2026-08-13] - Vertical Slice 7 Step 4 (Branch Endpoint + Draft Lineage Persistence)

- **Implemented:** Added `POST /api/v1/simulations/branch` (`201`) with canonical envelope typing and service-layer draft branch creation against a persisted parent simulation.
- **Lineage persistence:** Branch creation now persists a new simulation row with `parent_simulation_id` linkage, inherited ownership context (`network_id`, `workspace_id`), draft lifecycle state (`state=status=draft`), and deterministic branch scenario derivation.
- **Validation/provenance behavior:** Branch drafts carry `validation.pipeline_stage=branch_draft`, inherited required checks/policy reference where present, and branch provenance markers (`branch_from_simulation_id`, `branch_correlation_id`) in audit metadata.
- **Governance/constraints:** Endpoint scope matches Simulation PRD, no new domain events or websocket channels introduced, no schema migration required (Step 1 baseline already includes lineage fields), C5 workspace validation preserved via Organization service boundary, and C6 unchanged.
- **Validation:** Scoped Ruff passed; targeted simulation unit/integration tests passed (`30 passed`); full backend regression passed (`298 passed`).

## [2026-08-12] - Vertical Slice 7 Step 3 (Pause Endpoint + Resume Semantics)

- **Implemented:** Added `POST /api/v1/simulations/pause` and resume support on `POST /api/v1/simulations/start` via optional `simulation_id` while preserving canonical response envelope contracts.
- **Lifecycle behavior:** Pause now transitions eligible simulations (`queued`/`running`) to `paused`, emits `simulation.paused` under existing fail-open publish behavior, and remains idempotent for already-paused simulations.
- **Resume behavior:** Start requests with `simulation_id` now resume persisted paused/queued simulations by re-queuing a `simulation.started` handoff against the same simulation record and updating queue outcome metadata (`queued`/`deferred`).
- **Governance/constraints:** No new endpoint beyond Simulation PRD, no undocumented event-name additions, no schema migration in Step 3, C5 workspace validation preserved via Organization service boundary, and C6 unchanged.
- **Validation:** Scoped Ruff passed; targeted simulation unit tests passed (`10 passed`); targeted simulation endpoint/ws integration tests passed (`11 passed`); full backend regression passed (`292 passed`).

## [2026-08-12] - Vertical Slice 7 Step 2 (Simulation Start Persistence + C5 Validation)

- **Implemented:** Refactored `POST /api/v1/simulations/start` to execute through a new `SimulationStartService` that persists simulation handoff records and keeps existing queue fail-open semantics.
- **C5 boundary enforcement:** Start flow now validates `network_id` existence via `NetworkRepository` and validates workspace through `OrgWorkspaceService.get_active_workspace()` before queue handoff, preserving modular service boundary rules.
- **Persistence behavior:** On both queued and deferred publish outcomes, simulation lifecycle rows are persisted with queue metadata (`queue_status`, `stream_entry_id`, `warning`) plus validation/provenance snapshots and baseline run-output placeholders.
- **Fail-open semantics preserved:** Event publish failures still return `202` with `queue_status=deferred` and `warning=event_queue_unavailable`; persistence stores the degraded outcome for traceability.
- **Validation:** Scoped Ruff passed; targeted simulation unit tests passed (`7 passed`); targeted simulation endpoint integration tests passed (`4 passed`); full backend regression passed (`286 passed`).

## [2026-08-12] - Vertical Slice 7 Step 1 (Simulation Lifecycle Persistence Baseline)

- **Implemented:** Added the VS7 persistence foundation by introducing a dedicated `simulations` relational table and simulation module persistence layer.
- **Schema/model updates:** Added Alembic migration `0004_simulation_lifecycle_baseline` plus new Simulation ORM/repository support for lifecycle state, validation metadata, run outputs, model versions, audit provenance, queue outcome metadata, and branch parent linkage.
- **Repository baseline:** Added `SimulationRepository` create/read/queue-outcome update primitives with deterministic unit coverage.
- **Governance/constraints:** Required migration delivered with explicit downgrade path; no API envelope changes, no C5/C6 boundary drift, no new endpoint surface, and fail-open runtime semantics unchanged.
- **Validation:** Scoped Ruff passed; targeted unit test (`test_simulation_repository`) passed; targeted integration smoke (`test_simulation_endpoints -k start`) passed; migration upgrade/downgrade/upgrade gate passed; full backend regression passed (`282 passed`).

## [2026-08-12] - Vertical Slice 6 Closure (Remaining Scope Complete)

- **Completed:** Closed all remaining VS6 steps (3-5) after Step 1-2 baseline with update-path delta semantics, digital twin spatial-metadata mapping, and governed topology read-path spatial-reference exposure.
- **Contract closure:** Device update flow now emits deterministic `network.device.updated` `changed_fields` deltas for `spatial_ref_id`; digital twin scene-delta mapping now carries optional spatial metadata; topology read paths now expose nullable `spatial_ref_id` where available.
- **Governance/constraints:** No API envelope drift, no C5/C6 boundary drift, no deferred endpoint activation, and no additional schema migration beyond Step 1 baseline.
- **Validation closure:** Required scoped Ruff + targeted tests passed for Steps 4-5/closure scope; final backend full regression gate passed (`279 passed`).

## [2026-08-12] - Vertical Slice 6 Step 5 (Governed Topology Read-Path Spatial Reference Exposure)

- **Implemented:** Exposed `spatial_ref_id` on governed topology read paths by extending topology graph/node response payload models and Neo4j read queries.
- **Read-path updates:** `TopologyQueryService.get_graph()` now returns node `spatial_ref_id` when present, and `get_node_with_neighbours()` now includes `spatial_ref_id` for the primary node and each neighbour.
- **API contract updates:** Topology API response typing now explicitly models optional spatial-reference fields while preserving existing envelope and endpoint behavior.
- **Coverage updates:** Added unit/integration assertions for spatial-reference presence and nullability on topology graph and node-with-neighbours responses.
- **Scope guardrails:** No new routes, no C6 deferred endpoint activation, no schema migration, no C5 boundary change, and no envelope drift.
- **Validation:** Scoped Ruff passed; targeted network/topology/ws + simulation-flow tests passed (`73 passed`); full backend regression passed (`279 passed`).

## [2026-08-12] - Vertical Slice 6 Step 4 (Digital Twin Spatial Metadata Payload Mapping)

- **Implemented:** Extended simulation-to-digital-twin websocket payload mapping to include optional spatial metadata in scene deltas when present.
- **Mapping behavior:** `handle_ws_digital_twin_event()` now conditionally maps `spatial_ref_id` and `spatial_metadata` from simulation event payloads into `scene_object` plus `scene_object.changed_fields`.
- **Contract safety:** Baseline scene-delta contract for events without spatial fields remains unchanged; spatial additions are optional and additive only.
- **Coverage updates:** Added unit and integration tests to verify both positive mapping (spatial fields present) and omission behavior (spatial fields absent).
- **Scope guardrails:** No schema migration, no REST envelope drift, no C5/C6 boundary changes, and fail-open event-routing behavior unchanged.
- **Validation:** Scoped Ruff passed; targeted ws-push + simulation-event tests passed (`23 passed`); full backend regression passed (`278 passed`).

## [2026-08-12] - Vertical Slice 6 Step 3 (Spatial Reference Update Flow + Device Updated Delta Semantics)

- **Implemented:** Added device spatial-reference update flow via `PATCH /api/v1/networks/{network_id}/devices/{device_id}` and wired service-layer update handling for `spatial_ref_id`.
- **Update/event semantics:** `DeviceService.update_device_spatial_ref()` now publishes `network.device.updated` with `changed_fields` containing only `spatial_ref_id` when the value actually changes; no-change requests are idempotent no-op returns with no event emission.
- **Repository ownership check:** `DeviceRepository.update_spatial_ref_id()` enforces network/device ownership match before mutating state, preserving module boundary and tenancy safety expectations.
- **Consumer contract coverage:** Added tests to validate topology and websocket update-delta behavior for `changed_fields.spatial_ref_id` propagation.
- **Scope guardrails:** No API envelope drift, no C5/C6 boundary changes, no new schema migration, and fail-open runtime semantics unchanged.
- **Validation:** Scoped Ruff passed; targeted network/topology/ws + network-endpoint tests passed (`65 passed`); full backend regression passed (`275 passed`).

## [2026-08-12] - Vertical Slice 6 Step 2 (Spatial Reference Event + Topology Node Propagation)

- **Implemented:** Propagated `spatial_ref_id` through `network.device.added` event payloads and into topology node writes for Digital Twin synchronization continuity.
- **Event flow update:** Device creation now includes `spatial_ref_id` in `network.device.added` publish payload without changing envelope or event naming.
- **Topology write update:** Topology consumer and `TopologyQueryService.create_device_node()` now persist `spatial_ref_id` on Neo4j `Device` nodes.
- **Coverage updates:** Unit tests now assert event payload propagation and topology consumer/query spatial-ref write semantics.
- **Scope guardrails:** No new schema changes, no API envelope drift, no C5/C6 boundary change, and fail-open runtime semantics unchanged.
- **Validation:** Scoped Ruff passed; targeted network/topology unit+integration tests passed (`41 passed`); full backend regression passed (`266 passed`).

## [2026-08-12] - Vertical Slice 6 Step 1 (Device Spatial Reference Baseline)

- **Implemented:** Started M6/VS6 spatial-reference objective by introducing optional `spatial_ref_id` on network `Device` model and threading it through create-device request/response flow.
- **Schema/model updates:** Added `spatial_ref_id` to SQLAlchemy `Device` model and network device Pydantic schemas; create-device repository/service paths now persist and return the field.
- **Migration safety:** Added Alembic migration `0003_device_spatial_ref` to add nullable `devices.spatial_ref_id` plus index, keeping rollout reversible and backward-compatible.
- **Coverage updates:** Expanded unit/integration network endpoint/service tests to validate `spatial_ref_id` acceptance and response propagation on device creation.
- **Scope guardrails:** No API envelope drift, no C5/C6 boundary changes, no runtime/websocket fail-open behavior changes, and no unrelated refactors.
- **Validation:** Scoped Ruff passed; targeted network unit/integration tests passed (`29 passed`); full backend regression passed (`266 passed`).

## [2026-08-12] - Vertical Slice 5 Closure (Remaining Scope Complete)

- **Completed:** Closed all remaining VS5 steps (2-4) after Step 1 baseline with per-delta deny-list revalidation, session-security close-reason observability, and expanded simulation lifecycle WS coverage.
- **Security closure:** `/ws/digital-twin` now enforces both per-delta expiry and deny-list checks; revoked/expired sessions receive `WS_UNAUTHORIZED` then close, with close-reason counters for `expired` and `revoked`.
- **Lifecycle coverage closure:** `simulation.paused` and `simulation.cancelled` now route to digital twin scene-delta updates under the existing governed payload contract.
- **Governance/constraints:** No schema migrations, no API envelope drift, no C5/C6 boundary changes, and fail-open behavior preserved for Redis lookup/counter failures.
- **Validation closure:** Required scoped Ruff + targeted tests passed for each step; final backend full regression gate passed (`265 passed`).

## [2026-08-12] - Vertical Slice 5 Step 4 (Simulation Lifecycle WS Coverage Expansion)

- **Implemented:** Expanded governed simulation lifecycle fanout coverage for `/ws/digital-twin` beyond handoff/completion by wiring `simulation.paused` and `simulation.cancelled` through existing scene-delta translation flow.
- **Routing behavior:** `ws_push_consumer` now maps `simulation.paused`/`simulation.cancelled` to digital twin `update` deltas using the existing scene-object payload contract (no envelope or payload shape drift).
- **Coverage updates:** Unit and integration tests now verify paused/cancelled event translation, handler registration, and unchanged fail-open behavior for malformed/unmapped events.
- **Scope guardrails:** No schema migration, no new API endpoints, no API envelope drift, no C5/C6 boundary change, and no unrelated refactors.
- **Validation:** Scoped Ruff passed; targeted ws-push + simulation-event tests passed (`19 passed`); full backend regression passed (`265 passed`).

## [2026-08-12] - Vertical Slice 5 Step 3 (Digital Twin WS Session-Security Close-Reason Observability)

- **Implemented:** Added session-security observability for `/ws/digital-twin` close reasons using deterministic Redis counters plus structured log branches.
- **Observability behavior:** Security closes triggered by per-delta JWT checks now record reasoned counters under `digital_twin:ws:security_close:<reason>` (`expired`, `revoked`) before unauthorized frame + close.
- **Fail-open safety:** Counter client acquisition and increment failures are warning-only and do not block security close execution or standard push-path delivery semantics.
- **Coverage updates:** Unit tests now assert reason counter increments for expired and revoked closes and verify fail-open behavior when counter persistence is unavailable.
- **Scope guardrails:** No schema migration, no REST/API envelope change, no event-name/payload contract drift, no C5/C6 boundary change, and no unrelated refactors.
- **Validation:** Scoped Ruff passed; targeted digital-twin/simulation/ws tests passed (`26 passed`); full backend regression passed (`261 passed`).

## [2026-08-12] - Vertical Slice 5 Step 2 (Digital Twin WS Per-Delta JWT Deny-List Revalidation)

- **Implemented:** Added the next minimal VS5 hardening increment by enforcing deny-list (`jti`) revalidation on every `/ws/digital-twin` scene-delta push.
- **Security behavior:** `DigitalTwinWSManager` now stores per-connection token `jti` metadata and checks `jti:deny:<jti>` before each push; revoked sessions receive `WS_UNAUTHORIZED` and are closed before delivery.
- **Endpoint wiring:** `/ws/digital-twin` subscribe path now passes token `jti` claim metadata into manager subscription state together with existing expiry metadata.
- **Fail-open safety:** Redis client acquisition or deny-list lookup failures in push-path checks are warning-only and non-fatal; non-revoked/unknown sessions continue delta delivery.
- **Scope guardrails:** No schema migration, no REST/API envelope change, no event-name/payload contract drift, no C5/C6 boundary change, and no unrelated refactors.
- **Validation:** Scoped Ruff passed; targeted digital-twin/simulation/ws tests passed (`24 passed`); full backend regression passed (`259 passed`).

## [2026-08-12] - Vertical Slice 5 Step 1 (Digital Twin WS Per-Delta JWT Expiry Revalidation)

- **Implemented:** Added the smallest executable VS5 increment by enforcing JWT expiry revalidation on every `/ws/digital-twin` scene-delta push.
- **Security behavior:** `DigitalTwinWSManager` now stores connection token expiry (`exp`) at subscribe time and checks it before each push; expired sessions receive `WS_UNAUTHORIZED` and are closed before delivery.
- **Endpoint wiring:** `/ws/digital-twin` subscribe path now passes token `exp` claim metadata into manager subscription state.
- **Scope guardrails:** No schema migration, no REST/API envelope change, no event-name/payload contract drift, no C5/C6 boundary change, and fail-open delivery semantics for non-expired sessions preserved.
- **Validation:** Scoped Ruff passed; targeted digital-twin/simulation/ws tests passed; full backend regression passed.

## [2026-08-12] - Vertical Slice 4 Step 4 (Digital Twin Scenario-Validation Handoff Baseline)

- **Implemented:** Started executable Digital Twin baseline integration by adding a simulation validation handoff API path that queues deterministic `simulation.started` events and feeds `/ws/digital-twin` scene deltas.
- **Baseline API handoff:** Added `POST /api/v1/simulations/start` (`202 Accepted`) in `backend/app/api/v1/simulation.py`, returning canonical envelope payload with queued handoff state (`simulation_id`, `scenario_id`, `risk_gate`, `validation.pipeline_stage`).
- **Simulation service layer:** Added `backend/app/modules/simulation/service.py` with deterministic scenario-id derivation, ADR-008 policy metadata (`policy_reference=ADR-008`), required check defaults, and fail-open queue fallback (`queue_status=deferred`, `warning=event_queue_unavailable`).
- **Event + WS integration:** Registered `simulation` stream in publisher/bus and extended ws push consumer routing (`simulation.started`, `simulation.completed`) to `/ws/digital-twin` scene deltas via new `DigitalTwinWSManager` and `/ws/digital-twin` endpoint wiring.
- **Operational runbook:** Added `docs/project/DigitalTwinScenarioValidationRunbook.md` for handoff/completion operational checks and updated WebSocket/EventAPI docs with digital twin scene-delta contract examples and routing entries.
- **Scope guardrails:** No schema migrations, no C5/C6 drift, no envelope drift, and fail-open runtime behavior preserved on queue publish failures.
- **Validation:** Scoped Ruff passed; targeted unit/integration tests passed; full backend regression passed (`255 passed`).

## [2026-08-12] - Vertical Slice 4 Step 3 (Deferred Topology Endpoints Governed Design Start)

- **Implemented:** Started governed implementation design for deferred topology analysis endpoints under C6 by adding a dedicated VS4 design handoff document and expanding non-routability regression coverage.
- **Design handoff artifact:** Added `docs/project/TopologyDeferredEndpointsDesign-VS4.md` with module impact boundaries, API contract notes, event/data governance notes, risk controls, and explicit implementation-start exit criteria.
- **C6 enforcement hardening:** Extended deferred endpoint non-routability integration coverage with additional method/path variants (`GET /api/v1/topology/reconcile`, `POST /api/v1/topology/impact/{id}`) to reduce accidental route activation risk.
- **Scope guardrails:** Design + tests only; no deferred endpoint registration, no API envelope changes, no schema migration, and no C5/C6 contract drift.
- **Validation:** Scoped Ruff passed; targeted network endpoint integration tests passed; full backend regression passed (`234 passed`).

## [2026-08-12] - Vertical Slice 4 Step 2 (Runtime Adapter SLO Alerting + Runbook Operationalization)

- **Implemented:** Operationalized runtime adapter SLO posture into alert lifecycle signaling by emitting `alert.generated` and `alert.resolved` on SLO alert-state transitions from telemetry health internals.
- **State handling:** Added persisted counter state `runtime_adapter_slo_alert_active` to prevent duplicate alert emission and to ensure deterministic activation/recovery transition behavior.
- **Alert payload/runbook metadata:** Alert payload now carries severity/reason, anomaly flags, snapshot counters, threshold constants, and runbook metadata (`runbook_reference`, `runbook_version`, `runbook_playbook`) for operator response linkage.
- **Runbook delivery:** Added `docs/project/TelemetryRuntimeAdapterRunbook.md` with playbooks for combined threshold pressure, reason-frequency pressure, transition-frequency pressure, and recovery validation.
- **Fail-open safety:** Counter state persistence and alert publish failures remain warning-only; telemetry health response and existing runtime reliability semantics remain unchanged.
- **Scope guardrails:** No REST/WebSocket envelope drift, no schema migration changes, no C5/C6 scope drift, and no new endpoint additions.
- **Validation:** Scoped Ruff passed; targeted telemetry counters/query/endpoints tests passed; full backend regression passed (`234 passed`).

## [2026-08-12] - Vertical Slice 4 Step 1 (Vendor-Facing Runtime Adapter Increment Baseline)

- **Implemented:** Delivered the first VS4 vendor-facing runtime adapter increment by extending factory-controlled runtime modes with deterministic `snmp` and `grpc` adapter baselines.
- **Adapter mode expansion:** Added `SNMPRuntimeTelemetryAdapter` and `GRPCRuntimeTelemetryAdapter` plus shared deterministic sample builder wiring so both modes emit canonical telemetry payloads through the existing runtime poll path.
- **Operational metadata:** SNMP mode now emits deterministic vendor-facing metadata tags (`target`, `oid`) and gRPC mode emits (`endpoint`, `method`) while preserving stable ownership UUID derivation and canonical payload structure.
- **Startup/config wiring:** Extended runtime adapter environment/settings controls (`TELEMETRY_RUNTIME_ADAPTER_SNMP_*`, `TELEMETRY_RUNTIME_ADAPTER_GRPC_*`) and passed them through lifespan factory construction without changing collector retry/backoff or fail-open startup semantics.
- **Scope guardrails:** No REST/WebSocket envelope changes, no schema migration changes, no C5/C6 contract drift, and no new event contract surface.
- **Validation:** Scoped Ruff passed; targeted telemetry scaffold + startup integration tests passed; full backend regression passed (`226 passed`).

## [2026-08-12] - Vertical Slice 3 Step 28 (Digital Twin Planning Closure + VS3 Completion)

- **Implemented:** Closed remaining VS3 planning work by finalizing Digital Twin baseline integration/scenario planning handoff for next slice and marking VS3 complete in sprint tracking.
- **Planning closure outcome:** VS3 completion now includes adapter-path expansion beyond stub, runtime backpressure/SLO hardening completion, C6 deferred topology governance closure, and explicit VS4-ready execution candidates.
- **Governance check:** C6 deferred topology endpoint non-routability remains enforced and covered; Digital Twin work remains in planning handoff scope (no premature API/schema/runtime contract drift).
- **Scope guardrails:** Documentation/sprint-state closure only; no REST route/envelope changes, no schema migrations, no runtime behavior changes.
- **Validation:** Scoped Ruff passed (touched test/docs scope), targeted deferred-topology integration tests passed, full backend `pytest` regression passed (`222 passed`).

## [2026-08-12] - Vertical Slice 3 Step 27 (C6 Deferred Topology Planning/Governance Closure)

- **Implemented:** Completed VS3 deferred topology planning/governance closure under C6 by hardening explicit non-routability coverage for deferred endpoint path variants.
- **Regression hardening:** Added integration coverage for deferred path-pattern routes (`/api/v1/topology/impact/{id}`, `/api/v1/topology/reconcile/full`) to ensure C6 deferred endpoints remain non-routable beyond base-path checks.
- **Governance outcome:** Confirms deferred topology analysis endpoints remain intentionally absent from router registration while preserving existing graph/node endpoint availability.
- **Scope guardrails:** Test + planning closure only; no REST/API envelope changes, no schema migrations, no C5/C6 contract drift (C6 remains enforced).
- **Validation:** Scoped Ruff passed; targeted deferred-topology integration tests passed; full backend `pytest` regression passed (`220 passed`).

## [2026-08-12] - Vertical Slice 3 Step 26 (Runtime Adapter Dropped-Sample Backpressure Hardening)

- **Implemented:** Added dropped-sample runtime adapter counter and observability wiring to harden backpressure/SLO diagnostics.
- **Counter contract:** Introduced `runtime_adapter_dropped_samples` in telemetry health counter snapshot and incremented it on invalid sample drops and ingest-failure drops in runtime poll path.
- **SLO snapshot/rollup visibility:** Extended runtime adapter SLO snapshot and rollup metadata with `dropped_samples`, and added anomaly warning branch `telemetry_health_runtime_adapter_dropped_samples_detected`.
- **Anomaly semantics:** Dropped samples now contribute deterministic anomaly reason metadata (`dropped_samples_detected`) used by streak transition/rollup trend internals.
- **Fail-open safety:** Counter updates and warning branches remain warning-only/non-fatal; runtime retry/backoff and API health response contracts remain unchanged.
- **Scope guardrails:** No REST route/envelope changes, no schema migrations, no C5/C6 drift.
- **Validation:** Scoped Ruff passed; targeted telemetry counters/scaffold/query + telemetry endpoints tests passed; full backend `pytest` regression passed (`220 passed`).

## [2026-08-12] - Vertical Slice 3 Step 25 (Runtime Adapter Mode Factory Beyond Stub)

- **Implemented:** Advanced runtime adapter path beyond stub by adding configurable production adapter mode selection in startup wiring (`stub` / `seeded`).
- **Adapter expansion:** Added `SeededRuntimeTelemetryAdapter` with deterministic canonical telemetry sample generation (stable UUID ownership keys by sample key) and runtime mode factory `build_production_runtime_adapter(...)`.
- **Startup wiring:** Replaced direct stub instantiation with mode-driven adapter factory in lifespan startup and added runtime adapter environment settings (`TELEMETRY_RUNTIME_ADAPTER_*`) to `Settings` + `.env.example`.
- **Fail-open safety:** Invalid adapter mode values fall back to stub with warning-only diagnostics (`telemetry_runtime_adapter_mode_invalid`); no startup/runtime crash semantics changed.
- **Scope guardrails:** No REST/API envelope changes, no schema migrations, no C5/C6 drift; runtime poll retry/backoff and observability contracts remain intact.
- **Validation:** Scoped Ruff passed; targeted telemetry scaffold + startup integration tests passed; full backend `pytest` regression passed (`219 passed`).

## [2026-08-12] - Vertical Slice 3 Step 24 (Runtime Adapter Cooldown-Correlation Snapshot Aggregation)

- **Implemented:** Added internal-only deterministic cooldown-correlation snapshot aggregation for runtime adapter trend-threshold dimensions in telemetry health internals.
- **Correlation snapshot event:** Added `telemetry_health_runtime_adapter_slo_threshold_correlation_snapshot` with bounded-window aggregate metadata: `latest_threshold_trigger_state`, per-dimension `cooldown_transition_phase_counts`, `cooldown_summary_window_state`, and `latest_cooldown_summary_state`.
- **Threshold contract wiring:** Extended threshold evaluation return contract to carry per-dimension `updated_state`, deterministic `latest_threshold_trigger_state`, and normalized cooldown transition phase (`enter-cooldown`, `cooldown-suppressed`, `cooldown-expired-reemit`, `cooldown-cleared-recovery`) for correlation aggregation.
- **Fail-open safety:** Added warning-only correlation fallback branches (`...correlation_snapshot_state_write_failed`, `...correlation_snapshot_state_read_failed`, `...correlation_snapshot_log_failed`) while preserving Step 16-23 behavior/contracts and runtime poll-action semantics.
- **Scope guardrails:** Internal logging/state-only increment; no REST route/envelope changes, no schema migrations, no C5/C6 drift.
- **Validation:** Scoped Ruff passed; targeted telemetry query + scaffold + endpoints tests passed; full backend `pytest` regression passed (`216 passed`).

## [2026-08-11] - Vertical Slice 3 Step 23 (Runtime Adapter Cooldown-Transition Event Visibility)

- **Implemented:** Added internal-only deterministic cooldown-transition event visibility for runtime adapter threshold dimensions in telemetry health internals.
- **Transition branches:** Added explicit transition events for cooldown lifecycle phases: `enter-cooldown`, `cooldown-suppressed`, `cooldown-expired-reemit`, and `cooldown-cleared/recovery`.
- **Deterministic metadata:** Transition events now include per-dimension deterministic state metadata (`threshold_dimension`, `threshold_value`, `max_observed_value`, `crossed_values`, `previous/current threshold_crossed`, `previous/current reads_since_last_crossed_emit`, `cooldown_reads`, `recovery_transition`, `cooldown_re_emitted`).
- **Fail-open safety:** Added warning-only fail-open fallbacks for cooldown-transition state read/write failures and transition event log failures while preserving Step 16-22 behavior/contracts and runtime poll-action semantics.
- **Scope guardrails:** Internal logging-only change; no REST route/envelope changes, no schema migrations, no C5/C6 drift.
- **Validation:** Scoped Ruff passed; targeted telemetry query + scaffold/endpoints tests passed; full backend `pytest` regression passed (`210 passed`).

## [2026-08-11] - Vertical Slice 3 Step 22 (Runtime Adapter Trend-Threshold Cooldown-State Observability Summary)

- **Implemented:** Added internal-only cooldown-state observability summary logging for runtime adapter SLO trend-threshold internals (`telemetry_health_runtime_adapter_slo_trend_threshold_cooldown_summary`).
- **Summary metadata:** Emits deterministic per-dimension cooldown state (`transition_frequency_cooldown`, `reason_frequency_cooldown`) including `initialized`, `threshold_crossed`, `reads_since_last_crossed_emit`, `next_crossed_emit_in_reads`, `cooldown_active`, plus window and cooldown constants.
- **Fail-open safety:** Added isolated warning-only cooldown-summary fallback branches (`...trend_threshold_cooldown_summary_state_read_failed`, `...trend_threshold_cooldown_summary_log_failed`) while preserving existing Step 21 threshold cooldown/recovery and Step 20 evaluation fail-open behavior.
- **Scope guardrails:** Internal logging-only increment; no REST route/envelope changes, no schema migrations, no C5/C6 drift, and runtime poll-action semantics unchanged.
- **Validation:** Scoped Ruff passed; targeted telemetry query/scaffold/endpoints tests passed; full backend `pytest` regression passed (`205 passed`).

## [2026-08-11] - Vertical Slice 3 Step 21 (Runtime Adapter SLO Trend-Threshold Cooldown and Recovery Visibility)

- **Implemented:** Added internal threshold cooldown/hysteresis state for runtime adapter SLO trend-threshold evaluation in telemetry health read-path internals.
- **Cooldown behavior:** Threshold-crossed events are emitted on initial crossing, suppressed during cooldown reads (`3`), and re-emitted after cooldown expiry while still crossed (`...threshold_crossed_suppressed` + re-emitted crossed branch).
- **Recovery visibility:** Not-crossed branch now emits explicit transition semantics (`recovery_transition=true`) when a previously crossed threshold recovers.
- **Fail-open safety:** Added isolated warning-only cooldown state failure branches (`...trend_threshold_cooldown_state_read_failed`, `...trend_threshold_cooldown_state_write_failed`) while preserving existing threshold-evaluation and trend-window fail-open semantics.
- **Scope guardrails:** Internal-only logging/state changes; no REST route/envelope changes, no schema migrations, no C5/C6 drift, and runtime poll-action semantics unchanged.
- **Validation:** Scoped Ruff passed; targeted telemetry query/scaffold/endpoints tests passed; full backend `pytest` regression passed (`201 passed`).

## [2026-08-11] - Vertical Slice 3 Step 20 (Runtime Adapter SLO Trend-Threshold Trigger Visibility)

- **Implemented:** Added deterministic internal threshold-trigger visibility on runtime adapter SLO trend-window summaries for transition-frequency and anomaly-reason-frequency counters.
- **Threshold behavior:** Emits explicit crossed/not-crossed structured branches for both dimensions (`...transition_frequency_threshold_crossed|not_crossed`, `...reason_frequency_threshold_crossed|not_crossed`) using configured deterministic thresholds.
- **Operational semantics:** Threshold evaluation consumes existing Step 19 trend summary output and does not alter trend-window storage, rollup severity mapping, or streak persistence behavior from Steps 16-19.
- **Fail-open safety:** Added isolated warning-only evaluation failure branch (`telemetry_health_runtime_adapter_slo_trend_threshold_evaluation_failed`) while preserving existing fail-open handling for counter/trend state read-write/log failures.
- **Scope guardrails:** Internal-only logging changes; no REST route/envelope changes, no schema migrations, and runtime poll-action semantics unchanged.
- **Validation:** Scoped Ruff passed; targeted telemetry query/scaffold/endpoints tests passed; full backend `pytest` regression passed (`197 passed`).

## [2026-08-11] - Vertical Slice 3 Step 19 (Runtime Adapter SLO Trend-Window Transition Visibility)

- **Implemented:** Added bounded internal runtime adapter SLO trend-window tracking in telemetry health read-path internals and emitted `telemetry_health_runtime_adapter_slo_trend_window_summary`.
- **Window behavior:** Maintains an in-process bounded rolling window (`max_window_size=10`) over recent health reads and reports `window_size` plus deterministic capped transition aggregation.
- **Trend summary:** Emits severity transition counts (`from->to`) and anomaly reason frequency aggregation across the active window.
- **Fail-open safety:** Added isolated warning-only branches for trend-window state write/read/log failures (`...state_write_failed`, `...state_read_failed`, `...trend_window_log_failed`) without affecting health response behavior.
- **Compatibility guardrails:** Step 16 persisted streak continuity, Step 17 transition metadata, and Step 18 rollup severity semantics remain unchanged; no REST route/envelope changes, no schema migrations, and runtime poll-action behavior unchanged.
- **Validation:** Scoped Ruff passed; targeted telemetry query/scaffold/endpoints tests passed; full backend `pytest` regression passed (`195 passed`).

## [2026-08-11] - Vertical Slice 3 Step 18 (Runtime Adapter SLO Health Rollup Severity Visibility)

- **Implemented:** Added a single internal-only runtime adapter SLO health rollup log branch in telemetry health read-path internals (`telemetry_health_runtime_adapter_slo_rollup`).
- **Rollup payload:** Emits `runtime_adapter_anomaly_streak`, `runtime_sustained_failure_active`, `ingest_attempts`, `ingest_failures`, `invalid_samples`, computed `invalid_sample_ratio`, `last_batch_size`, and `anomaly_reason_flags`.
- **Severity mapping:** Added explicit operations-only severity mapping (`ok`, `degraded`, `critical`) with deterministic reason tags (`runtime_adapter_healthy`, `runtime_adapter_anomaly_detected`, `anomaly_streak_threshold_exceeded`, `runtime_sustained_failure_active`).
- **Compatibility guardrails:** Step 16 persisted streak continuity and Step 17 transition metadata semantics remain unchanged; no REST route/envelope changes, no schema migrations, and runtime poll-action behavior unchanged.
- **Fail-open safety:** Rollup emission remains inside existing safe logging branch; counter snapshot fallback and logging failure handling remain non-fatal.
- **Validation:** Scoped Ruff passed; targeted telemetry query/scaffold/endpoints tests passed; full backend `pytest` regression passed (`191 passed`).

## [2026-08-11] - Vertical Slice 3 Step 17 (Runtime Adapter Anomaly Streak Transition Metadata)

- **Implemented:** Added runtime adapter anomaly streak transition metadata visibility in telemetry health read-path internals (`previous_streak`, `current_streak`, `anomaly_reason_flags`).
- **Transition semantics:** Transition logs now emit on increment, reset, and unchanged branches via `telemetry_health_runtime_adapter_anomaly_streak_transition`, with warning level for increasing streak and info level otherwise.
- **Reason flags:** Added explicit anomaly reason tagging for transition context (`ingest_failures_detected`, `invalid_sample_ratio_exceeded`) while preserving existing anomaly warning events.
- **Fail-open safety:** Transition metadata remains internal-only and logging/counter failure handling stays non-fatal; no REST route/envelope changes, no schema migrations, and runtime poll-action semantics unchanged.
- **Validation:** Scoped Ruff passed; targeted telemetry query/scaffold/endpoints tests passed; full backend `pytest` regression passed (`188 passed`).

## [2026-08-11] - Vertical Slice 3 Step 16 (Persisted Runtime Adapter Anomaly Streak)

- **Implemented:** Persisted runtime adapter anomaly streak in Redis-backed telemetry health counters and wired health read-path streak load/store through `TelemetryHealthCounterService`.
- **Continuity behavior:** Streak continuity now comes from counter snapshot state (cross-instance safe) instead of process-local in-memory state.
- **Fail-open safety:** Counter read failures still fall back to zero snapshot; counter write failures during streak persistence are warning-only (`telemetry_health_runtime_adapter_anomaly_streak_persist_failed`) and non-fatal.
- **Scope guardrails:** Internal-only behavior; no REST route/envelope changes, no schema migrations, and runtime poll-action semantics unchanged.
- **Validation:** Scoped Ruff passed; targeted telemetry counters/query/scaffold/endpoints tests passed; full backend `pytest` regression passed (`187 passed`).

## [2026-08-11] - Vertical Slice 3 Step 15 (Runtime Adapter Anomaly Streak Visibility)

- **Implemented:** Added rolling runtime adapter anomaly streak tracking in telemetry health read-path internals.
- **Trend behavior:** Streak increments on consecutive anomaly snapshots (threshold breaches) and resets to zero on a healthy snapshot.
- **Observability:** Uses structured warning/info logs only (`...anomaly_streak_incremented`, `...anomaly_streak_reset`) with no external contract changes.
- **Scope guardrails:** No REST route/envelope changes, no schema migrations, and runtime poll-action semantics unchanged.
- **Fail-open safety:** Snapshot/counter failure path remains warning-only and non-fatal; streak logic remains contained to internal read-path state.
- **Validation:** Scoped Ruff passed; targeted telemetry query/scaffold/endpoints tests passed; full backend `pytest` regression passed (`184 passed`).

## [2026-08-11] - Vertical Slice 3 Step 14 (Runtime Adapter Backpressure Anomaly Logging Thresholds)

- **Implemented:** Added internal-only anomaly warning thresholds in telemetry health runtime adapter SLO logging.
- **Threshold behavior:** Warns when `ingest_failures > 0` with explicit zero-attempt guard and warns when `invalid_samples` ratio exceeds threshold (`> 0.25`).
- **Scope guardrails:** No REST route changes, no API envelope changes, no schema migrations, and no runtime poll-action semantic changes.
- **Fail-open safety:** Threshold/anomaly checks are contained in existing safe logging path; logging failures remain warning-only and non-fatal.
- **Validation:** Scoped Ruff passed; targeted telemetry query/scaffold/endpoints tests passed; full backend `pytest` regression passed (`181 passed`).

## [2026-08-11] - Vertical Slice 3 Step 13 (Runtime Adapter SLO Snapshot Visibility)

- **Implemented:** Extended telemetry health read-path internals to build and log runtime adapter SLO snapshot fields (`last_batch_size`, `invalid_samples`, `ingest_attempts`, `ingest_failures`) from existing runtime adapter counters.
- **Scope guardrails:** No REST route changes, no API envelope changes, and no schema migration changes; runtime poll-action semantics are unchanged.
- **Fail-open safety:** Invalid/malformed runtime adapter counter values are sanitized to zero with structured warnings, and SLO snapshot logging failures are warning-only and non-fatal.
- **Validation:** Scoped Ruff passed; targeted telemetry query/scaffold/endpoints tests passed; full backend `pytest` regression passed (`178 passed`).

## [2026-08-10] - Vertical Slice 3 Step 12 (VS3 Step 12 Runtime Adapter Observability Counters)

- **Implemented:** Added runtime adapter observability counters for backpressure and ingest quality (`runtime_adapter_last_batch_size`, `runtime_adapter_invalid_samples`, `runtime_adapter_ingest_attempts`, `runtime_adapter_ingest_failures`).
- **Poll-path instrumentation:** Runtime poll action now records batch-size, invalid-sample increments, ingest-attempt increments, and ingest-failure increments while preserving retry behavior.
- **Fail-open safety:** Counter update failures in runtime path are isolated and logged (`telemetry_runtime_adapter_counter_update_failed`) without crashing startup/runtime/shutdown.
- **Validation:** Scoped Ruff, targeted telemetry counter/scaffold tests, and full backend regression passed.
- **Commit:** `7ed0821`.

## [2026-08-10] - Vertical Slice 3 Step 11 (Production Adapter Stub Wiring)

- **Implemented:** Wired first minimal production collector adapter stub behind runtime poll action path under existing retry/runtime loop scaffolding.
- **Reliability alignment:** Reused established retry/backoff/runtime loop controls rather than introducing a parallel execution path.
- **Scope safety:** No API route/envelope changes and no schema migrations.
- **Validation:** Scoped Ruff, targeted telemetry startup/scaffold tests, and full backend regression passed.

## [2026-08-10] - Vertical Slice 3 Step 10 (Alerts WS Fanout Observability)

- **Implemented:** Added observability branches for alerts websocket lifecycle fanout outcomes (success/failure) in push-consumer flow.
- **Operational behavior:** Fanout outcome recording preserves fail-open behavior and does not change event delivery semantics.
- **Validation:** Scoped Ruff, targeted websocket push/alerts tests, and full backend regression passed.

## [2026-08-10] - Vertical Slice 3 Step 9 (Alerts WebSocket Fanout)

- **Implemented:** Added minimal `/ws/alerts` delivery path for `alert.generated` and `alert.resolved` via ws push consumer translation.
- **Routing behavior:** Alert lifecycle events are translated to websocket push path without introducing REST/API contract changes.
- **Validation:** Scoped Ruff, targeted websocket-alert tests, and full backend regression passed.

## [2026-08-10] - Vertical Slice 3 Step 8 (Telemetry -> Alert Event Flow)

- **Implemented:** Routed sustained-failure transition events from telemetry consumer to alerting event flow (`alert.generated`, `alert.resolved`).
- **Bus integration:** Added alert stream producer/consumer registration support in event publisher/bus mappings.
- **Fail-open safety:** Malformed payloads, correlation parsing issues, or publish failures are warning-only and non-crashing.
- **Validation:** Scoped Ruff, targeted telemetry consumer/event-contract tests, and full backend regression passed.

## [2026-08-10] - Vertical Slice 3 Step 7 (Audit Transition Event Coverage)

- **Implemented:** Extended audit consumer mapping to capture sustained-failure transition events with `resource_type=telemetry_collector`.
- **Hardening:** UUID parsing and payload shape handling in audit path remain fail-open for malformed events.
- **Validation:** Scoped Ruff, targeted audit/telemetry startup tests, and full backend regression passed.

## [2026-08-10] - Vertical Slice 3 Step 6 (Runtime Transition Internal Events)

- **Implemented:** Added internal transition event emission for runtime sustained failure activation and recovery (`telemetry.collector.sustained_failure_activated`, `telemetry.collector.sustained_failure_recovered`).
- **Emission semantics:** Transition events are emitted only on state change (activation/recovery), not on every failed cycle.
- **Fail-open safety:** Internal event publish failures are warning-only and do not crash collector loop/startup.
- **Validation:** Scoped Ruff, targeted telemetry scaffold tests, and full backend regression passed.

## [2026-08-10] - Vertical Slice 3 Step 5 (Sustained Runtime Failure Health Visibility)

- **Implemented:** Added deterministic sustained runtime failure tracking and health surfacing (`runtime_exhausted_cycles`, `runtime_exhausted_streak`, `runtime_sustained_failure_windows`, `runtime_sustained_failure_active`).
- **Health behavior:** Telemetry health status now reports `degraded` when sustained-failure-active flag is set and returns to `ok` on recovery.
- **Scope safety:** No route/envelope or schema changes; startup/runtime remain fail-open.
- **Validation:** Scoped Ruff and targeted telemetry runtime/health tests passed.

## [2026-08-10] - Vertical Slice 3 Step 4 (Runtime Loop Lifecycle Wiring)

- **Implemented:** Wired collector runtime loop harness into app lifespan orchestration: startup now starts `TelemetryCollectorRunner` with bounded retry and then starts runtime loop when startup succeeds.
- **Safe default poll action:** Added `_telemetry_collector_noop_poll_action()` as the default runtime poll action so loop lifecycle is wired without introducing adapter-specific polling logic.
- **Failure isolation:** Runtime loop start failures are treated as collector startup failures, logged, and collector shutdown is attempted immediately; API startup remains fail-open.
- **Shutdown determinism:** Existing shutdown path now deterministically stops runtime loop through collector stop lifecycle with no dangling loop-task behavior.
- **Scope safety:** No API route/envelope changes, no schema migrations, and no C5/C6 routing changes.
- **Validation:** Scoped Ruff and targeted telemetry startup/lifecycle unit+integration tests passed, including repeated startup/shutdown non-regression coverage.

## [2026-08-10] - Vertical Slice 3 Step 3 (Runtime Collector Loop Harness)

- **Implemented:** Added a minimal runtime loop harness in `TelemetryCollectorRunner` that schedules one poll cycle at a deterministic interval and executes each cycle through `run_single_poll_with_retry()`.
- **Continuation safety:** Exhausted poll cycles log `telemetry_collector_runtime_cycle_exhausted` and loop safely continues to next interval instead of crashing unrelated components.
- **Stop determinism:** Added explicit runtime loop start/stop controls with internal stop-event signaling and task awaiting to avoid dangling runtime tasks during shutdown.
- **Observability:** Structured logs now cover runtime loop started/stopped and already-running guard paths, while retry/recovery/exhaust logs remain emitted by Step 2 retry wrapper.
- **Scope safety:** No API route/envelope changes, no schema migrations, and startup reliability behavior from VS3 Step 1 remains unchanged.
- **Validation:** Scoped Ruff, targeted loop/retry unit tests, and startup non-regression integration tests passed.

## [2026-08-10] - Vertical Slice 3 Step 2 (Runtime Poll Retry Wrapper)

- **Implemented:** Added `TelemetryCollectorRunner.run_single_poll_with_retry()` to wrap one runtime collector poll action with deterministic retry and bounded exponential backoff.
- **Determinism:** Runtime retries reuse `compute_bounded_backoff_seconds()` and accept injected `sleep` for deterministic unit testing of retry timing.
- **Failure visibility:** Retry scheduling and retry exhaustion are logged with structured fields; exhaustion returns `False` and does not raise by default, preserving isolation from unrelated components.
- **Recovery behavior:** Poll success after transient failures is explicitly covered and logged via recovery branch behavior.
- **Scope safety:** No API route/envelope changes, no schema migrations, and no startup lifecycle drift from VS3 Step 1.
- **Validation:** Scoped Ruff checks, targeted unit tests for retry/exhaust/recovery, and startup non-regression integration tests passed.

## [2026-08-10] - Vertical Slice 3 Step 1 (Telemetry Collector Reliability Baseline)

- **Implemented:** Added bounded exponential retry/backoff startup path for telemetry collector via `TelemetryCollectorRunner.start_with_retry()` and wired lifespan startup to use it.
- **Determinism:** Retry math is isolated in `compute_bounded_backoff_seconds()` with explicit cap behavior and unit coverage for retry intervals and exhaustion/success branches.
- **Failure visibility:** Startup retry scheduling and retry exhaustion are logged, while exhausted retries remain startup-safe (API continues boot without collector runner).
- **Scope safety:** No REST/WebSocket contract changes, no migration/schema changes, and no C5/C6 routing changes.
- **Validation:** Scoped Ruff and targeted telemetry unit/integration tests for startup/retry behavior passed.

## [2026-08-10] - Vertical Slice 2 Step 8 (Telemetry Health Counters + WS Fanout)

- **Implemented:** Added Redis-backed telemetry operational counter service (`ingested_events`, `persisted_events`, `fanout_events`, `dropped_events`) and wired counter updates into ingestion/persistence/fanout branches.
- **Health behavior:** `GET /api/v1/telemetry/health` now reads real dropped-event counter state from Redis-backed snapshot (with safe fallback behavior if counter reads fail), preserving canonical API envelope.
- **Streaming behavior:** Added `/ws/telemetry` endpoint and telemetry WebSocket manager path; telemetry deltas are pushed only after successful persistence of `telemetry.metric.ingested` events.
- **Failure isolation:** WebSocket fanout/counter failures are logged and counted as dropped events without breaking telemetry persistence commits or event bus retry semantics for SQL failures.
- **Validation:** Full backend test suite passed (`121 passed`), Step-8-scoped Ruff checks passed for all changed files, and telemetry/startup/deferred-endpoint regressions remained green. Repository-wide Ruff still reports pre-existing lint debt outside VS2 Step 8 scope.

## [2026-08-09] - Vertical Slice 2 Step 7 (Telemetry Read APIs)

- **Implemented:** Added telemetry read endpoints `GET /api/v1/telemetry/history`, `GET /api/v1/telemetry/device/{id}`, and `GET /api/v1/telemetry/health` with canonical `{success, data, meta, errors}` envelope.
- **Read model behavior:** Queries are served from `telemetry_records` with deterministic ordering (`observed_at` desc, `record_id` desc), pagination (`page`, `page_size`), and optional metric/network/workspace filters where applicable.
- **Health contract:** `telemetry/health` returns baseline ingest telemetry (`status`, `ingest_lag_ms`, `dropped_events`, `latest_observed_at`, `total_records`) without changing ingestion pipeline behavior.
- **Validation:** Step-7-scoped Ruff checks, telemetry unit tests, and integration endpoint tests passed; startup collector lifecycle remained green and deferred topology paths remained non-routable.

## [2026-08-09] - Vertical Slice 2 Step 6 (Telemetry Persistence Baseline)

- **Implemented:** Added `telemetry_records` persistence baseline via Alembic `0002` migration and Telemetry module model/repository write path.
- **Consumer behavior:** `telemetry.metric.ingested` now persists normalized payloads idempotently by `event_id`; malformed payloads are logged/skipped and SQL failures are logged/re-raised for bus retry/dead-letter handling.
- **Schema/indexing:** Table includes event/correlation IDs, ownership IDs (`device_id`, `network_id`, `workspace_id`), metric/value/unit/source/tags, and timestamp fields with query indexes on device/network/workspace/metric/observed_at.
- **Validation:** Step-6-scoped Ruff, unit tests, and integration tests passed; startup collector lifecycle tests remained green (no Step 5 regression).

## [2026-08-09] - Vertical Slice 2 Step 5 (Telemetry Ingestion Scaffold)

- **Implemented:** Added internal telemetry ingestion scaffold with collector lifecycle wiring (`start`/`stop`), payload normalization, and internal publish path via Redis Streams event bus.
- **Event contract:** Telemetry ingestion now emits `telemetry.metric.ingested` to `stream:telemetry`; consumer handling is intentionally parse/log-only (no persistence side effects in VS2 Step 5).
- **Startup behavior:** Lifespan startup initializes and starts collector runner; failures are caught and logged so API startup remains healthy/no-op safe.
- **Validation:** Ruff checks and targeted telemetry unit/integration tests passed, including startup lifecycle coverage and C6 deferred topology endpoint non-regression checks.

## [2026-08-09] - Vertical Slice 2 Step 4 (Topology Node Neighbours)

- **Implemented:** Added `GET /api/v1/topology/nodes/{device_id}` with default `depth=1`, canonical envelope, and deterministic neighbour ordering.
- **Payload behavior:** Endpoint returns `node` plus `neighbours[]`, where each neighbour includes required relation metadata (`edge_type`, `direction`).
- **Validation:** Ruff checks and targeted unit/integration tests passed; existing graph pagination remained intact and deferred C6 endpoints still return 404.

## [2026-08-09] - Vertical Slice 2 Step 3 (Topology Graph Pagination)

- **Implemented:** Added paginated `GET /api/v1/topology/graph` with `limit` and `cursor` query parameters, deterministic `device_id` ascending ordering, and `meta.next_cursor` for continuation.
- **Service behavior:** Pagination is node-based; `next_cursor` is returned only when more nodes exist. Edge output is constrained to edges whose endpoints are both present in the current node page.
- **Validation:** Ruff checks and targeted unit/integration tests for topology pagination passed; deferred C6 endpoints remain non-routable (404).

## [2026-08-06] - Vertical Slice 1 Implementation Closure

- **Implemented:** Backend modular monolith scaffolded — FastAPI, async SQLAlchemy 2.0 (lazy engine), Redis Streams event bus, Neo4j driver.
- **Identity Module:** User/Role/Permission models, AuthService (JWT + bcrypt), rate-limiting via Redis incr/expire, jti deny-list revocation. `passlib` replaced with direct `bcrypt 5.x` calls (passlib 1.7.4 incompatible with bcrypt 4.0+).
- **Organization Module:** Organization/Workspace/OrgMember models, OrgService, WorkspaceService. Boundary enforced: cross-module references stored as UUID columns only (ADR-004).
- **Network Module:** Network/Device models, NetworkService, DeviceService. C5 constraint enforced — `workspace_id` validated via `WorkspaceService.get_active_workspace()`, no SQL cross-joins.
- **Event Bus:** Redis Streams consumer loop, three handler registries (audit, topology, ws_push) merged and dispatched per stream group. Event naming follows `module.entity.action` convention (EventAPI.md).
- **WebSocket:** `/ws/topology` JWT-authenticated endpoint + `ConnectionManager` singleton. Canonical channel per Telemetry.md §4.
- **API Routers:** 5 REST routers (auth, orgs, networks, topology, audit) — all responses use canonical `{success, data, meta, errors}` envelope (API_STANDARD.md §2). HTTPException handler added to main.py to wrap all 4xx/5xx in envelope.
- **Exception Handlers:** JWTError → 401, HTTPException → envelope, Exception → 500. `_http_error_code()` maps status codes to canonical error code strings.
- **Alembic Migration 0001:** `roles`, `permissions`, `users`, `user_roles`, `audit_logs`, `organizations`, `workspaces`, `org_members`, `networks`, `devices` — applied to live PostgreSQL 16.14.
- **Seed data in migration:** 3 default roles (Admin, Operator, Read-Only) + 6 permissions seeded.
- **Test Suite:** 68/68 tests passing — 39 unit (service layer, security, JWT) + 29 integration (HTTP routing, envelope shape, C5/C6 constraints). Zero warnings after httpx2 install.
- **C5 verified:** `TestNetworkService::test_c5_no_workspace_repository_direct_call` confirms no direct repository call in cross-module path.
- **C6 verified:** `TestC6DeferredEndpointsAbsent` confirms /neighbors, /impact, /reconcile return 404; /topology/graph returns non-404.
- **Infrastructure:** Docker services confirmed healthy — PostgreSQL 16.14, Neo4j 5.25-community (APOC enabled), Redis 7-alpine. `./scripts/dev-start.sh` operational.
- **Technical Fixes Recorded:**
  - `passlib` → direct `bcrypt` (bcrypt 4.0+ broke passlib's `__about__` introspection)
  - structlog `PrintLoggerFactory` → `stdlib.LoggerFactory` (PrintLogger has no `.name`)
  - `AsyncMock.add` → `MagicMock` (SQLAlchemy `session.add()` is synchronous)
  - `fakeredis.aioredis.FakeRedis` → `fakeredis.FakeAsyncRedis` (extras merged in v2.37)
  - `redis.setex()` → `redis.set(..., ex=ttl)` (setex deprecated in fakeredis 2.37)

## [2026-08-06] - Vertical Slice 1 Design Closure & Documentation Hardening

- **Errata Corrected:** Re-read of canonical docs revealed three files (`constitution.md`, `API_STANDARD.md`, `Authentication.md`) were incorrectly claimed as empty in the initial design pass. All three are fully populated. The API envelope field was corrected from `"error"` (invented) to `"errors"` (canonical, per `API_STANDARD.md` §2).
- **Decision:** WebSocket channel ambiguity resolved — Option A adopted. `/ws/topology` added as a canonical channel in `docs/features/Telemetry.md` §4 to keep topology structural events domain-separated from metric telemetry.
- **Expanded:** `docs/api/WebSocket.md` replaced from scope stub to full normative specification: channel registry, JWT auth model, subscription protocol, delta payload format (add/update/remove), and backpressure/error signaling with error code table.
- **Expanded:** `docs/api/EventAPI.md` replaced from scope stub to full normative specification: naming convention (`module.entity.action`), mandatory envelope with field table, payload governance rules, delivery/retry semantics, event-to-WS-channel routing table.
- **Updated:** `docs/features/Authentication.md` §8 added — JWT claim baseline covering required claims (`sub`, `email`, `roles`, `permissions`, `iat`, `exp`, `jti`), optional claims (`org_id`, `workspace_id`), single-org-per-token scoping behaviour, RBAC evaluation order, `jti`-based token revocation, and claims exclusion list.
- **Created:** `docs/features/Organization.md` — full PRD for Organization & Workspace Management module. Covers purpose, requirements, 13 API endpoints, 3 PostgreSQL tables, 8 event contracts, 4 risks, 8 acceptance criteria, and testing requirements. Resolves blocking condition C2 from architecture review gate.
- **Updated:** `docs/project/CurrentSprint.md` — all design closure tasks marked complete; implementation awaiting approval.
- **Updated:** `docs/project/DecisionLog.md` — WebSocket channel decision and JWT scoping model recorded.
- **Architecture Review Gate re-run:** Result upgraded to APPROVE — all four blocking conditions (C1–C4) resolved by this session's documentation changes.


- **Action:** Consolidated database rules into `database.md`, added `architecture-guardrails.md`, and refactored `constitution.md` to remove information duplication[cite: 1].
- **Relocation:** Moved project tracking documents into `docs/project/`.

## [2026-08-05] - Documentation Baseline & Agent Alignment
- **Action:** Added canonical chapter index, split chapter mirror files, and standardized diagram fencing for cleaner rendering.
- **Action:** Added `AGENTS.md` and `.agent.md` compatibility entry for consistent agent discovery.
- **Action:** Updated workflow approval gates and rule path scopes to align with repository layout.

## [2026-08-05] - Pre-Coding Governance Hardening
- **Action:** Added docs structure map and phase tracker (`docs/README.md`) covering architecture, adr, api, features, project, and standards.
- **Action:** Added feature PRD baselines for Topology, Simulation, and Telemetry plus ADR-001/002/003.
- **Action:** Updated context loading to prioritize `docs/project/DevelopmentJournal.md` and added context-safety standard (`docs/standards/AgentExecutionStandard.md`).
- **Action:** Enforced strict design approval handoff in `design-feature` and explicit design artifact verification in `implement-feature`.

## [2026-08-05] - Documentation Quality Audit & Traceability Alignment
- **Action:** Audited docs/rules/workflows for single-responsibility scope, cross-reference quality, and placeholder leakage.
- **Action:** Added foundational ADRs ADR-004 to ADR-008 (DDD ownership, backend stack baseline, event bus communication, AIOS + Digital Twin pillars, simulation-before-deployment policy).
- **Action:** Updated workflows to explicitly load task-relevant standards and `docs/api/API_STANDARD.md`.
- **Action:** Restructured roadmap/milestones around a milestone-driven sequence plus first vertical slice validation path.

## [2026-08-05] - Architecture Review Gate & Decision Log
- **Action:** Added `.agents/workflows/architecture-review.md` as a pre-merge design gate for significant features.
- **Action:** Added `docs/project/DecisionLog.md` for lightweight decision traceability when ADR overhead is unnecessary.
