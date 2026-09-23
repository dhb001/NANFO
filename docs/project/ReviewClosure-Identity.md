# ADR027 Identity / Request Metadata Handoff

Date: 2026-09-21. Scope: R03 and the backend request-metadata portion of R10.

## Delivered

- `backend/app/core/request_context.py`: one cached request ID and UTC request
  timestamp; pure-ASGI middleware binds structlog `request_id` and
  `request_timestamp`, clears on entry and in `finally`, and adds `X-Request-ID`
  to responses. Log-event `timestamp` retains its existing emission-time meaning.
- IDs are opaque printable ASCII, at most 128 characters, preserved exactly.
  Missing/empty headers generate a UUID (existing empty-header behavior retained).
  Oversized, whitespace-only, control-character and non-ASCII IDs return canonical
  HTTP400 `REQUEST_ID_INVALID` before routing/dependencies or mutations. Rejection
  receives fresh safe metadata; the invalid header is never echoed or logged.
- `core/dependencies.py` retains the `RequestMeta` import/constructor contract and
  reuses cached metadata, with the same validation for standalone router mounting.
- `identity/service.py` validates and resolves correlations before login counters,
  session creation, refresh rotation or logout revocation. It reuses the existing
  `normalize_audit_correlation`: UUIDs remain unchanged, opaque IDs use the same
  UUIDv5 URL namespace / `nanfo:audit-correlation:` prefix. Audit metadata retains
  IP, reason and JTI, adding the original opaque `request_id`. Published auth
  events retain the original correlation ID.
- `report/service.py` resolves correlation before authority/source/storage work.
  The UUID-backed report and outbox use the same stable mapping; the original
  opaque ID is retained in frozen `snapshot.metadata.request_id`, alongside other
  metadata, before size checking and hashing. UUID inputs retain their previous
  snapshot shape. Idempotent replay retains the original accepted identity/snapshot.
  CSV/PDF rendering includes snapshot metadata through the existing renderer.
- `main.py` uses shared metadata for HTTP/JWT/validation/unhandled errors. Generic
  failures are handled while request context is bound; already-started streams
  propagate failures without sending a replacement response. Validation responses
  retain status422/code/envelope and use reviewed static guidance or a fixed safe
  fallback, avoiding arbitrary validator text, input or context containing credentials.

Public routes, token-pair schemas, report response schemas and binary bodies/ETags
are preserved. No database migration. Session repository/token checks are unchanged:
refresh remains single-use; replay revokes the family; absolute expiry is retained.

## Reproduction and regression evidence

Initial new auth HTTP regression run against pre-repair implementation:

```sh
poetry run pytest tests/integration/test_request_identity_auth.py -q --no-cov --tb=short
```

**7 failed, 1 passed**: opaque success/invalid/rate-limited login and refresh returned
500 (`ValueError`), and UUID invalid/rate-limited error timestamps were empty. The
refresh tests start with UUID login to isolate the post-rotation opaque-ID failure.

Final selected suite: **431 passed, 0 failed, 0 skipped, 7 warnings in 40.64s**.
Of these, **44 new targeted cases** are in:

- `tests/integration/test_request_identity_auth.py` (15): UUID/opaque login outcomes,
  opaque refresh/replay/logout, usable rotated access, fixed absolute expiry,
  complete family revocation, invalid-header rejection before counters/session
  changes, successful subsequent refresh and direct service-boundary validation.
- `tests/unit/test_request_context.py` (23): shared success/error/log identity and
  request time, generated UUIDs, 128/129 bounds, invalid/non-ASCII IDs, concurrency,
  sequential cleanup, cancellation, interpolated-secret validation, standalone
  dependency caching and binary stream failure after headers without rewriting.
- `tests/unit/test_request_identity_report.py` (6): UUID/opaque acceptance with
  stable outbox mapping, original metadata preservation, snapshot digest, real
  CSV/PDF rendering, idempotent replay, invalid-ID early rejection and actual report
  HTTP/service acceptance through signed-session/current-authority dependencies.

Final command, run from `backend/`:

```sh
poetry run pytest tests/unit/test_auth_service.py tests/unit/test_identity_sessions.py tests/unit/test_identity_repository.py tests/unit/test_dependencies_scope.py tests/unit/test_security.py tests/unit/test_audit_consumer.py tests/unit/test_report_service.py tests/unit/test_report_capacity.py tests/unit/test_report_artifacts.py tests/unit/test_report_sources.py tests/unit/test_report_worker.py tests/unit/test_report_consumer.py tests/unit/test_rest_tenant_authorization.py tests/unit/test_websocket_auth_revalidation.py tests/integration/test_auth_endpoints.py tests/integration/test_auth_session_endpoints.py tests/integration/test_reports_endpoints.py tests/integration/test_error_envelope_handlers.py tests/integration/test_request_identity_auth.py tests/unit/test_request_context.py tests/unit/test_request_identity_report.py -q --no-cov --tb=short

poetry run ruff check app/core/dependencies.py app/core/request_context.py app/main.py app/modules/identity/service.py app/modules/report/service.py tests/integration/test_request_identity_auth.py tests/unit/test_request_context.py tests/unit/test_request_identity_report.py
```

Scoped Ruff: **All checks passed**. Warnings are Starlette's deprecated httpx
TestClient adapter (1) and `HTTP_422_UNPROCESSABLE_ENTITY` alias (6); HTTP status
remains422. Dependency-owner changes occurred concurrently; the final431-case run
  passed with the warning-producing environment then in use. Exact independently
  verified original/upgraded environment versions are recorded in the follow-up below.

## Integration boundaries

- Tests use mocked PostgreSQL repositories/sessions, isolated fakeredis and temporary
  report storage. Auth/JWT/session rotation and report HTTP authorization code remain
  real. No shared stores, migrations, deployed workers or live acceptance campaign
  were used. Report database durability is covered only by existing mocked lifecycle
  tests in this run; no new PostgreSQL acceptance claim is made.
- Only the five owned production files (including the new request-context file),
  three new test files and this handoff were edited by this workstream. Concurrent
  configuration, dependency, frontend, deployment and other owner edits were left
  to their owners. No commits.
- Remaining R10 frontend recovery/dashboards and global integration tracking belong
  to the coordinator. The 128-character request-ID protocol bound and safe generic
  validation-message policy are recorded here for the coordinator's global contract docs.

## Integration follow-up: useful safe validation guidance and robustness

The coordinator reported `test_flow_aggregation_rejected_before_query` failing
because the generic validation message removed required guidance about unavailable
flow aggregation and using raw history. Reproduced **1 failed** in each environment
with the unchanged existing integration test:

```sh
/tmp/opencode/r07-backend/bin/python -m pytest tests/integration/test_telemetry_endpoints.py::test_flow_aggregation_rejected_before_query -q --no-cov --tb=short
poetry run python -m pytest tests/integration/test_telemetry_endpoints.py::test_flow_aggregation_rejected_before_query -q --no-cov --tb=short
```

Environment identities verified using `sys.executable`, `sys.version` and
`importlib.metadata.version`:

| Environment | Python | FastAPI | Starlette | Pydantic | pytest |
| --- | --- | --- | --- | --- | --- |
| Original backend Poetry | 3.14.7 | 0.115.14 | 0.46.2 | 2.13.4 | 8.4.2 |
| `/tmp/opencode/r07-backend/bin/python` | 3.12.14 | 0.135.4 | 1.6.0 | 2.13.4 | 9.1.1 |

`main.py` now uses an explicit exact `(error type, full message)` lookup returning
only reviewed constant strings for17 static Telemetry/Report/Organization messages.
All17 are covered through actual domain validators. It preserves the original
`Value error, ...` message form and useful guidance. Unknown messages, nonmatching
types, prefix/suffix/newline interpolation and malformed message values fall back
to `Request validation failed.`. Neither `input`, `ctx`, `loc`, nor exception body
is serialized or logged, even when the public message is allowlisted. No substring
matching, blanket raw-message return, or change to the existing telemetry test.

Independent robustness check found duplicate `X-Request-ID` headers selected the
first value and ignored an oversized/control-character second value: **3 failed**
before repair in the upgraded environment. `request_context.py` now rejects all
duplicate request-ID fields before routing with HTTP400 `REQUEST_ID_INVALID` and
fresh safe metadata. Additional probes verify error-handler failure cleanup and
untouched WebSocket/lifespan forwarding, alongside existing concurrency,
cancellation, validation-secret and started-binary-response tests.

Final follow-up command, from `backend/`, run once with each interpreter prefix
(`/tmp/opencode/r07-backend/bin/python`, `poetry run python`):

```sh
<interpreter> -m pytest tests/integration/test_telemetry_endpoints.py tests/integration/test_error_envelope_handlers.py tests/integration/test_reports_endpoints.py tests/integration/test_org_endpoints.py tests/unit/test_request_context.py tests/integration/test_request_identity_auth.py tests/unit/test_request_identity_report.py -q --no-cov --tb=short --disable-warnings
poetry run ruff check app/main.py app/core/request_context.py tests/unit/test_request_context.py
```

- Original: **164 passed, 0 failed, 0 skipped in 5.54s**, no warnings.
- Upgraded: **164 passed, 0 failed, 0 skipped in 6.20s**,68 warnings (existing
  Starlette TestClient/httpx and422 status-alias deprecations; warning detail hidden
  in final command, not filtered from the count).
- Scoped Ruff and tracked-file whitespace check: **passed**.
- Follow-up edits: `main.py`, `core/request_context.py`, the existing owned
  `tests/unit/test_request_context.py` and this handoff only.31 additional regression
  cases, including every allowlisted message. No shared stores, commits or changes
  to other owners' files.
