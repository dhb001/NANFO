# Decision Log

Lightweight chronological notes for decisions that do not require a full ADR.

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
