# Development Journal

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
