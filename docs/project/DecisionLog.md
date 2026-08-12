# Decision Log

Lightweight chronological notes for decisions that do not require a full ADR.

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
