# Decision Log

Lightweight chronological notes for decisions that do not require a full ADR.

## 2026-08-14
### VS15 Step 2: Frontend Burst-Resilience Coverage via Deterministic Store + Reliability E2E Tests
Decision: Implement VS15 Step 2 as frontend test-surface hardening only by extending realtime-store unit coverage and reliability e2e high-volume fixtures, without altering application contracts or runtime behavior.
Reason:
- VS15 scope requires post-M10 synthetic-load continuity evidence across both backend and frontend while preserving API/channel stability.
- Existing realtime store and reliability route already own alert-burst behavior, so extending tests in-place avoids architecture drift and refactor risk.
- Deterministic retention/order assertions at store level plus high-volume operator-flow e2e coverage provides bounded confidence for burst handling.
Impact:
- Updated `frontend/src/features/realtime/store.test.ts` with `250`-delta burst assertions for `200`-item cap, newest-first ordering, and deduplicated in-place update semantics.
- Updated `frontend/tests/e2e/vs3-reliability.spec.ts` with a `180`-alert fixture scenario validating filter precision, status-segment transitions, and action-control states under heavy alert volume.
- Recorded full validation evidence across frontend gates and backend regression to keep VS15 step-level quality requirements intact.
Assumptions:
- Burst-resilience confidence for VS15 Step 2 is satisfied by deterministic unit + e2e coverage expansion without introducing external load generators in frontend scope.
- Existing large `three` chunk warning remains accepted baseline and is tracked as ongoing optimization continuity, not a VS15 blocker.
Related:
- `frontend/src/features/realtime/store.test.ts`
- `frontend/tests/e2e/vs3-reliability.spec.ts`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS15 Step 1: Activate Post-M10 Synthetic Telemetry Load Campaign as Test-Only Burst Coverage
Decision: Implement the first VS15 executable increment as integration-test-only synthetic telemetry burst coverage that validates ingest/persist/fanout counter continuity at macro batch size without changing runtime contracts.
Reason:
- `CurrentSprint.md` explicitly deferred macro-scale synthetic load work beyond VS14 and left the next slice undefined; VS15 must begin by converting that deferred item into executable evidence.
- Existing telemetry module already provides deterministic event flow and health counters, enabling bounded load simulation through tests without production code churn.
- A test-only first step minimizes risk while preserving API envelope stability, C5/C6 constraints, and fail-open runtime behavior.
Impact:
- Added `backend/tests/integration/test_telemetry_synthetic_load.py` to drive a `120`-event synthetic burst through `TelemetryIngestionService` + `handle_telemetry_event(...)` and assert counter integrity (`ingested/persisted/fanout`) with zero drops.
- Updated `CurrentSprint.md` to define VS15 scope boundaries, acceptance criteria, checklist, and status progression (`IN PROGRESS`, Step 1 complete).
- Recorded validation evidence for scoped Ruff, targeted VS15 test, and full backend regression.
Assumptions:
- VS15 Step 1 focuses on deterministic backend synthetic burst evidence only; frontend burst-resilience coverage remains Step 2 scope.
- Burst-scale validation is performed in integration harness (fakeredis + patched session/ws manager), not by introducing new external load tooling in this increment.
Related:
- `backend/tests/integration/test_telemetry_synthetic_load.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS14 Closure Gate: Accept Completion After Scoped Hardening Remediation and Full Green Regression Evidence
Decision: Mark VS14 complete once a bounded hardening-only remediation pass resolves gate-discovered lint debt and all required backend/frontend production-readiness validation commands are green in one evidence set.
Reason:
- VS14 scope in CurrentSprint is explicitly hardening/verification only with no net-new product API/event surface unless defect remediation requires it.
- Initial VS14 backend scoped Ruff gate surfaced existing test-hygiene defects that blocked release-readiness verification despite no runtime contract issues.
- A minimal test-only remediation plus full gate rerun satisfies production-readiness evidence without introducing architectural or contract drift.
Impact:
- Applied bounded backend hardening updates only in `backend/tests/unit/test_security.py` and `backend/tests/unit/test_telemetry_scaffold.py`.
- Completed required validation sequence: scoped Ruff, targeted VS14 backend readiness suite, full backend regression (`455 passed`), and full frontend gate (`lint`, `typecheck`, `test` `67`, `test:e2e` `15/15`, `build`, `perf:bundle`).
- `CurrentSprint.md` now marks VS14 status as `COMPLETE`, adds VS14 subsystem closure steps/evidence, and closes the remaining-work master checklist.
- `DevelopmentJournal.md` now records VS14 Step 2 remediation and closure-gate evidence including runbook currency and performance baseline notes.
Assumptions:
- Existing large `three` chunk warning remains accepted baseline at VS14 closure and is deferred as post-M10 optimization work, not a release blocker.
- Current targeted load/performance readiness signal is satisfied by runtime-threshold regression coverage and green frontend build/perf gates; no additional synthetic load harness is introduced in VS14 scope.
Related:
- `backend/tests/unit/test_security.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- `docs/project/DecisionLog.md`

## 2026-08-14
### VS13 Closure Gate: Accept Completion After Full Backend + Frontend Green Validation Suite
Decision: Mark VS13 complete once scoped reporting backend validation, full backend regression, and full frontend quality gates all pass in a single closure evidence set.
Reason:
- Slice-completion governance requires both backend and frontend acceptance criteria to pass before closure.
- VS13 Step 1 and Step 2 implementation scope is complete; remaining requirement is authoritative validation evidence and tracking finalization.
- Final rerun produced all-green frontend e2e (`15/15`) including new VS13 reporting lifecycle scenarios.
Impact:
- `CurrentSprint.md` now marks VS13 status as `COMPLETE`, closes VS13 checklist items, and records command-level closure evidence.
- `DevelopmentJournal.md` includes dedicated VS13 Step 1, Step 2, and closure entries with backend/frontend gate outcomes.
- Remaining-work checklist advances to VS14 as the next planned unfinished slice.
Assumptions:
- Existing large `three` chunk warning remains accepted baseline for this milestone and is deferred to production-readiness/performance scope.
- Closure acceptance uses the latest all-green run outputs as authoritative evidence.
Related:
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- `docs/project/DecisionLog.md`

## 2026-08-14
### VS13 Step 2: Frontend Reporting Lifecycle Parity on Existing Contracts
Decision: Implement VS13 frontend parity as a dedicated `/ops/reports` lifecycle surface driven strictly by reporting REST contracts, with route/nav/hotkey/command integrations and explicit failure/retry behavior.
Reason:
- VS13 closure governance requires frontend acceptance criteria (UI states, retry handling, tests) in addition to backend endpoint delivery.
- Existing backend Step 1 already delivered the approved endpoint set; frontend parity can be completed without API/event/channel expansion.
- Reporting operations are asynchronous and operator-sensitive, so explicit status/retry UX and keyboard-first discoverability are required for practical usage.
Impact:
- Added typed reporting API client/hooks and reporting page with generate/status workflows, artifact metadata rendering, and failed-job retry action.
- Added app routing export + protected route wiring for `/ops/reports`.
- Added reports entry points in app shell, command palette, and hotkey mappings (`y`, `g y`).
- Added VS13 frontend coverage across logic/API/component/e2e layers and extended shared e2e session mocks for reporting contracts/idempotency semantics.
Assumptions:
- VS13 status freshness uses polling-based reconciliation (`useQuery` refetch interval); no websocket channel is added in this slice.
- Existing bundle-size warning for `three` remains accepted baseline and is deferred to production-readiness optimization scope.
Related:
- `frontend/src/features/reporting/ReportsPage.tsx`
- `frontend/src/features/reporting/hooks.ts`
- `frontend/src/features/reporting/api.ts`
- `frontend/src/features/reporting/logic.ts`
- `frontend/src/app/App.tsx`
- `frontend/src/app/routes.ts`
- `frontend/src/shared/ui/AppShell.tsx`
- `frontend/src/shared/ui/CommandPalette.tsx`
- `frontend/src/shared/lib/hotkeys.ts`
- `frontend/tests/e2e/vs13-reporting.spec.ts`
- `frontend/tests/e2e/support/session.ts`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS13 Step 1: Reporting Async Pipeline Activation with Persistence and Event/Audit Parity
Decision: Activate VS13 reporting scope by adding the PRD-approved reporting endpoint set (`POST /api/v1/reports/generate`, `GET /api/v1/reports/{id}`), migration-backed report lifecycle persistence, and reporting event/audit parity.
Reason:
- CurrentSprint VS13 scope explicitly enables these two reporting endpoints while prohibiting route-surface expansion.
- Reporting PRD acceptance requires asynchronous generation lifecycle and artifact/error metadata visibility.
- Existing modular monolith event-bus patterns and fail-open publication semantics support bounded implementation without architecture drift.
Impact:
- Added Report module persistence/service stack and Alembic migration `0008_reporting_async_pipeline_baseline` for lifecycle records.
- Added reporting router wiring and validation logic for idempotency, format/date-range, and workspace/network boundary checks.
- Added report stream registration plus report consumer and audit mapping coverage for `report.requested|report.generated|report.failed`.
- Added targeted unit/integration coverage for reporting service, endpoints, consumer behavior, and event/audit/startup parity.
Assumptions:
- VS13 lifecycle uses deterministic in-process consumer baseline for terminal generated/failed outcomes and artifact metadata synthesis rather than external worker integration in this slice.
- Queue publication degradation remains warning-only/non-fatal (`queue_status=deferred`) to preserve existing fail-open operational posture.
Related:
- `backend/app/api/v1/reports.py`
- `backend/app/modules/report/service.py`
- `backend/app/modules/report/repository.py`
- `backend/app/modules/report/models.py`
- `backend/alembic/versions/0008_reporting_async_pipeline_baseline.py`
- `backend/app/events/publisher.py`
- `backend/app/events/bus.py`
- `backend/app/events/consumers/report_consumer.py`
- `backend/app/events/consumers/audit_consumer.py`
- `backend/tests/integration/test_reports_endpoints.py`
- `backend/tests/unit/test_report_service.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS12 Closure Gate: Accept Completion After Full Backend + Frontend Green Validation Suite
Decision: Mark VS12 complete once scoped plugin backend validation, full backend regression, and full frontend quality gates all pass in a single closure evidence set.
Reason:
- Slice-completion governance requires both backend and frontend acceptance criteria to pass before closure.
- VS12 Step 1 and Step 2 implementation scope is complete; remaining requirement is authoritative validation evidence and tracking finalization.
- Final rerun produced all-green frontend e2e (`13/13`) including new VS12 plugin lifecycle scenarios.
Impact:
- `CurrentSprint.md` now marks VS12 status as `COMPLETE`, closes VS12 checklist items, and records command-level closure evidence.
- `DevelopmentJournal.md` includes dedicated VS12 Step 1, Step 2, and closure entries with backend/frontend gate outcomes.
- Remaining-work checklist advances to VS13 as the next planned unfinished slice.
Assumptions:
- Existing large `three` chunk warning remains accepted baseline for this milestone and is deferred to later production-readiness/performance slices.
- Closure acceptance uses the latest all-green run outputs as authoritative evidence.
Related:
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- `docs/project/DecisionLog.md`

## 2026-08-14
### VS12 Step 2: Frontend Plugin Lifecycle Parity on Existing Contracts
Decision: Implement VS12 frontend parity as a dedicated `/ops/plugins` runtime safety surface driven strictly by existing plugin REST contracts, with route/nav/hotkey/command integrations and explicit safety-state UX.
Reason:
- VS12 closure governance requires frontend acceptance criteria (UI states, lifecycle controls, failure/retry behavior, tests) in addition to backend endpoint delivery.
- Existing backend Step 1 already delivered the approved endpoint set; frontend parity can be completed without API/event/channel expansion.
- Plugin operations are operator-sensitive and benefit from keyboard-first navigation additions (`u`, `g u`) aligned with established shell patterns.
Impact:
- Added typed plugins API client/hooks and plugin runtime safety page with install/enable/disable workflows, safety badges, and failure-state messaging.
- Added app routing export + protected route wiring for `/ops/plugins`.
- Added plugins entry points in app shell, command palette, and hotkey mappings.
- Added VS12 frontend coverage across API/unit/component/e2e layers and expanded shared e2e session mocks for plugin lifecycle + safety failure semantics.
Assumptions:
- VS12 continues to rely on near-real-time polling reconciliation for lifecycle updates; no websocket channel is added in this slice.
- Existing bundle-size warning for `three` remains accepted baseline and is deferred to later production-readiness optimization scope.
Related:
- `frontend/src/features/plugins/PluginsPage.tsx`
- `frontend/src/features/plugins/hooks.ts`
- `frontend/src/features/plugins/api.ts`
- `frontend/src/app/App.tsx`
- `frontend/src/app/routes.ts`
- `frontend/src/shared/ui/AppShell.tsx`
- `frontend/src/shared/ui/CommandPalette.tsx`
- `frontend/src/shared/lib/hotkeys.ts`
- `frontend/tests/e2e/vs12-plugins-lifecycle.spec.ts`
- `frontend/tests/e2e/support/session.ts`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS12 Step 1: Plugin Runtime Safety Activation with Persistence and Event/Audit Parity
Decision: Activate VS12 plugin runtime safety scope by adding the PRD-approved plugin endpoint set (`GET /api/v1/plugins`, `POST /api/v1/plugins/install`, `POST /api/v1/plugins/{id}/enable`, `POST /api/v1/plugins/{id}/disable`), migration-backed registry persistence, and plugin lifecycle event/audit parity.
Reason:
- CurrentSprint VS12 scope explicitly enables these four plugin endpoints while prohibiting route-surface expansion and new websocket channels.
- Plugins PRD acceptance requires explicit signature/dependency validation and fault-isolation behavior with bounded lifecycle controls.
- Existing modular monolith event-bus patterns and fail-open publication semantics support bounded implementation without architecture drift.
Impact:
- Added Plugin module persistence/service stack and Alembic migration `0007_plugin_lifecycle_baseline` for registry lifecycle records.
- Added plugins router wiring and lifecycle validation logic for install/enable/disable transitions.
- Added plugin stream registration plus audit mapping coverage for `plugin.installed|plugin.enabled|plugin.disabled|plugin.failed`.
- Added targeted unit/integration coverage for plugin endpoints, service safety behavior, and event/audit/startup parity.
Assumptions:
- VS12 lifecycle controls intentionally stop at install/enable/disable and do not expose unrestricted plugin runtime execution paths.
- Queue publication degradation remains warning-only/non-fatal (`queue_status=deferred`) to preserve existing fail-open operational posture.
Related:
- `backend/app/api/v1/plugins.py`
- `backend/app/modules/plugin/service.py`
- `backend/app/modules/plugin/repository.py`
- `backend/app/modules/plugin/models.py`
- `backend/alembic/versions/0007_plugin_lifecycle_baseline.py`
- `backend/app/events/publisher.py`
- `backend/app/events/bus.py`
- `backend/app/events/consumers/audit_consumer.py`
- `backend/tests/integration/test_plugins_endpoints.py`
- `backend/tests/unit/test_plugin_service.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS11 Closure Gate: Accept Completion After Full Backend + Frontend Green Validation Suite
Decision: Mark VS11 complete once scoped alerts backend validation, full backend regression, and full frontend quality gates all pass in a single closure evidence set.
Reason:
- Slice-completion governance requires both backend and frontend acceptance criteria to pass before closure.
- VS11 Step 1 and Step 2 implementation scope is complete; remaining requirement is authoritative validation evidence and tracking finalization.
- Final rerun produced all-green frontend e2e (`11/11`) and cleared earlier transient flake uncertainty for closure evidence.
Impact:
- `CurrentSprint.md` now marks VS11 status as `COMPLETE`, closes VS11 checklist items, and records command-level closure evidence.
- `DevelopmentJournal.md` includes dedicated VS11 Step 1, Step 2, and closure entries with backend/frontend gate outcomes.
- Remaining-work checklist advances to VS12 as the next planned unfinished slice.
Assumptions:
- Existing large `three` chunk warning remains accepted baseline for this milestone and is deferred to later production-readiness/performance slices.
- Closure acceptance uses the latest all-green run outputs as authoritative evidence.
Related:
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- `docs/project/DecisionLog.md`

## 2026-08-14
### VS11 Step 2: Frontend Alerts Lifecycle Parity on Existing Contracts
Decision: Implement VS11 frontend parity by driving reliability alerts lifecycle UX from existing alerts REST contracts and `/ws/alerts` parity, including acknowledge/resolve actions, deterministic status filters, and keyboard-navigation aliases.
Reason:
- VS11 closure governance requires frontend acceptance criteria (UI states, realtime behavior, tests) in addition to backend endpoint delivery.
- Existing backend Step 1 already delivered the approved endpoint set; frontend parity can be completed without API/event/channel expansion.
- Adding explicit alerts navigation aliases (`l`, `g l`, command palette alias) improves operator discoverability while preserving established app navigation patterns.
Impact:
- Added typed alerts API client and React Query hooks for list/ack/resolve flows.
- Reworked reliability page alert lifecycle rendering/actions and action-level queue-status operator feedback.
- Extended websocket alert delta typing/store acceptance for `ack` lifecycle transitions and status normalization.
- Added VS11 frontend coverage across unit/component/e2e layers and recorded full frontend gate evidence.
Assumptions:
- Reliability view remains the canonical VS11 operator surface for alerts lifecycle actions; no separate alerts route is required in this slice.
- Existing bundle-size warning for `three` remains accepted baseline and is deferred to later production-readiness optimization scope.
Related:
- `frontend/src/features/reliability/ReliabilityPage.tsx`
- `frontend/src/features/reliability/api.ts`
- `frontend/src/features/reliability/hooks.ts`
- `frontend/src/shared/types/alerts.ts`
- `frontend/src/shared/types/ws.ts`
- `frontend/tests/e2e/vs11-alerts-lifecycle.spec.ts`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS11 Step 1: Alerts API Lifecycle Activation with Event/Audit/WebSocket Parity
Decision: Activate VS11 alerts lifecycle scope by adding the PRD-approved alerts endpoint set (`GET /api/v1/alerts`, `POST /api/v1/alerts/{id}/ack`, `POST /api/v1/alerts/{id}/resolve`), migration-backed persistence, and parity handling for `alert.acknowledged` across audit and `/ws/alerts` consumers.
Reason:
- CurrentSprint VS11 scope explicitly enables these three alerts endpoints while prohibiting route-surface expansion and new websocket channels.
- Alerts PRD acceptance requires auditable acknowledge/resolve transitions and event parity with deterministic lifecycle status handling.
- Existing modular monolith event-bus patterns and fail-open publish semantics support bounded implementation without architecture drift.
Impact:
- Added Alert module persistence/service stack and Alembic migration `0006_alert_lifecycle_baseline` for lifecycle records.
- Added alerts router wiring and consumer registration for generated/acknowledged/resolved ingestion.
- Extended audit consumer actor/resource resolution and `/ws/alerts` delta mapping/counters for `alert.acknowledged` parity.
- Added targeted unit/integration coverage for endpoints, service lifecycle behavior, and consumer parity.
Assumptions:
- Alert list endpoint is read-focused (`GET /api/v1/alerts`) and intentionally excludes new detail/create endpoints in VS11.
- Queue publication degradation remains warning-only/non-fatal (`queue_status=deferred`) to preserve existing fail-open operational posture.
Related:
- `backend/app/api/v1/alerts.py`
- `backend/app/modules/alert/service.py`
- `backend/app/modules/alert/repository.py`
- `backend/app/events/consumers/alert_consumer.py`
- `backend/app/events/consumers/audit_consumer.py`
- `backend/app/events/consumers/ws_push_consumer.py`
- `backend/alembic/versions/0006_alert_lifecycle_baseline.py`
- `backend/tests/integration/test_alerts_endpoints.py`
- `backend/tests/unit/test_alert_service.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS10 Closure Gate: Accept Completion After Full Backend + Frontend Green Validation Suite
Decision: Mark VS10 complete once the full closure gate passes across scoped topology checks, full backend regression, and full frontend quality gates, with evidence recorded in sprint tracking.
Reason:
- Slice-completion governance in project docs requires backend and frontend acceptance criteria to pass before closure.
- VS10 Step 1 and Step 2 implementation scope is complete; remaining requirement is authoritative validation evidence and tracking finalization.
- Re-running closure commands post-Step 2 commit confirms no regressions and validates C6-governed endpoint set remains bounded.
Impact:
- `CurrentSprint.md` now marks VS10 status as `COMPLETE`, closes VS10 checklist items, and records command-level closure evidence.
- `DevelopmentJournal.md` includes a dedicated VS10 closure entry with backend/frontend gate outcomes.
- Remaining-work checklist advances to VS11 as the next planned unfinished slice.
Assumptions:
- Existing large `three` chunk warning remains accepted baseline for this milestone and is deferred to later production-readiness/performance slices.
- Closure acceptance uses the latest all-green run outputs as authoritative evidence.
Related:
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- `docs/project/DecisionLog.md`

## 2026-08-14
### VS10 Step 2: Frontend Topology Analysis Parity on Existing Endpoint Contract
Decision: Implement VS10 frontend parity as a dedicated `/ops/topology-analysis` experience wired to existing VS10 topology endpoints, including deterministic neighbour/impact views, reconcile action feedback, and topology WebSocket-driven stale-result invalidation.
Reason:
- VS10 closure governance requires frontend acceptance criteria (UI states, realtime behavior, tests) in addition to backend endpoint delivery.
- Existing backend Step 1 already delivered the approved endpoint set; frontend parity can be completed without API/event/channel expansion.
- Bounded query normalization (`depth`, `max_hops`) and deterministic list summaries reduce operator ambiguity while preserving documented contract semantics.
Impact:
- Added route/nav/hotkey/command integration for topology analysis entry points (`/ops/topology-analysis`, `p`, `g p`).
- Added typed API client + React Query hooks for neighbors/impact/reconcile contracts and reconcile-triggered topology cache invalidation.
- Added realtime fingerprint-based refetch behavior for neighbour/impact queries on `/ws/topology` structural deltas.
- Added VS10 frontend coverage across unit/component/e2e layers and recorded full frontend gate evidence.
Assumptions:
- Reconcile lifecycle event progress beyond immediate response remains backend/audit-observed in this slice; frontend Step 2 shows latest available reconcile result from API mutation response and topology refresh semantics.
- Existing bundle-size warning for `three` remains accepted baseline and is deferred to later production-readiness optimization scope.
Related:
- `frontend/src/features/topology/TopologyAnalysisPage.tsx`
- `frontend/src/features/topology/api.ts`
- `frontend/src/features/topology/hooks.ts`
- `frontend/src/features/topology/logic.ts`
- `frontend/tests/e2e/vs10-topology-analysis.spec.ts`
- `frontend/src/shared/ui/AppShell.tsx`
- `frontend/src/shared/ui/CommandPalette.tsx`
- `frontend/src/shared/lib/hotkeys.ts`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS10 Step 1: Deferred Topology Endpoints Activation with Deterministic Graph Semantics
Decision: Activate VS10 deferred topology endpoint set by implementing `GET /api/v1/topology/device/{id}/neighbors`, `GET /api/v1/topology/impact/{id}`, and `POST /api/v1/topology/reconcile` in the existing topology module, with deterministic ordering, bounded traversal depth, and reconcile lifecycle audit events.
Reason:
- CurrentSprint VS10 scope explicitly enables these three deferred endpoints under C6 while prohibiting route-surface expansion beyond them.
- Topology PRD acceptance requires deterministic neighbour metadata, reachable dependency set with hop depth, and auditable reconcile lifecycle outcomes.
- Existing topology service/router and event-bus patterns allow bounded implementation without schema changes or contract drift.
Impact:
- Topology router now exposes all VS10-approved endpoints with canonical envelope responses and 404 semantics for missing device/network resources.
- `TopologyQueryService` now provides deterministic neighbours/impact analysis plus reconcile orchestration with per-network counts and workspace backfill checks.
- Reconcile lifecycle emits auditable events: `network.topology.reconcile_requested`, `network.topology.reconcile_completed`, and `network.topology.reconcile_failed`.
- Audit consumer now persists reconcile lifecycle events as network-scoped audit records.
Assumptions:
- Event names use `network.topology.*` within EventAPI naming convention and remain internal contracts until PRD/API docs are expanded in closure tracking.
- Reconcile baseline is analysis/audit oriented (no cross-module write side effects beyond existing topology graph data hygiene).
Related:
- `backend/app/api/v1/topology.py`
- `backend/app/modules/network/topology.py`
- `backend/app/modules/network/schemas.py`
- `backend/app/events/consumers/audit_consumer.py`
- `backend/tests/unit/test_topology_flow.py`
- `backend/tests/unit/test_audit_consumer.py`
- `backend/tests/integration/test_network_endpoints.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS9 Closure Gate: Evidence Acceptance on Immediate Green Rerun for Flaky E2E
Decision: Accept VS9 closure validation after a full all-green rerun of the frontend e2e suite when an earlier run produced a single transient timeout in `vs2-telemetry` that passed immediately on retry and on full rerun without code changes.
Reason:
- VS9 closure governance requires current command-level proof for backend and frontend gates.
- The failing signal was non-deterministic (timeout in select option availability) and did not persist when the same full command was rerun in the same environment.
- Blocking closure on a non-reproducible transient would not improve contract correctness and would delay bounded-scope completion.
Impact:
- VS9 closure evidence records the passing rerun as authoritative (`npm run test:e2e` `8/8`), alongside backend scoped/full regression and full frontend quality gates.
- No additional scope expansion was introduced; no API/event/channel changes were required to satisfy closure.
Assumptions:
- The VS2 inspector timeout remains a known flaky risk to monitor, but it is not a deterministic regression against VS9 acceptance criteria.
- Future slices may prioritize hardening this flake if recurrence increases.
Related:
- `frontend/tests/e2e/vs2-telemetry.spec.ts`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### VS9 Step 1: Hypervisor Baseline Outcome Semantics and Execute Permission Gate
Decision: Implement VS9 backend baseline by introducing a dedicated in-process hypervisor execution service that deterministically sets terminal intent outcomes (`execution_completed` / `execution_failed`) based on verification outcome, persists rollback metadata when verification fails, and enforces `execute:rollback` permission on `POST /api/v1/intents/execute`.
Reason:
- VS9 objective requires moving from deferred lifecycle placeholders to intent-to-hypervisor baseline execution outcomes with rollback-ready metadata.
- Existing contracts already define required REST surface and event names; introducing new endpoints/channels would violate scope boundaries.
- Permission gating at execute entry aligns with Authentication PRD permission model and reduces unsafe dispatch risk.
Impact:
- Added `backend/app/modules/intent/hypervisor.py` with deterministic verification + rollback-ready outcome shaping.
- `IntentExecutionService.execute_intent(...)` now records `verification` and optional `rollback` metadata in `execution_provenance`, updates terminal status from hypervisor baseline outcome, and keeps event publication fail-open semantics.
- Added `INTENT_EXECUTION_PERMISSION_DENIED` conflict path (`403`) when caller lacks `execute:rollback`.
- Extended ws intent delta mapping with optional `verification_status` and `rollback_status` changed fields for operator context while preserving canonical channel/payload shape.
Assumptions:
- VS9 Step 1 uses deterministic in-process baseline execution outcomes (no vendor driver calls, no Celery queue orchestration) to preserve finite scope and reversibility.
- Verification-failure rollback metadata is baseline provenance evidence and does not yet imply external device-level rollback execution telemetry beyond current documented contracts.
Related:
- `backend/app/modules/intent/hypervisor.py`
- `backend/app/modules/intent/service.py`
- `backend/app/api/v1/intents.py`
- `backend/app/events/consumers/ws_push_consumer.py`
- `backend/tests/unit/test_intent_hypervisor_service.py`
- `backend/tests/unit/test_intent_execution_service.py`
- `backend/tests/integration/test_intent_endpoints.py`
- `backend/tests/integration/test_intent_event_ws_flow.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-14
### Frontend Full-Gate Revalidation and Evidence-First Closure Update
Decision: After E2E suite expansion and stability fixes, require a fresh full frontend quality gate run (`lint`, `typecheck`, `test`, `test:e2e`, `build`, `perf:bundle`) and record results in sprint/journal evidence before closure commit.
Reason:
- Recent VS2/VS7 Playwright strict-locator failures showed evidence drift risk after test-suite growth.
- Closure governance requires current, command-level proof rather than relying on prior green runs.
- Frontend-only fix scope avoids backend/API contract churn while restoring deterministic quality signal.
Impact:
- Applied frontend-scope test hardening only: selector disambiguation in VS2/VS7 specs and query-tolerant workspace-aware network mocks in shared E2E session support.
- Re-ran full frontend gate and captured all-green outcomes in project tracking docs.
- Maintained no-backend-change posture and preserved canonical API envelope/event/channel contracts.
Assumptions:
- Existing `three` chunk warning in build/perf output remains acceptable at this stage and is tracked as performance optimization follow-up, not a release blocker for this gate.
Related:
- `frontend/tests/e2e/vs2-telemetry.spec.ts`
- `frontend/tests/e2e/vs7-branch-compare.spec.ts`
- `frontend/tests/e2e/support/session.ts`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-13
### VS8 Frontend Parity Closure Scope and Validation Gate Decision
Decision: Close VS8 by delivering a bounded frontend parity increment that focuses on documented intent lifecycle UX requirements and missing tenancy-management operator flows, then require full frontend quality-gate evidence in the same closure step.
Reason:
- `CurrentSprint` defined VS8 closure as blocked on frontend parity; backend lifecycle/event scope was already complete.
- Existing frontend baseline lacked complete org/workspace/member management affordances and did not fully harden intent validate/execute error/retry/terminal state handling.
- A bounded parity pass with explicit tests and gates minimizes risk while satisfying completion-governance rules.
Impact:
- Added `/ops/tenancy` surface with organization/workspace/member create/select/remove flows and explicit async states.
- Hardened `IntentPage` with JSON validation guards, idempotency-conflict operator handling, terminal execute guard, and realtime-to-detail reconciliation triggers.
- Added frontend tests across required layers: unit (`intent/tenancy logic`), component (`IntentPage`), and e2e (`validate -> execute -> retry -> terminal state`).
- Ran and recorded full frontend closure gate commands (`lint`, `typecheck`, `test`, `test:e2e`, `build`, `perf:bundle`) with green results.
Assumptions:
- Member role values remain free-form per current backend contract; UI restricts role choices to practical defaults without changing API schema.
- Bundle-size warning from the `three` chunk is acceptable for VS8 closure and is deferred to production-readiness optimization slices.
Related:
- `frontend/src/features/organizations/TenancyPage.tsx`
- `frontend/src/features/intent/IntentPage.tsx`
- `frontend/src/features/intent/logic.ts`
- `frontend/tests/e2e/intent-parity.spec.ts`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-13
### VS8 Step 7 Explainability/Confidence Fallback Coverage Closure
Decision: Close VS8 Step 7 by adding focused fallback assertions for explainability/confidence serialization paths in execute replay and detail-read flows, without expanding API/event contracts.
Reason:
- VS8 Step 7 requires contract presence plus fallback safety, and existing baseline metadata fields were already in place.
- Targeted tests reduce risk of null/shape drift in persisted lifecycle metadata while keeping scope minimal.
- No additional schema/event changes are required for this closure increment.
Impact:
- Added tests validating confidence band fallback derivation for idempotent replay when stored band is absent.
- Added tests validating detail-read normalization fallback for non-dict metadata fields and default confidence posture.
- Backend explainability/confidence contract behavior remains unchanged externally; closure gain is regression safety on fallback semantics.
Assumptions:
- Current baseline confidence posture (`approval_required` default behavior and score-band thresholds) remains authoritative for VS8; richer policy gates remain future-slice scope.
- VS8 overall closure still requires frontend parity evidence per project completion governance.
Related:
- `backend/tests/unit/test_intent_execution_service.py`
- `backend/app/modules/intent/service.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-13
### VS8 Step 6 Terminal Intent Lifecycle Producer Source in Execute Flow
Decision: Close VS8 Step 6 by producing `intent.execution_completed` and `intent.execution_failed` from a bounded terminal transition immediately after `intent.execution_started` publication in the existing execute lifecycle flow.
Reason:
- VS8 contract requires all four governed intent lifecycle events to be producer-emitted and consumer-covered.
- Hypervisor integration remains VS9 scope, so terminal lifecycle signaling in VS8 must remain lifecycle/provenance-oriented and avoid real execution side effects.
- A bounded same-flow terminal transition preserves finite VS8 scope while satisfying event contract closure.
Impact:
- `IntentExecutionService.execute_intent(...)` now updates persisted terminal status/provenance/explainability and publishes terminal intent event payloads.
- Successful queue-handoff path records/publishes `execution_completed`; degraded publish path records/publishes `execution_failed` with fail-open warning metadata.
- Terminal publish failures are warning-only (`intent_terminal_event_publish_failed`) and do not fail the API request/transaction.
- Unit coverage for execute lifecycle now asserts started + terminal publication behavior and degraded terminal-state handling.
Assumptions:
- VS8 terminal lifecycle outcomes remain baseline intent-state transitions and do not represent VS9 hypervisor dispatch/rollback completion semantics.
- Frontend parity validation for VS8 remains required for slice closure but is blocked until frontend repository/path is available.
Related:
- `backend/app/modules/intent/service.py`
- `backend/tests/unit/test_intent_execution_service.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-13
### Authoritative Slice Completion Rule Includes Frontend Acceptance (Planning)
Decision: A vertical slice cannot be marked complete unless both backend and frontend acceptance criteria pass, including UI state behavior, realtime integration expectations, accessibility/responsiveness checks, and required frontend tests.
Reason:
- Remaining slices include end-user application surfaces where backend-only completion leaves the product operationally incomplete.
- Current project tracking required stronger completion governance so "done" reflects full application readiness.
- Enforcing frontend parity at slice closure reduces late-stage integration debt and production-readiness risk.
Impact:
- Added explicit frontend workstream requirements to VS8-VS14 planning in `CurrentSprint.md`.
- Slice closure interpretation now requires frontend acceptance evidence in addition to backend validation gates.
- Future implementation and closure updates must record frontend test outcomes (`unit`, `component`, `e2e`) alongside backend regressions.
Assumptions:
- Frontend workstream uses existing documented REST/WebSocket contracts; no undocumented channel/API expansion is implied by this rule.
- If a slice has no documented realtime channel dependency, polling/refresh behavior can satisfy "realtime behavior expectations" for that slice.
Related:
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- `docs/project/Roadmap.md`

## 2026-08-13
### Post-VS8 Vertical Slice Sequencing and Remaining-Work Authority (Planning)
Decision: Treat `docs/project/CurrentSprint.md` (`Post-VS8 Plan` + `Remaining Work Master Checklist`) as the authoritative source for all remaining implementation slices after VS8, with the planned sequence `VS9` through `VS14`.
Reason:
- Future sessions need a single unambiguous pointer for "what remains" to prevent overlap and planning drift.
- Existing project docs (`Roadmap.md`, `Milestones.md`) are milestone-oriented and were not sufficiently explicit on ordered post-VS8 implementation slices.
- A finite sequence with closure gates preserves design-before-implementation discipline and reduces scope creep.
Impact:
- Added explicit post-VS8 slices and end-state criteria into `CurrentSprint.md`.
- Added ordered, non-overlapping remaining-work checklist to drive session continuity.
- Added cross-doc alignment updates in `Roadmap.md` and `Milestones.md` to match the same sequence.
- Added AGENTS entry-point pointer so future agent sessions load this authoritative plan before coding.
Assumptions:
- VS8 must close before VS9 implementation starts, except planning/docs updates.
- Production-readiness work remains a distinct final slice (`VS14`) to consolidate hardening and release evidence.
- `OPENCODE.md` Vertical Slice Continuity note is treated as historical/stale for sequencing; authoritative remaining-work order is `docs/project/CurrentSprint.md` (`Post-VS8 Plan`).
Related:
- `docs/project/CurrentSprint.md`
- `docs/project/Roadmap.md`
- `docs/project/Milestones.md`
- `AGENTS.md`

## 2026-08-13
### Post-VS8 Scope Assumptions for Hypervisor, Deferred Topology, Alerts, Plugins, Reporting, and M10 Closure (Planning)
Decision: Encode post-VS8 slice boundaries directly from PRDs and ADRs, and explicitly mark unresolved rollout details as assumptions rather than commitments.
Reason:
- `IntentEngine.md`, `Topology.md`, `Alerts.md`, `Plugins.md`, and `Reporting.md` define target surfaces but not full execution-order details.
- ADR guardrails require avoiding invented contracts while still enabling finite execution planning.
- Explicit assumptions reduce ambiguity for first implementation sessions in each future slice.
Impact:
- VS9 scope is constrained to hypervisor execution/rollback baseline through existing intent contracts and documented intent events.
- VS10 scope is constrained to deferred topology endpoints already named in `Topology.md`, preserving C6 governance.
- VS11-VS13 scopes map exactly to PRD-listed API/event contracts for alerts/plugins/reporting.
- VS14 is designated as a no-net-new-surface hardening and release-readiness closure gate unless defect remediation requires minimal documented changes.
Assumptions:
- Hypervisor terminal lifecycle outcomes (`intent.execution_completed`/`intent.execution_failed`) are produced in VS9 without adding `/api/v1/ai/*` routes.
- No new WebSocket channels are required for VS11-VS13 beyond those already documented.
- Any additional schema/index work remains migration-gated and only added when required by measured query or lifecycle behavior.
Related:
- `docs/features/IntentEngine.md`
- `docs/features/Topology.md`
- `docs/features/Alerts.md`
- `docs/features/Plugins.md`
- `docs/features/Reporting.md`
- `docs/adr/ADR-006-event-bus-internal-communication.md`
- `docs/adr/ADR-008-simulation-before-deployment.md`

## 2026-08-13
### Intent Execute/Detail Baseline with Partial Lifecycle Producer Completion (VS8 Steps 4-6 Progress)
Decision: Implement `POST /api/v1/intents/execute` + `GET /api/v1/intents/{id}` and advance Step 6 by publishing `intent.validated` and `intent.execution_started` with fail-open queue semantics, while deferring producer emission of `intent.execution_completed`/`intent.execution_failed` to a subsequent bounded transition source.
Reason:
- `docs/features/IntentEngine.md` requires execute + detail endpoints and governed lifecycle events; VS8 baseline can safely produce validated/start events without introducing M9 hypervisor side effects.
- Execute path needed idempotent replay/conflict semantics and persisted provenance updates before broader lifecycle transition expansion.
- Existing consumer architecture can carry full intent lifecycle mapping now, even while producer transitions for terminal states remain pending.
Impact:
- Added execute/detail API contracts and service flows for lifecycle execution-start + read behavior.
- Validation flow now publishes `intent.validated` with persisted queue metadata (`queue_status`, `stream_entry_id`, `warning`) and fail-open degradation on publish failure.
- Execute flow publishes `intent.execution_started` with the same fail-open semantics.
- Audit and ws push consumers/tests now include the full intent lifecycle event set, and intent stream registration is wired in event publisher/bus.
- Remaining Step 6 scope is narrowed to adding bounded producer transition sources for `intent.execution_completed` and `intent.execution_failed`.
Assumptions:
- VS8 baseline remains lifecycle/provenance oriented; terminal execution outcomes are modeled as future bounded transitions until M9 execution integration exists.
Related:
- `backend/app/api/v1/intents.py`
- `backend/app/modules/intent/service.py`
- `backend/app/modules/intent/repository.py`
- `backend/app/events/publisher.py`
- `backend/app/events/bus.py`
- `backend/app/events/consumers/audit_consumer.py`
- `backend/app/events/consumers/ws_push_consumer.py`
- `backend/tests/unit/test_intent_execution_service.py`
- `backend/tests/unit/test_intent_service.py`
- `backend/tests/integration/test_intent_endpoints.py`
- `backend/tests/integration/test_intent_event_ws_flow.py`

## 2026-08-13
### Intent Validate Endpoint Contract with Persisted Explicit Reasons (VS8 Step 3)
Decision: Implement `POST /api/v1/intents/validate` with explicit reason-coded validation outcomes persisted to the Intent baseline table and returned through canonical envelope response models.
Reason:
- `docs/features/IntentEngine.md` requires invalid intents to fail with explicit reasons.
- VS8 Step 3 needs a minimal, reversible baseline that validates UNIL action/scope/constraints semantics and preserves C5 boundary checks without introducing execution side effects.
- Persisting validation + explainability metadata in Step 3 supports later execution/read/event steps without contract churn.
Impact:
- Added `/api/v1/intents/validate` route with typed request/response schemas and canonical envelope response.
- Added `IntentValidationService` baseline checks for supported action map, scope/constraints shape, network existence/workspace boundary, and deterministic reason-code outputs.
- Added baseline explainability/confidence posture fields in validation output (`summary`, `evidence`, `alternatives_considered`, `policy_reference`, `score`, `band`, `approval_required`).
- No execution endpoint behavior introduced, no new event publication introduced, no websocket channel change, and no C5/C6 drift.
Assumptions:
- Step 3 confidence scoring remains baseline heuristic (`0.84` validated, `0.0` rejected) until richer recommendation scoring is implemented in later VS8 explainability steps.
Related:
- `backend/app/api/v1/intents.py`
- `backend/app/modules/intent/schemas.py`
- `backend/app/modules/intent/service.py`
- `backend/app/main.py`
- `backend/tests/unit/test_intent_service.py`
- `backend/tests/integration/test_intent_endpoints.py`

## 2026-08-13
### Intent Persistence Baseline as Required First VS8 Executable Increment (VS8 Step 2)
Decision: Introduce a dedicated `intents` PostgreSQL table and minimal Intent module ORM/repository baseline as the required first executable persistence increment for VS8.
Reason:
- `docs/features/IntentEngine.md` requires intent records, lifecycle status transitions, and execution provenance before endpoint lifecycle behavior can be implemented safely.
- A migration-first baseline keeps VS8 finite, reversible, and aligned with database ownership guardrails.
- Capturing explainability/confidence placeholders in baseline persistence avoids ad-hoc schema drift in later VS8 steps.
Impact:
- Added Alembic migration `0005_intent_lifecycle_baseline` with reversible downgrade and lifecycle/read indexes.
- Added `Intent` ORM model and `IntentRepository` create/read/idempotency lookup/status-update primitives.
- No REST/WebSocket route additions in Step 2, no event contract additions yet, and no C5/C6 boundary changes.
Assumptions:
- Baseline table can carry both lifecycle state and explainability/confidence metadata for VS8; optional split tables (MIG-8.3) remain deferred unless required by later steps.
Related:
- `backend/alembic/versions/0005_intent_lifecycle_baseline.py`
- `backend/alembic/env.py`
- `backend/app/modules/intent/models.py`
- `backend/app/modules/intent/repository.py`
- `backend/tests/unit/test_intent_repository.py`

## 2026-08-13
### VS7 Closure Gate Completion and Simulation Lifecycle Baseline Finalization
Decision: Mark VS7 complete after delivering Steps 4-7 with full backend regression and tracking closure.
Reason:
- All VS7 checklist items in sprint tracking are now implemented and validated.
- Simulation PRD endpoint surface and lifecycle contract goals are complete for baseline scope.
- Closure entry provides a governance checkpoint before opening next-slice planning.
Impact:
- VS7 now closes with persisted branch lineage, detail read, deterministic compare deltas, and lifecycle audit/ws contract alignment.
- Project tracking reflects closure gate completion and VS7 complete state.
- No additional schema/API boundary changes introduced by closure itself.
Related:
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- `docs/project/DecisionLog.md`

## 2026-08-13
### Simulation Lifecycle Contract Alignment via `simulation.branch_created` + Audit Coverage (VS7 Step 7)
Decision: Extend simulation lifecycle contract coverage by publishing `simulation.branch_created` during branch creation, routing it through existing digital twin delta translation, and adding lifecycle event audit coverage for simulation events.
Reason:
- VS7 Step 7 requires lifecycle audit coverage and contract alignment updates after branch/read/compare endpoint delivery.
- EventAPI naming convention and existing simulation lifecycle model support additive optional lifecycle events without envelope changes.
- Existing ws/audit consumer architecture can absorb this event with minimal reversible scope.
Impact:
- Branch flow now emits `simulation.branch_created` with governed simulation payload fields.
- Audit consumer now maps simulation lifecycle events to `resource_type=simulation` and resolves simulation resource IDs from payload.
- WebSocket push consumer now translates `simulation.branch_created` to `/ws/digital-twin` update deltas under existing scene-object shape.
- No route additions, no schema migration, no C5/C6 drift.
Assumptions:
- `simulation.branch_created` is treated as a non-breaking additive lifecycle event under current simulation PRD/event governance.
Related:
- `backend/app/modules/simulation/service.py`
- `backend/app/events/consumers/audit_consumer.py`
- `backend/app/events/consumers/ws_push_consumer.py`
- `backend/tests/unit/test_simulation_service.py`
- `backend/tests/unit/test_audit_consumer.py`
- `backend/tests/unit/test_ws_push_consumer.py`

## 2026-08-13
### Deterministic Compare Endpoint Semantics for Baseline Deltas (VS7 Step 6)
Decision: Implement compare semantics on `GET /api/v1/simulations/{id}/compare/{baselineId}` using deterministic numeric extraction over persisted `run_output` and return explicit simulation/baseline snapshots plus metric deltas.
Reason:
- Simulation PRD acceptance criteria requires baseline compare for latency/loss/throughput deltas.
- Deterministic coercion of absent/non-numeric fields to `0.0` avoids unstable response behavior and keeps compare output predictable.
- C5 boundary safety requires workspace validation on both simulation records before compare.
Impact:
- Added compare API response contract with `simulation_metrics`, `baseline_metrics`, and `deltas` objects.
- Added conflict semantics (`409`) when simulation and baseline belong to different networks.
- No schema migration, no websocket/event contract changes, and no C6 drift.
Assumptions:
- Compare endpoint currently operates on persisted simulation metadata records only; TimescaleDB-backed extended analytics remain out of Step 6 scope.
Related:
- `backend/app/api/v1/simulation.py`
- `backend/app/modules/simulation/service.py`
- `backend/tests/unit/test_simulation_service.py`
- `backend/tests/integration/test_simulation_endpoints.py`

## 2026-08-13
### Simulation Detail Read Contract via Persisted Lifecycle Metadata (VS7 Step 5)
Decision: Add `GET /api/v1/simulations/{id}` read endpoint returning a canonical envelope view over persisted simulation lifecycle metadata, including lineage and queue outcome fields.
Reason:
- Simulation PRD explicitly lists simulation detail read endpoint as required lifecycle surface.
- Existing Step 1 persistence schema already contains required fields; read endpoint is minimal/no-migration increment.
- C5 boundary checks must remain enforced for simulation reads through Organization service boundary.
Impact:
- Added detail API response model and service read flow for simulation metadata fields (`validation`, `run_output`, `model_versions`, `audit_provenance`, queue fields, timestamps).
- Not-found behavior returns standard 404 wrapped by canonical error envelope.
- No event contract or websocket routing changes for Step 5 scope.
Assumptions:
- Detail endpoint returns stored metadata snapshots as-is; no additional enrichment from external stores is required in this step.
Related:
- `backend/app/api/v1/simulation.py`
- `backend/app/modules/simulation/service.py`
- `backend/tests/unit/test_simulation_service.py`
- `backend/tests/integration/test_simulation_endpoints.py`

## 2026-08-13
### Branch via Persisted Draft Record with Parent Lineage Linkage (VS7 Step 4)
Decision: Implement simulation branching with `POST /api/v1/simulations/branch` by creating a new draft simulation record linked through `parent_simulation_id` to an existing persisted simulation.
Reason:
- `Simulation.md` explicitly defines `/simulations/branch` and requires scenario lineage support for what-if workflows.
- Existing Step 1 simulation schema already includes `parent_simulation_id`, enabling lineage persistence without extra migration scope.
- Draft-only creation keeps Step 4 minimal and reversible while preserving existing start/pause queue semantics and event contracts.
Impact:
- Added `branch_simulation(...)` service flow with parent existence + C5 workspace validation before persistence.
- Branch records now persist as `state=status=draft`, `queue_status=draft`, inherited ownership context, and branch validation metadata (`pipeline_stage=branch_draft`).
- API route `POST /api/v1/simulations/branch` now returns canonical envelope payload including both `simulation_id` and `parent_simulation_id` lineage reference.
- No new event names, no websocket routing changes, no schema migration, and no C6 drift.
Assumptions:
- Branch scenario identity is deterministically derived from `(network_id, scenario_name)` and can differ from parent `scenario_id` when label changes.
Related:
- `backend/app/api/v1/simulation.py`
- `backend/app/modules/simulation/service.py`
- `backend/app/modules/simulation/repository.py`
- `backend/tests/unit/test_simulation_service.py`
- `backend/tests/integration/test_simulation_endpoints.py`
- `backend/tests/unit/test_simulation_repository.py`

## 2026-08-12
### Pause Endpoint and Resume-via-Start Lifecycle Semantics (VS7 Step 3)
Decision: Implement simulation pause with `POST /api/v1/simulations/pause` and implement resume semantics via optional `simulation_id` on existing `POST /api/v1/simulations/start` rather than introducing any new resume endpoint/event type.
Reason:
- `Simulation.md` explicitly includes `/simulations/pause` and lifecycle integrity AC for pause/resume.
- Reusing `/simulations/start` for resume keeps endpoint surface minimal and avoids undocumented contract expansion.
- Existing fail-open publication pattern must be preserved for queue availability degradations.
Impact:
- Added pause route and service lifecycle transition handling for `queued|running -> paused` with idempotent paused behavior.
- Resume requests now target existing simulation records and re-queue `simulation.started` handoff with queue outcome persistence (`queued` or `deferred`).
- `simulation.paused` publication failures are warning-only and non-fatal, preserving fail-open behavior.
- No schema changes, no C5/C6 drift, and canonical envelope/status behavior preserved.
Assumptions:
- Resume eligibility is restricted to persisted simulations in `paused` or `queued` state; non-resumable states return conflict.
Related:
- `backend/app/api/v1/simulation.py`
- `backend/app/modules/simulation/service.py`
- `backend/app/modules/simulation/repository.py`
- `backend/tests/unit/test_simulation_service.py`
- `backend/tests/integration/test_simulation_endpoints.py`

## 2026-08-12
### Persist `POST /api/v1/simulations/start` Through C5-Safe Validation and Fail-Open Queue Outcomes (VS7 Step 2)
Decision: Route simulation start through a dedicated `SimulationStartService` that validates network/workspace ownership boundaries and persists start-handoff outcomes while retaining existing fail-open queue behavior.
Reason:
- `Simulation.md` requires persisted scenario/run baseline metadata; previous start flow only returned transient handoff payloads.
- C5 guardrail requires workspace validation through Organization service boundary rather than cross-module joins/direct table coupling.
- Existing Step-4 fail-open queue semantics are production behavior and must remain unchanged while adding persistence.
Impact:
- `POST /api/v1/simulations/start` now validates network existence and active workspace via `OrgWorkspaceService.get_active_workspace()` before queue publication.
- Start outcomes are persisted in `simulations` for both `queued` and `deferred` paths with queue metadata and provenance snapshots.
- REST route shape/status/envelope remain unchanged (`202` canonical envelope); deferred behavior (`warning=event_queue_unavailable`) is preserved.
Assumptions:
- `run_output` baseline placeholders (`latency_ms`, `loss_pct`, `throughput_mbps` set to `0.0`) are acceptable until lifecycle execution steps populate observed values.
Related:
- `backend/app/api/v1/simulation.py`
- `backend/app/modules/simulation/service.py`
- `backend/tests/unit/test_simulation_service.py`
- `backend/tests/integration/test_simulation_endpoints.py`

## 2026-08-12
### Simulation Persistence Baseline as Required First VS7 Increment (VS7 Step 1)
Decision: Introduce a dedicated `simulations` PostgreSQL table with a minimal Simulation module ORM/repository baseline as the required first executable VS7 increment.
Reason:
- `docs/features/Simulation.md` requires persisted scenario metadata, run outputs, and baseline deltas; current code only produced transient handoff payloads.
- A required migration-first step keeps VS7 finite, reversible, and aligned with database ownership guardrails before adding additional lifecycle endpoints.
- Keeping the change persistence-only avoids premature contract expansion and preserves existing `POST /api/v1/simulations/start` fail-open publish behavior.
Impact:
- Added Alembic migration `0004_simulation_lifecycle_baseline` with reversible downgrade and indexes for network/workspace/scenario/state lookups.
- Added `Simulation` ORM model and `SimulationRepository` create/read/queue-outcome update primitives.
- No REST/WebSocket route additions in Step 1, no API envelope drift, and no C5/C6 contract changes.
Assumptions:
- `simulations` is treated as the single authoritative baseline table for VS7 before any optional split into supplemental run-output tables.
Related:
- `backend/alembic/versions/0004_simulation_lifecycle_baseline.py`
- `backend/app/modules/simulation/models.py`
- `backend/app/modules/simulation/repository.py`
- `backend/tests/unit/test_simulation_repository.py`

## 2026-08-12
### VS6 Closure: Remaining Scope Complete and Tracking Finalized
Decision: Mark VS6 complete after delivering Steps 3-5 with full validation gates and closure tracking updates.
Reason:
- All VS6 checklist items in sprint tracking are complete and validated with full backend regression.
- Spatial-reference objectives for update semantics, digital twin mapping, and governed topology read exposure are now delivered without architecture/contract drift.
- Closure entry provides a single governance checkpoint before opening next-slice planning.
Impact:
- VS6 now closes with end-to-end spatial-reference continuity across create/update events, digital twin scene-delta mapping, and topology read contracts.
- Project tracking reflects completed closure gate and finished VS6 state.
- No additional runtime/API/schema changes introduced by closure itself.
Related:
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- `docs/project/DecisionLog.md`

## 2026-08-12
### Topology Read-Path Spatial Reference Exposure Under Existing Contracts (VS6 Step 5)
Decision: Extend governed topology read-path payloads (`/api/v1/topology/graph`, `/api/v1/topology/nodes/{device_id}`) to include optional `spatial_ref_id` where available.
Reason:
- VS6 Step 5 requires surfacing spatial references on read paths without introducing new endpoint surface area.
- Topology service already writes/stores `spatial_ref_id` on Device nodes from VS6 Steps 1-2; read-path exposure is the minimal contract completion.
- Optional-field exposure preserves backwards compatibility for existing consumers and nodes lacking spatial references.
Impact:
- Topology node schemas now carry nullable `spatial_ref_id` fields.
- Neo4j read queries for graph and node-with-neighbours now project `spatial_ref_id` from Device nodes.
- Unit/integration tests now verify `spatial_ref_id` presence and null behavior in topology responses.
- No route additions, no C6 deferred endpoint changes, and no schema/envelope drift.
Related:
- `backend/app/modules/network/schemas.py`
- `backend/app/modules/network/topology.py`
- `backend/app/api/v1/topology.py`
- `backend/tests/unit/test_topology_flow.py`
- `backend/tests/integration/test_network_endpoints.py`

## 2026-08-12
### Optional Spatial Metadata Mapping in Digital Twin Scene Deltas (VS6 Step 4)
Decision: Extend simulation websocket delta translation to include optional spatial fields (`spatial_ref_id`, `spatial_metadata`) when provided by simulation event payloads.
Reason:
- VS6 Step 4 requires digital twin payload mapping to carry spatial reference metadata where available.
- Existing `scene_object` + `changed_fields` contract supports additive optional fields without breaking current consumers.
- Keeping mapping optional preserves compatibility for existing simulation events that do not yet provide spatial metadata.
Impact:
- `handle_ws_digital_twin_event()` now conditionally maps spatial fields into `scene_object` and `scene_object.changed_fields`.
- Baseline mapping for non-spatial simulation events remains unchanged.
- Added unit/integration coverage for both spatial-present and spatial-absent event payloads.
- No API envelope/schema changes and no C5/C6/runtime fail-open semantics drift.
Related:
- `backend/app/events/consumers/ws_push_consumer.py`
- `backend/tests/unit/test_ws_push_consumer.py`
- `backend/tests/integration/test_simulation_event_ws_flow.py`

## 2026-08-12
### Device Spatial Reference Update Path and `network.device.updated` Delta Contract (VS6 Step 3)
Decision: Implement a dedicated device spatial-reference update path and emit `network.device.updated` with strict `changed_fields` delta semantics for topology/digital twin consumers.
Reason:
- VS6 Step 3 explicitly requires spatial-reference updates beyond create flow and contract-safe update deltas.
- Existing `/ws/topology` and topology-consumer update paths already consume `changed_fields`; extending this with `spatial_ref_id` is the minimal compatible increment.
- Idempotent no-change handling avoids unnecessary event fanout and keeps update semantics deterministic.
Impact:
- Added `PATCH /api/v1/networks/{network_id}/devices/{device_id}` request flow for `spatial_ref_id` updates.
- `DeviceService.update_device_spatial_ref()` now publishes `network.device.updated` payload with `{ "changed_fields": {"spatial_ref_id": ...} }` plus ownership metadata.
- Topology and websocket consumers continue using existing delta contract; tests now explicitly cover spatial-ref update propagation.
- No API envelope drift, no schema migration in Step 3, and no C5/C6/runtime fail-open behavior changes.
Related:
- `backend/app/api/v1/networks.py`
- `backend/app/modules/network/schemas.py`
- `backend/app/modules/network/service.py`
- `backend/app/modules/network/repository.py`
- `backend/tests/unit/test_network_service.py`
- `backend/tests/unit/test_topology_flow.py`
- `backend/tests/unit/test_ws_push_consumer.py`
- `backend/tests/integration/test_network_endpoints.py`

## 2026-08-12
### Spatial Reference Propagation in Device Added Event and Topology Writes (VS6 Step 2)
Decision: Include `spatial_ref_id` in `network.device.added` event payload and write it to Neo4j `Device` nodes during topology consumer processing.
Reason:
- VS6 Step 1 introduced persistence/API baseline; without event propagation, Digital Twin synchronization paths remain spatially incomplete.
- Existing event consumer topology path is the minimal in-boundary integration point for spatial-reference continuity.
- Change stays contract-safe by extending payload fields non-breakingly and preserving event naming/version semantics.
Impact:
- `DeviceService.add_device()` now publishes `spatial_ref_id` in `network.device.added` payload.
- `TopologyQueryService.create_device_node()` and topology consumer now store `spatial_ref_id` on Neo4j nodes.
- No envelope drift, no schema migration in Step 2, and no C5/C6/runtime fail-open semantic changes.
Related:
- `backend/app/modules/network/service.py`
- `backend/app/modules/network/topology.py`
- `backend/app/events/consumers/topology_consumer.py`
- `backend/tests/unit/test_network_service.py`
- `backend/tests/unit/test_topology_flow.py`

## 2026-08-12
### Device Spatial Reference Baseline for M6/VS6 (VS6 Step 1)
Decision: Introduce optional `spatial_ref_id` on Network `Device` persistence and API create/read contracts as the first executable M6 spatial-reference increment.
Reason:
- `CurrentSprint` explicitly defers Digital Twin spatial references to M6; prior model contained only `location_hint` free text.
- Minimal reversible rollout requires nullable field introduction first, without forcing immediate event/read-path propagation or breaking create flows.
- Backward compatibility is preserved by keeping `spatial_ref_id` optional end-to-end.
Impact:
- Added Alembic migration `0003_device_spatial_ref` to append nullable `devices.spatial_ref_id` with index.
- `Device` ORM model and create-device schema/service/repository flow now accept/store/return `spatial_ref_id`.
- No API envelope drift, no C5/C6 scope change, and no runtime/websocket behavior change in Step 1.
Related:
- `backend/alembic/versions/0003_device_spatial_ref.py`
- `backend/app/modules/network/models.py`
- `backend/app/modules/network/schemas.py`
- `backend/app/modules/network/repository.py`
- `backend/app/modules/network/service.py`
- `backend/tests/unit/test_network_service.py`
- `backend/tests/integration/test_network_endpoints.py`

## 2026-08-12
### VS5 Closure: Remaining Scope Complete and Tracking Finalized
Decision: Mark VS5 complete after delivering Steps 2-4 with full validation gates and final tracking closure, then roll planning forward to VS6 Step 1.
Reason:
- All VS5 checklist items in sprint tracking are complete and validated with full backend regression.
- Security and lifecycle contract goals were achieved without violating architecture, schema, or envelope guardrails.
- Closure entry provides a single governance checkpoint before opening the next vertical slice.
Impact:
- VS5 now closes with per-delta expiry + deny-list enforcement, close-reason observability, and paused/cancelled simulation lifecycle fanout coverage.
- Project tracking reflects completed closure gate and future planning handoff to VS6.
- No additional runtime/API/schema changes introduced by closure itself.
Related:
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- `docs/project/DecisionLog.md`

## 2026-08-12
### Simulation Lifecycle WS Coverage Expansion for Digital Twin (VS5 Step 4)
Decision: Extend digital twin WebSocket event translation coverage to include `simulation.paused` and `simulation.cancelled` using the existing scene-delta `update` contract.
Reason:
- VS5 Step 4 requires lifecycle coverage beyond `simulation.started`/`simulation.completed` while preserving governed event and payload contracts.
- Existing simulation payload shape already carries state/status/risk gate fields needed for paused/cancelled lifecycle representation.
- Minimal/reversible scope is preserved by extending only event-to-handler mappings and test coverage.
Impact:
- `ws_push_consumer` now routes `simulation.paused` and `simulation.cancelled` to `/ws/digital-twin` with unchanged scene-object envelope.
- Unit/integration coverage now validates paused/cancelled translation and registration.
- No schema/API route changes, no envelope drift, and fail-open malformed/unmapped event handling remains unchanged.
Related:
- `backend/app/events/consumers/ws_push_consumer.py`
- `backend/tests/unit/test_ws_push_consumer.py`
- `backend/tests/integration/test_simulation_event_ws_flow.py`

## 2026-08-12
### Digital Twin WS Session-Security Close-Reason Observability (VS5 Step 3)
Decision: Record deterministic close-reason observability for `/ws/digital-twin` session-security closures by incrementing Redis counters keyed by reason (`expired`, `revoked`) and emitting structured branch logs.
Reason:
- VS5 requires explicit visibility into session-security outcomes; per-delta enforcement from Steps 1-2 lacked low-friction operational counters for closure cause distribution.
- Reuses existing Redis operational counter patterns with minimal, reversible scope and no contract or schema expansion.
- Preserves fail-open runtime safety by treating counter persistence failures as warning-only.
Impact:
- Added counter contract `digital_twin:ws:security_close:<reason>` in `DigitalTwinWSManager` push-path security branches.
- Expired and revoked closure branches now emit reason-recorded logs in addition to existing unauthorized frame + close semantics.
- Counter acquisition/increment failures are isolated to warning branches and do not block session-security closure execution.
Related:
- `backend/app/websocket/manager.py`
- `backend/tests/unit/test_websocket_digital_twin_auth.py`

## 2026-08-12
### Digital Twin WS Per-Delta JWT Deny-List Revalidation (VS5 Step 2)
Decision: Enforce JWT deny-list (`jti`) revalidation in `/ws/digital-twin` manager before every scene-delta push and close revoked sessions with `WS_UNAUTHORIZED` signaling.
Reason:
- `docs/features/Authentication.md` defines `jti` deny-list revocation semantics; prior `/ws/digital-twin` runtime behavior checked deny-list only during connection upgrade.
- This is the smallest production-safe VS5 increment to harden active-session revocation enforcement without introducing endpoint, schema, or event contract changes.
- Keeps implementation reversible and scoped by attaching `jti` metadata to existing digital twin subscription state.
Impact:
- `DigitalTwinWSManager` now tracks per-connection token `jti` and blocks push delivery when `jti:deny:<jti>` exists.
- Revoked websocket subscribers receive `WS_UNAUTHORIZED` error frame followed by connection close.
- `/ws/digital-twin` endpoint now passes token `jti` into manager subscription metadata.
- Fail-open semantics are preserved: deny-list client/check failures are warning-only and do not terminate healthy delivery paths.
Related:
- `backend/app/websocket/manager.py`
- `backend/app/websocket/digital_twin.py`
- `backend/tests/unit/test_websocket_digital_twin_auth.py`

## 2026-08-12
### Digital Twin WS Per-Delta JWT Expiry Revalidation (VS5 Step 1)
Decision: Enforce JWT expiry (`exp`) revalidation in `/ws/digital-twin` manager before every scene-delta push and close expired sessions with `WS_UNAUTHORIZED` signaling.
Reason:
- `docs/api/WebSocket.md` requires token expiry revalidation before every delta push; prior behavior validated JWT only at connection upgrade.
- This is the smallest production-safe M6/VS5 increment that hardens session security without introducing new endpoints, schema changes, or event contract drift.
- Keeps implementation reversible and scoped by attaching expiry metadata to existing digital twin subscriptions only.
Impact:
- `DigitalTwinWSManager` now tracks per-connection token expiry and blocks push delivery to expired sessions.
- Expired websocket subscribers receive `WS_UNAUTHORIZED` error frame followed by connection close.
- `/ws/digital-twin` endpoint now passes token `exp` into manager subscription metadata.
- Non-expired sessions continue to receive standard scene deltas; no API envelope changes and no C5/C6 scope impact.
Related:
- `backend/app/websocket/manager.py`
- `backend/app/websocket/digital_twin.py`
- `backend/tests/unit/test_websocket_digital_twin_auth.py`

## 2026-08-12
### Digital Twin Scenario-Validation Handoff Baseline via Simulation Started Events (VS4 Step 4)
Decision: Implement VS4 Step 4 with a minimal executable simulation handoff path that queues deterministic `simulation.started` events from `POST /api/v1/simulations/start` and translates `simulation.*` events into `/ws/digital-twin` scene deltas.
Reason:
- CurrentSprint Step 4 requires executable Digital Twin baseline integration plus scenario validation handoff, and existing backend already provides event-bus and WS push primitives that can be extended without architectural drift.
- ADR-008 requires simulation-before-deployment policy gating; handoff payload now carries explicit validation state and policy reference.
- Minimal/reversible scope is preserved by avoiding schema changes and keeping queue failures fail-open with explicit warning metadata.
Impact:
- Added simulation API route `POST /api/v1/simulations/start` returning canonical envelope with deterministic handoff payload and queue status.
- Added simulation service for deterministic scenario validation handoff shaping and `simulation.started` event publication.
- Registered `simulation` stream mappings in publisher + consumer group config and routed `simulation.started`/`simulation.completed` to `/ws/digital-twin` scene delta fanout.
- Added `/ws/digital-twin` endpoint + manager and documented scene delta/routing contracts in API docs.
- Added digital twin scenario validation runbook for operational response and fail-open queue degradation handling.
Related:
- `backend/app/api/v1/simulation.py`
- `backend/app/modules/simulation/service.py`
- `backend/app/events/consumers/ws_push_consumer.py`
- `backend/app/websocket/digital_twin.py`
- `backend/app/websocket/manager.py`
- `backend/app/events/publisher.py`
- `backend/app/events/bus.py`
- `docs/project/DigitalTwinScenarioValidationRunbook.md`
- `docs/api/WebSocket.md`
- `docs/api/EventAPI.md`

## 2026-08-12
### Deferred Topology Endpoints Governed Design Start Under C6 (VS4 Step 3)
Decision: Start VS4 deferred-topology work with a design-first handoff document and expanded C6 non-routability coverage, without enabling deferred routes.
Reason:
- Preserve architecture guardrails by separating planning/design from endpoint activation.
- Reduce accidental deferred route exposure risk while implementation design is prepared.
- Keep scope minimal/reversible and aligned with existing C6 contract enforcement.
Impact:
- Added `docs/project/TopologyDeferredEndpointsDesign-VS4.md` capturing module impact, contract intent, data/event boundaries, risks, and implementation-start exit criteria.
- Integration tests now assert additional deferred path/method non-routability (`GET /api/v1/topology/reconcile`, `POST /api/v1/topology/impact/{id}`).
- No REST contract/envelope changes, no schema migrations, and no route registration changes.
Related:
- `docs/project/TopologyDeferredEndpointsDesign-VS4.md`
- `backend/tests/integration/test_network_endpoints.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-12
### Runtime Adapter SLO Alerting Operationalization with Runbook Metadata (VS4 Step 2)
Decision: Emit runtime adapter SLO threshold lifecycle alerts (`alert.generated`/`alert.resolved`) from telemetry health state transitions and attach runbook-backed response metadata in the alert payload.
Reason:
- Convert existing internal SLO severity/reason observability into actionable alerting without introducing API or schema drift.
- Ensure deterministic alert lifecycle behavior by persisting `runtime_adapter_slo_alert_active` state in telemetry health counters.
- Provide operator-ready guidance linkage by attaching explicit runbook playbook identifiers in emitted alert payloads.
Impact:
- Telemetry health read-path now publishes SLO alert events only on state transition (inactive->active, active->inactive), preventing duplicate re-emits on unchanged state.
- Alert payloads include severity context, anomaly reason flags, SLO snapshot fields, threshold constants, and runbook references (`runbook_reference`, `runbook_version`, `runbook_playbook`).
- Added `docs/project/TelemetryRuntimeAdapterRunbook.md` as the operational source for response playbooks consumed by alert metadata.
- Fail-open behavior preserved: state persistence and publish failures remain warning-only and do not change health response contracts.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/app/modules/telemetry/counters.py`
- `backend/app/api/v1/telemetry.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_counters.py`
- `backend/tests/integration/test_telemetry_endpoints.py`
- `docs/project/TelemetryRuntimeAdapterRunbook.md`

## 2026-08-12
### Vendor-Facing Runtime Adapter Increment Baseline (VS4 Step 1)
Decision: Extend the existing runtime adapter mode factory with deterministic vendor-facing `snmp` and `grpc` modes while preserving the established `stub`/`seeded` fail-open semantics.
Reason:
- Execute the first VS4 runtime adapter increment behind already-governed factory controls with minimal, reversible scope.
- Preserve architecture guardrails by avoiding direct vendor command execution and keeping runtime adapter changes inside telemetry module boundaries.
- Keep reliability behavior unchanged by reusing existing runtime poll/retry/backpressure instrumentation path.
Impact:
- Added `SNMPRuntimeTelemetryAdapter` and `GRPCRuntimeTelemetryAdapter` deterministic poll baselines that emit canonical telemetry records with stable ownership UUID derivation.
- Added SNMP (`target`, `oid`) and gRPC (`endpoint`, `method`) metadata tags for operational traceability without introducing new REST/WebSocket/event contracts.
- Startup wiring now passes new runtime adapter settings (`TELEMETRY_RUNTIME_ADAPTER_SNMP_*`, `TELEMETRY_RUNTIME_ADAPTER_GRPC_*`) through `build_production_runtime_adapter(...)`.
- Invalid mode handling remains fail-open to `stub` with warning-only diagnostics; no schema migrations or C5/C6 contract drift.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/app/core/config.py`
- `backend/app/main.py`
- `backend/.env.example`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_startup_telemetry.py`

## 2026-08-12
### VS3 Completion Gate and VS4 Handoff Baseline (VS3 Step 28)
Decision: Mark VS3 complete after closing remaining planning/governance tasks and carry unresolved execution scope into explicit VS4 candidates.
Reason:
- Enforce finite VS3 closure criteria with explicit documentation of completed adapter-path expansion, backpressure/SLO hardening, C6 governance checks, and Digital Twin planning handoff.
- Avoid scope creep by separating completed VS3 governance/planning outcomes from executable VS4 implementation work.
Impact:
- `CurrentSprint` now marks Vertical Slice 3 as complete through Step 28 and moves remaining execution tracks to VS4 candidates.
- Digital Twin baseline work is explicitly handed off as next-slice implementation planning without introducing runtime/API/schema drift in VS3 closure.
- C6 deferred topology constraints remain active and test-validated as part of completion gate.
Related:
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- `docs/project/DecisionLog.md`

## 2026-08-12
### C6 Deferred Topology Planning/Governance Closure (VS3 Step 27)
Decision: Finalize VS3 deferred topology planning governance by extending integration-level non-routability coverage for deferred topology endpoint path variants under C6.
Reason:
- Ensure deferred topology analysis endpoints remain explicitly out of runtime routing scope while VS3 closes reliability/backpressure goals.
- Prevent accidental route activation through path-shape variants not covered by prior base-path-only checks.
Impact:
- Integration suite now asserts `404` for additional deferred-path variants (`/api/v1/topology/impact/{id}`, `/api/v1/topology/reconcile/full`) alongside existing deferred checks.
- Confirms C6 contract remains enforced and documented before transitioning to next vertical slice.
- No API envelope, schema, event contract, or runtime telemetry behavior changes.
Related:
- `backend/tests/integration/test_network_endpoints.py`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`

## 2026-08-12
### Runtime Adapter Dropped-Sample Backpressure Hardening (VS3 Step 26)
Decision: Add runtime adapter dropped-sample counter semantics and include dropped-sample anomaly visibility in telemetry health SLO internals.
Reason:
- Complete VS3 backpressure/SLO hardening scope with explicit dropped-sample accounting across invalid sample and ingest-failure drop paths.
- Improve operational explainability by surfacing dropped-sample pressure in snapshot, rollup, and anomaly transition metadata.
Impact:
- Added Redis-backed runtime counter `runtime_adapter_dropped_samples` to telemetry health snapshot contract.
- Runtime poll path now increments dropped-sample counter for invalid runtime samples and ingest-failure drops.
- Health internals now emit dropped-sample SLO visibility (`dropped_samples` in snapshot/rollup) and warning branch `telemetry_health_runtime_adapter_dropped_samples_detected` with anomaly reason `dropped_samples_detected`.
- REST/WebSocket contracts, canonical envelope, schema/migrations, C5/C6 constraints, and fail-open retry/runtime semantics remain unchanged.
Related:
- `backend/app/modules/telemetry/counters.py`
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_counters.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-12
### Runtime Adapter Mode Factory and Seeded Adapter Expansion (VS3 Step 25)
Decision: Expand runtime adapter path beyond stub by introducing a mode-driven production adapter factory and adding a deterministic seeded runtime adapter mode.
Reason:
- Progress VS3 objective to move beyond a hardcoded stub while preserving minimal/reversible scope and existing runtime reliability contracts.
- Provide a deterministic production-shaped adapter mode usable for non-invasive runtime path validation without introducing vendor-specific SNMP/gRPC dependencies yet.
Impact:
- Startup runtime wiring now resolves adapter implementation via `build_production_runtime_adapter(...)` using environment-configurable mode and seeded adapter parameters.
- Added `SeededRuntimeTelemetryAdapter` that emits canonical single-sample telemetry payloads with stable ownership UUIDs and deterministic metadata tags.
- Invalid runtime adapter mode values fail open to stub with warning-only logging (`telemetry_runtime_adapter_mode_invalid`).
- REST/WebSocket contracts, canonical envelope, schema/migrations, C5/C6 constraints, and retry/backoff fail-open behavior remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/app/main.py`
- `backend/app/core/config.py`
- `backend/.env.example`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_startup_telemetry.py`

## 2026-08-12
### Runtime Adapter Cooldown-Correlation Snapshot Aggregation (VS3 Step 24)
Decision: Add an internal-only cooldown-correlation snapshot aggregation branch that captures deterministic per-dimension threshold trigger state, cooldown transition phase counts, and cooldown-summary window aggregates over a bounded in-process window.
Reason:
- Improve operational explainability by correlating threshold trigger outcomes with cooldown transition phases and cooldown-summary state in one deterministic internal snapshot.
- Preserve minimal/reversible scope by extending existing Step 21-23 internal threshold/cooldown observability flow without changing external contracts.
Impact:
- Telemetry health internals now emit `telemetry_health_runtime_adapter_slo_threshold_correlation_snapshot` with bounded-window aggregate metadata for `transition_frequency` and `reason_frequency` dimensions.
- Threshold evaluation now returns deterministic correlation metadata (`updated_state`, `latest_threshold_trigger_state`, `cooldown_transition_phase`) consumed by snapshot aggregation.
- Correlation snapshot state-write/state-read/log failures are isolated to warning-only fail-open branches and do not affect health responses.
- REST/WebSocket contracts, canonical envelope, schema/migrations, C5/C6 constraints, and runtime poll-action behavior remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-11
### Runtime Adapter Cooldown-Transition Event Visibility (VS3 Step 23)
Decision: Add internal-only deterministic cooldown-transition event visibility for runtime adapter trend-threshold dimensions, covering enter-cooldown, cooldown-suppressed, cooldown-expired-reemit, and cooldown-cleared/recovery phases.
Reason:
- Improve operational explainability of Step 21 cooldown/hysteresis behavior with explicit transition-phase diagnostics.
- Preserve reversible, minimal scope by emitting structured internal log branches from existing threshold evaluation flow.
Impact:
- Telemetry health internals now emit per-dimension cooldown transition events with deterministic state metadata for both threshold dimensions.
- Cooldown-transition state read/write and transition-event log failures are isolated to warning-only fail-open branches and do not affect health responses.
- REST/WebSocket contracts, canonical envelope, schema/migrations, C5/C6 constraints, and runtime poll-action behavior remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-11
### Runtime Adapter Trend-Threshold Cooldown-State Observability Summary (VS3 Step 22)
Decision: Add an internal-only cooldown-state summary branch for runtime adapter trend-threshold internals so operations can inspect cooldown status per threshold dimension deterministically.
Reason:
- Improve diagnosability of Step 21 cooldown/hysteresis behavior without changing public contracts.
- Keep enhancement minimal and reversible by reusing existing in-process cooldown state and trend summary context.
Impact:
- Health read-path internals now emit `telemetry_health_runtime_adapter_slo_trend_threshold_cooldown_summary` with per-dimension cooldown metadata (`initialized`, `threshold_crossed`, `reads_since_last_crossed_emit`, `next_crossed_emit_in_reads`, `cooldown_active`) and deterministic window/cooldown fields.
- Cooldown-summary state-read/log failures are isolated to warning-only fail-open branches and do not impact health responses.
- REST/WebSocket contracts, canonical envelope, schema/migrations, C5/C6 constraints, and runtime poll-action behavior remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-11
### Runtime Adapter SLO Trend-Threshold Cooldown and Recovery Visibility (VS3 Step 21)
Decision: Add internal-only cooldown/hysteresis state to runtime adapter SLO trend-threshold trigger evaluation so repeated crossed conditions are rate-limited and recovery/not-crossed transitions are explicitly visible.
Reason:
- Reduce repeated high-noise crossed emissions while retaining deterministic trend-threshold signaling.
- Preserve Step 16-20 reliability semantics by keeping new behavior internal to telemetry health read-path observability.
Impact:
- Crossed thresholds now emit on initial crossing, suppress repeated crossed emissions during cooldown reads, and re-emit crossed when cooldown expires while still crossed.
- Not-crossed branches now include explicit recovery transition visibility (`recovery_transition`) when a previously crossed threshold clears.
- Cooldown state read/write failures are isolated to warning-only fail-open branches and do not alter health responses.
- REST/WebSocket contracts, canonical envelope, schema/migrations, trend-window model, and runtime poll-action behavior remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-11
### Runtime Adapter SLO Trend-Threshold Trigger Visibility (VS3 Step 20)
Decision: Add internal-only deterministic threshold trigger logging on runtime adapter SLO trend-window summaries for transition-frequency and anomaly-reason-frequency counters.
Reason:
- Surface actionable trend escalation signals while preserving minimal, reversible observability-only scope.
- Reuse Step 19 trend-window summary outputs and preserve Step 16-19 semantics unchanged.
Impact:
- Health read path now emits explicit crossed/not-crossed branches for both threshold dimensions (`transition_frequency`, `reason_frequency`) with configured deterministic thresholds.
- Threshold evaluation failures are isolated to warning-only fail-open branch (`telemetry_health_runtime_adapter_slo_trend_threshold_evaluation_failed`) and do not impact health responses.
- REST/WebSocket contracts, canonical envelope, schema/migrations, trend-window state model, and runtime poll-action behavior remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-11
### Runtime Adapter SLO Trend-Window Transition Visibility (VS3 Step 19)
Decision: Add internal-only bounded trend-window visibility on telemetry health runtime adapter rollup flow, logging a rolling summary of severity transitions and anomaly reason frequency.
Reason:
- Extend single-snapshot rollup visibility with minimal trend context for operations diagnostics.
- Keep implementation reversible and fail-open while preserving Step 16-18 behavior contracts.
Impact:
- Health read path now emits `telemetry_health_runtime_adapter_slo_trend_window_summary` with `window_size`, capped `max_window_size`, `severity_transition_counts`, and `anomaly_reason_frequency`.
- Trend-window state write/read/log failures are isolated to warning-only branches and do not change health responses.
- Public REST/WebSocket contracts, canonical envelope, schema/migrations, C5/C6 constraints, and runtime poll-action behavior remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-11
### Runtime Adapter SLO Health Rollup Severity Visibility (VS3 Step 18)
Decision: Add a single internal-only telemetry health rollup log branch for runtime adapter SLO visibility, with explicit severity mapping (`ok`, `degraded`, `critical`) and structured rollup payload fields.
Reason:
- Provide concise operations-focused health posture visibility without changing API contracts.
- Preserve Step 16/17 streak persistence and transition semantics while adding a minimal rollup summary.
Impact:
- Health read path now emits `telemetry_health_runtime_adapter_slo_rollup` including streak, sustained-failure state, ingest attempts/failures, invalid sample ratio, last batch size, and anomaly reason flags.
- Severity mapping is explicit and deterministic (`runtime_adapter_healthy`, `runtime_adapter_anomaly_detected`, `anomaly_streak_threshold_exceeded`, `runtime_sustained_failure_active`) while remaining internal-only.
- REST/WebSocket contracts, canonical envelope, schema/migrations, and runtime poll-action behavior remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-11
### Runtime Adapter Anomaly Streak Transition Metadata Visibility (VS3 Step 17)
Decision: Extend telemetry health runtime adapter streak observability with explicit transition metadata (`previous_streak`, `current_streak`, `anomaly_reason_flags`) emitted by an internal transition event log branch.
Reason:
- Improve operational trend diagnostics by exposing streak transitions and their triggering anomaly categories.
- Preserve existing fail-open behavior and Step 16 Redis-backed streak continuity without introducing API/schema drift.
Impact:
- Health read path now emits `telemetry_health_runtime_adapter_anomaly_streak_transition` on increment/reset/unchanged branches with structured reason flags (`ingest_failures_detected`, `invalid_sample_ratio_exceeded`).
- Public REST/WebSocket contracts, response envelope, schema/migrations, and runtime poll-action semantics remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-11
### Persist Runtime Adapter Anomaly Streak via Redis Health Counters (VS3 Step 16)
Decision: Move runtime adapter anomaly streak state from process-local memory to Redis-backed telemetry health counters; health read path now reads streak from counter snapshot and persists streak updates through counter service.
Reason:
- Preserve anomaly trend continuity across app instances/restarts.
- Keep fail-open reliability by treating counter read/write failures as warning-only with safe fallback behavior.
Impact:
- Cross-instance streak continuity is now supported through shared Redis state.
- Public API contracts and runtime poll-action semantics remain unchanged.
Related:
- `backend/app/modules/telemetry/counters.py`
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_counters.py`
- `backend/tests/unit/test_telemetry_query_service.py`

## 2026-08-11
### Runtime Adapter Rolling Anomaly Streak Visibility (VS3 Step 15)
Decision: Add internal-only rolling anomaly streak state in telemetry health runtime adapter logging flow; increment on consecutive anomaly snapshots and reset on healthy snapshots.
Reason:
- Provide minimal trend visibility beyond single-snapshot anomaly warnings.
- Keep behavior fully internal and fail-open while preserving existing contracts.
Impact:
- Telemetry health read path now emits structured streak trend signals (`incremented`, `reset`) for runtime adapter anomaly continuity.
- No REST/API/schema/C5/C6/runtime-poll semantic drift introduced.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-11
### Runtime Adapter Backpressure Anomaly Threshold Warnings (VS3 Step 14)
Decision: Add internal-only warning thresholds to telemetry health runtime adapter SLO logging: warn on `ingest_failures > 0` with a safe zero-attempt denominator guard, and warn when invalid sample ratio exceeds configured threshold (`> 0.25`).
Reason:
- Provide minimal anomaly visibility for backpressure/quality drift without changing public API contracts.
- Preserve fail-open reliability by keeping anomaly checks inside existing non-fatal logging path.
Impact:
- Health read path now emits targeted anomaly warnings for runtime adapter ingest failures and excessive invalid sample ratios.
- REST routes, API envelope, schema/migrations, C5/C6 behavior, and runtime poll-action semantics remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-11
### Runtime Adapter SLO Snapshot Visibility in Health Read Path (VS3 Step 13)
Decision: Extend telemetry health internal read path to derive and emit runtime adapter SLO snapshot visibility from existing counters (`last_batch_size`, `invalid_samples`, `ingest_attempts`, `ingest_failures`) through structured logging only.
Reason:
- Add operational SLO visibility for runtime adapter behavior without changing public telemetry health API contracts.
- Reuse Step 12 counters and preserve fail-open reliability semantics via sanitization + warning-only logging failures.
Impact:
- Health read path now exposes runtime adapter SLO state internally for diagnostics and future SLO tuning.
- API routes, response envelope, schema/migrations, and runtime poll-action semantics remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_query_service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_telemetry_endpoints.py`

## 2026-08-10
### Runtime Adapter Observability Counters Baseline (VS3 Step 12)
Decision: Add minimal runtime adapter observability counters on telemetry runtime poll path: `runtime_adapter_last_batch_size`, `runtime_adapter_invalid_samples`, `runtime_adapter_ingest_attempts`, and `runtime_adapter_ingest_failures`.
Reason:
- Provide concrete backpressure and ingest-quality visibility for runtime adapter behavior without introducing schema or API changes.
- Keep instrumentation aligned with existing telemetry counter architecture and fail-open reliability goals.
Impact:
- Runtime adapter poll cycles now expose measurable health signals for operations and future SLO tuning.
- Counter update failures remain warning-only and non-fatal to collector runtime.
- Reference implementation commit: `7ed0821`.
Related:
- `backend/app/modules/telemetry/counters.py`
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_counters.py`
- `backend/tests/unit/test_telemetry_scaffold.py`

## 2026-08-10
### Production Collector Adapter Stub Wiring (VS3 Step 11)
Decision: Wire a first minimal production adapter stub into runtime `poll_action` path using existing runtime loop and retry/backoff primitives.
Reason:
- Move from no-op runtime poll action to a production-shaped execution seam without introducing full adapter complexity.
- Preserve Step 1-4 reliability semantics while opening the path for SNMP/gRPC adapter expansion.
Impact:
- Runtime loop now executes through adapter-stub path under existing retry/exhaust/recovery behavior.
- No REST/API/schema drift introduced.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/app/main.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_startup_telemetry.py`

## 2026-08-10
### Alerts WS Fanout Outcome Observability (VS3 Step 10)
Decision: Record structured success/failure observability branches for `alert.generated` and `alert.resolved` websocket fanout outcomes in ws push consumer flow.
Reason:
- Close visibility gap on alert lifecycle fanout reliability without altering delivery semantics.
- Support operational debugging while preserving fail-open behavior.
Impact:
- Alert websocket fanout now emits explicit outcome signals for troubleshooting and SLO tracking.
- No endpoint, envelope, or schema changes.
Related:
- `backend/app/events/consumers/ws_push_consumer.py`
- `backend/tests/unit/test_ws_push_consumer.py`

## 2026-08-10
### Alerts WebSocket Delivery Baseline (VS3 Step 9)
Decision: Add minimal `/ws/alerts` websocket delivery path for alert lifecycle events through ws push consumer translation.
Reason:
- Deliver live alert lifecycle updates with minimal scope and no REST/API contract expansion.
- Reuse existing websocket manager and push-consumer architecture for consistency.
Impact:
- `alert.generated` and `alert.resolved` now reach alert websocket subscribers in real time.
- Deferred topology governance and schema boundaries remain unchanged.
Related:
- `backend/app/events/consumers/ws_push_consumer.py`
- `backend/app/websocket/alerts.py`
- `backend/app/websocket/manager.py`
- `backend/tests/integration/test_alerts_ws_endpoint.py`

## 2026-08-10
### Telemetry Sustained-Failure -> Alert Event Routing (VS3 Step 8)
Decision: Route telemetry sustained-failure transition events to alert event flow using `alert.generated` on activation and `alert.resolved` on recovery.
Reason:
- Integrate collector reliability state with alert lifecycle using existing internal event conventions.
- Preserve fail-open behavior for malformed payloads and publish failures.
Impact:
- Alerting pipeline receives runtime reliability transitions without changing public API/schema contracts.
- Event bus/publisher now include alert stream mapping support.
Related:
- `backend/app/events/consumers/telemetry_consumer.py`
- `backend/app/events/publisher.py`
- `backend/app/events/bus.py`
- `backend/tests/unit/test_telemetry_consumer.py`

## 2026-08-10
### Audit Coverage for Sustained-Failure Transitions (VS3 Step 7)
Decision: Consume telemetry sustained-failure transition events in audit consumer map with `resource_type=telemetry_collector`.
Reason:
- Ensure reliability state transitions are audit-visible without adding a new persistence mechanism.
- Maintain consumer hardening for malformed payloads and UUID parsing.
Impact:
- Audit trail now captures collector sustained-failure activation/recovery transitions.
- Fail-open behavior in audit handling remains intact.
Related:
- `backend/app/events/consumers/audit_consumer.py`
- `backend/tests/unit/test_audit_consumer.py`

## 2026-08-10
### Runtime Sustained-Failure Transition Events (VS3 Step 6)
Decision: Emit internal transition events for runtime sustained-failure state changes: `telemetry.collector.sustained_failure_activated` and `telemetry.collector.sustained_failure_recovered`.
Reason:
- Provide a reliable transition signal for downstream audit/alert consumers without polling health endpoint state.
- Avoid noisy repeated emissions by firing only on state transitions.
Impact:
- Downstream consumers can react to activation/recovery transitions deterministically.
- Event emission failures remain non-fatal and logged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`

## 2026-08-10
### Sustained Runtime Failure Health State (VS3 Step 5)
Decision: Track sustained runtime exhaustion windows and surface collector health degradation via existing telemetry health path and counters.
Reason:
- Distinguish transient poll failures from sustained runtime failures with deterministic thresholding.
- Improve operational health visibility without changing public response envelope or schema.
Impact:
- Telemetry health status now degrades based on sustained runtime failure-active state and recovers on success.
- Runtime failure counters support window/streak analysis for operations.
Related:
- `backend/app/modules/telemetry/counters.py`
- `backend/app/modules/telemetry/service.py`
- `backend/app/api/v1/telemetry.py`
- `backend/tests/unit/test_telemetry_query_service.py`

## 2026-08-10
### Runtime Loop Lifecycle Wiring in App Startup/Shutdown (VS3 Step 4)
Decision: Wire `TelemetryCollectorRunner.start_runtime_loop()` into app lifespan after successful `start_with_retry()`, using a safe default no-op poll action, and keep shutdown deterministic via collector `stop()`.
Reason:
- Completes Step 4 by integrating Step 3 harness into real lifecycle orchestration without introducing adapter-specific poll implementations.
- Preserves startup resilience from Step 1: collector/runtime-loop startup failures remain observable and fail-open for API boot.
- Maintains deterministic runtime task cleanup by preserving explicit stop/await semantics already implemented in collector runner.
Impact:
- Runtime loop lifecycle is now active in production startup/shutdown flow behind existing collector lifecycle controls.
- Runtime loop startup parameters are centralized as constants in `main.py` and exercised via startup integration tests.
- API contracts, schema, and deferred C5/C6 constraints remain unchanged.
Related:
- `backend/app/main.py`
- `backend/app/modules/telemetry/service.py`
- `backend/tests/integration/test_startup_telemetry.py`
- `backend/tests/unit/test_telemetry_scaffold.py`

## 2026-08-10
### Runtime Collector Loop Harness Baseline (VS3 Step 3)
Decision: Add a minimal runtime loop harness to `TelemetryCollectorRunner` that schedules one poll cycle per deterministic interval, routes each cycle through `run_single_poll_with_retry()`, and provides explicit start/stop task lifecycle handling.
Reason:
- Completes the smallest safe Step 3 increment by composing Step 2 retry primitive into a continuous runtime harness without introducing adapter-specific complexity.
- Preserves reliability isolation: exhausted cycles are observable and do not terminate unrelated components.
- Ensures deterministic shutdown by signaling stop and awaiting loop-task completion.
Impact:
- Runtime polling now has a reusable scheduled loop primitive with bounded retry behavior per cycle.
- Structured runtime loop lifecycle logs are available (`started`, `stopped`, `already_running`, per-cycle exhaustion).
- Startup behavior and API/schema contracts remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_startup_telemetry.py`

## 2026-08-10
### Runtime Poll Retry Wrapper Baseline (VS3 Step 2)
Decision: Introduce a minimal runtime collector wrapper `run_single_poll_with_retry()` in `TelemetryCollectorRunner` that executes one poll action with deterministic bounded retry/backoff and structured retry/exhaust visibility.
Reason:
- Extends VS3 reliability controls from startup-only (Step 1) to runtime single-action polling without introducing adapter loops, new APIs, or schema changes.
- Keeps behavior testable and deterministic by reusing bounded backoff math and injectable sleep.
- Maintains isolation by returning success/failure status instead of crashing unrelated components on retry exhaustion.
Impact:
- Runtime poll actions now have a production-safe, bounded retry primitive for future collector loop wiring.
- Exhaustion and retry schedule are observable via logs; transient recovery is explicitly supported.
- Startup behavior and existing contracts remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_startup_telemetry.py`

## 2026-08-10
### Telemetry Collector Startup Retry Baseline (VS3 Step 1)
Decision: Add deterministic collector startup reliability controls via bounded exponential retry/backoff in `TelemetryCollectorRunner.start_with_retry()` and use that path from app lifespan startup with conservative defaults (3 attempts, 0.5s base, 2.0s max).
Reason:
- Delivers the smallest production-safe VS3 increment directly aligned with Telemetry PRD AC for collector retry/backoff, without introducing new APIs, schema changes, or cross-module coupling.
- Keeps startup resilient: exhausted retries are observable via logs and do not fail API startup or affect unrelated consumers.
- Maintains reversible scope by constraining change to collector startup behavior only.
Impact:
- Transient collector start failures now retry deterministically before giving up.
- Retry scheduling and exhaustion outcomes are explicitly logged for operational visibility.
- Existing API contracts, event envelopes, and C5/C6 constraints remain unchanged.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/app/main.py`
- `backend/tests/unit/test_telemetry_scaffold.py`
- `backend/tests/integration/test_startup_telemetry.py`

## 2026-08-10
### Telemetry Health Counters and WS Fanout (VS2 Step 8)
Decision: Add Redis-backed telemetry operational counters (`ingested_events`, `persisted_events`, `fanout_events`, `dropped_events`) and wire `telemetry.metric.ingested` persistence success to `/ws/telemetry` delta fanout; expose counter-backed `dropped_events` in `GET /api/v1/telemetry/health` without changing the canonical envelope or existing route contracts.
Reason:
- Completes VS2 Step 8 by adding observable pipeline health and real-time telemetry push from persisted events while preserving ADR-006 event-bus flow.
- Keeps failure isolation explicit: telemetry fanout/counter failures are logged and counted, but do not break persistence commit or unrelated consumers.
- Uses already-approved channel/event contracts (`/ws/telemetry`, `telemetry.*`) from Telemetry PRD and EventAPI routing.
Impact:
- Health endpoint now reports real dropped-event counters instead of fixed baseline values.
- Telemetry WebSocket subscribers receive metric deltas only after successful persistence, preventing fanout of non-durable records.
- Startup and deferred topology constraints remain unchanged.
- Full backend pytest regression completed green post-implementation (`121 passed`); repository-wide Ruff debt remains pre-existing and out of VS2 Step 8 scope.
Related:
- `backend/app/modules/telemetry/counters.py`
- `backend/app/modules/telemetry/service.py`
- `backend/app/events/consumers/telemetry_consumer.py`
- `backend/app/websocket/manager.py`
- `backend/app/websocket/telemetry.py`
- `backend/app/api/v1/telemetry.py`

## 2026-08-09
### Telemetry Read API Contract (VS2 Step 7)
Decision: Expose telemetry read APIs on `/api/v1/telemetry/history`, `/api/v1/telemetry/device/{id}`, and `/api/v1/telemetry/health` backed exclusively by `telemetry_records`, using canonical envelope responses and deterministic descending ordering by `observed_at` then `record_id`.
Reason:
- Delivers Step 7 with minimal scope by adding read-side APIs only, without changing ingestion/event bus write behavior.
- Provides stable pagination/query semantics for clients while preserving existing module boundaries.
- Adds baseline health visibility from persisted telemetry (`ingest_lag_ms`, `latest_observed_at`, `total_records`) without introducing new storage/migration complexity.
Impact:
- Clients can query global telemetry history, per-device history, and ingestion health through consistent API contracts.
- Read paths remain decoupled from telemetry collection lifecycle; Step 5 startup resilience is unchanged.
- Deferred topology endpoints remain untouched and continue returning 404.
Related:
- `backend/app/api/v1/telemetry.py`
- `backend/app/modules/telemetry/service.py`
- `backend/app/modules/telemetry/repository.py`
- `backend/app/modules/telemetry/schemas.py`

## 2026-08-09
### Telemetry Persistence Contract (VS2 Step 6)
Decision: Persist `telemetry.metric.ingested` events to Telemetry-owned `telemetry_records` with event-level idempotency keyed by `event_id`; consumer commits only on new records, logs-and-skips validation/type failures, and re-raises SQL failures so retry/dead-letter semantics stay in the bus layer.
Reason:
- Completes VS2 Step 6 with minimal scope expansion from Step 5 (publish -> persist) while preserving event conventions and modular boundaries.
- Keeps persistence deterministic and reversible by using a single append-oriented table with explicit Alembic upgrade/downgrade.
- Preserves consumer isolation: persistence failures do not alter API/startup behavior and are handled within existing event bus failure semantics.
Impact:
- Internal telemetry ingestion now has a durable baseline write path without adding public API routes.
- Duplicate deliveries of the same event envelope do not create duplicate telemetry rows.
- Operational diagnosis improves through explicit telemetry persistence success/failure log branches.
Related:
- `backend/alembic/versions/0002_telemetry_records.py`
- `backend/app/modules/telemetry/models.py`
- `backend/app/modules/telemetry/repository.py`
- `backend/app/modules/telemetry/service.py`
- `backend/app/events/consumers/telemetry_consumer.py`

## 2026-08-09
### Telemetry Ingestion Event Contract (VS2 Step 5)
Decision: Introduce internal-only telemetry ingestion contract emitting `telemetry.metric.ingested` events to Redis Stream `stream:telemetry` with normalized payload fields (`device_id`, `network_id`, `workspace_id`, `metric`, `value`, `unit`, `observed_at`, `source`, `tags`) and collector lifecycle wiring in app lifespan.
Reason:
- Satisfies VS2 Step 5 requirements for collector lifecycle + normalized event publish without introducing new public API routes.
- Preserves modular-monolith boundaries by using ADR-006 event-bus communication instead of direct cross-module coupling.
- Keeps rollout safe and reversible by constraining Step 5 consumer behavior to parse/log only (no database writes).
Impact:
- Telemetry producers and internal consumers now share a stable event name and payload contract for Step 5.
- Startup remains resilient: collector startup failures are logged and do not fail service boot.
- Enables future VS2+ increments (collector adapters, persistence, WS streaming) without contract churn.
Related:
- `backend/app/modules/telemetry/service.py`
- `backend/app/events/publisher.py`
- `backend/app/events/bus.py`
- `backend/app/events/consumers/telemetry_consumer.py`
- `backend/app/main.py`
- `docs/features/Telemetry.md`

## 2026-08-09
### Topology Nodes Direction Semantics
Decision: For `GET /api/v1/topology/nodes/{device_id}`, neighbour relation direction is reported relative to the requested node: `outbound` for edges `node -> neighbour`, `inbound` for edges `neighbour -> node`; relation type is normalized to `connected_to`.
Reason:
- Provides deterministic, client-friendly relation semantics without introducing deferred `/neighbors` behavior.
- Satisfies VS2 requirement for explicit `edge_type` and `direction` metadata per neighbour.
Impact:
- Frontend/consumers can render directional adjacency from a single node view without additional inference.
- Does not alter graph pagination contract or deferred endpoint routing.
Related:
- `backend/app/api/v1/topology.py`
- `backend/app/modules/network/topology.py`
- `docs/features/Topology.md`

## 2026-08-09
### Topology Graph Pagination Cursor Contract
Decision: Use node-based pagination on `GET /api/v1/topology/graph` with deterministic ordering by `device_id` ascending; `cursor` represents the last seen `device_id`, and `meta.next_cursor` returns the last `device_id` of the current page only when additional nodes exist.
Reason:
- Keeps pagination stable and idempotent without inventing new routes or event contracts.
- Preserves canonical response envelope while exposing continuation state in metadata.
- Ensures predictable client traversal and retry behavior.
Impact:
- Topology graph clients can iterate pages using `next_cursor`.
- Page edges are limited to relationships where both nodes are in the current page, avoiding partial dangling references.
Related:
- `backend/app/api/v1/topology.py`
- `backend/app/modules/network/topology.py`
- `docs/features/Topology.md`

## 2026-08-05
### Added Architecture Review Gate
Reason:
- Create a pre-merge design checkpoint for major features without adding heavyweight process.

### Introduced Source-of-Truth Documentation Layout
Reason:
- Reduce context drift and duplication by enforcing one canonical home per recurring question.

---

## 2026-08-06
### Replaced passlib with direct bcrypt calls (`security.py`)
Decision: Remove `passlib[bcrypt]` dependency; call `bcrypt.hashpw/checkpw` directly.
Reason: `passlib` 1.7.4 (last release 2020) uses `bcrypt.__about__.__version__` which was removed in bcrypt 4.0. No upstream patch exists; the library is unmaintained. Direct `bcrypt` usage is simpler and future-proof.
Trade-off: Lose passlib's multi-algorithm support (not needed in NANFO — bcrypt only).

### Switched structlog to `stdlib.LoggerFactory`
Decision: Replace `PrintLoggerFactory` with `structlog.stdlib.LoggerFactory()`.
Reason: `structlog.stdlib.add_logger_name` processor accesses `logger.name`. `PrintLogger` (PrintLoggerFactory output) has no `.name` attribute → `AttributeError` in unit tests before lifespan configures logging. stdlib loggers always have `.name`.
Trade-off: Structlog now routes through Python's stdlib logging; negligible performance impact.

### HTTPException → canonical envelope override in `main.py`
Decision: Register `@app.exception_handler(StarletteHTTPException)` before the generic `Exception` handler.
Reason: FastAPI's default handler returns `{"detail": "..."}` which violates API_STANDARD.md §2. All 4xx/5xx must carry `{success, data, meta, errors}`. The handler also maps status codes to canonical error code strings (`AUTH_TOKEN_MISSING_OR_INVALID`, `RATE_LIMITED`, etc.).
Impact: Every HTTP error response is now envelope-compliant. Confirmed by integration tests.

### fakeredis `FakeAsyncRedis` (v2.37 API change)
Decision: Replace `fakeredis.aioredis.FakeRedis` with `fakeredis.FakeAsyncRedis` in all test fixtures.
Reason: fakeredis 2.37 merged aioredis extras into the top-level package. The `aioredis` sub-module still exists but the recommended async class is now `FakeAsyncRedis`.

---

## 2026-08-06
### WebSocket Channel Routing — Option A (Dedicated `/ws/topology` Channel)
Reason:
- Topology structural events (`network.device.added`, `network.device.updated`, `network.device.deleted`) represent changes to the network object graph (node/edge lifecycle), not metric telemetry signals.
- Routing topology events through `/ws/telemetry` would force metric consumers to filter unrelated graph events and topology consumers to filter metric noise. This creates unnecessary coupling between two independently evolving domains.
- Option A (dedicated channel) respects the single-responsibility principle at the WebSocket layer and aligns with the pattern already established for `/ws/alerts` and `/ws/digital-twin`.
Impact:
- `/ws/topology` added as a canonical channel in `docs/features/Telemetry.md` §4.
- `docs/api/WebSocket.md` updated to include `/ws/topology` in the channel registry table.
- `docs/api/EventAPI.md` §5 routing table updated to map `network.device.*` events to `/ws/topology`.
Related:
- `docs/features/Telemetry.md` §4
- `docs/api/WebSocket.md` §1
- `docs/api/EventAPI.md` §5

### JWT Scoping Model — Single-Org-Per-Token
Reason:
- Simplifies RBAC middleware: a single `org_id` claim eliminates the need to resolve org context per-request.
- Multi-org membership is supported at the data layer (`org_members` table); the token scope is single-org at issuance. Users switch org context by obtaining a new token.
- Workspace context is optional in the token. Services requiring workspace scoping accept `workspace_id` as a query parameter when absent from the token, maintaining backward compatibility.
Impact:
- `docs/features/Authentication.md` §8.3 documents this as authoritative behaviour.
- RBAC middleware must extract `org_id` from token claims; if absent, access to org-scoped resources is denied.
- A future `/api/v1/auth/switch-org` endpoint will allow context switching without re-entering credentials.
Related:
- `docs/features/Authentication.md` §8



## Template
## YYYY-MM-DD
### Decision Title
Reason:
- ...
Impact:
- ...
Related:
- `path/to/file.md`
