# Development Journal

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
