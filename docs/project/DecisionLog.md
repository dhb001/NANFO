# Decision Log

Lightweight chronological notes for decisions that do not require a full ADR.

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
