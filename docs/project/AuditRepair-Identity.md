# ADR-026 Identity / Organization handoff

Implemented workstream1 on2026-09-20. No commit. Preserved pre-existing Identity
authentication changes and concurrent workstreams. No migration required.

## Delivered

- A05: Event-entity resource mapping and event-specific actor keys. Membership
  uses administrator actor_id and affected user_id; workspace uses workspace_id.
  Network created/updated/deleted and device lifecycle mappings retain org_id.
- A06: Exclusive organization-row transaction lock serializes membership restore/remove
  and org/workspace administration; resource writes use compatible shared fences.
  Recheck current
  membership after lock acquisition, refreshing ORM state. Restore original PK and
  created_at, apply requested role; active duplicate409. Audit metadata records
  restored=true. Revocation winning the lock denies a waiting restore with403.
- A12: Operator gets read:topology/read:telemetry/write:config/execute:rollback;
  Read-Only gets two reads; Admin gets seeded permissions. Local org role still
  narrows authority. Operator does not become global Admin.
- A13/A14: Bounded/trimmed names, descriptions, exact role set, slug3..63, bounded
  API pagination and deterministic UUID tie-breakers. Deleted slugs remain reserved;
  concurrent uniqueness violation translates only expected slug conflict to409.
- A16: All eight org/workspace/member lifecycle paths append Identity audit before
  commit, then best-effort publish with the same event_id. Existing audit unique
  index deduplicates direct/consumer/restart replay. Audit failure rolls back the
  mutation. Redis failure cannot remove the committed record.
- Audit search applies alongside existing actor/resource/org filters before count
  and limit. Historical evidence remains untouched even on corrected event replay.
- Safe deletion: reject active workspace descendants at organization level and
  active networks at workspace level through NetworkService, retaining history.
  Last usable org Admin cannot be removed: another current org Admin must have an
  active Identity account and global write:config.

## Frontend contract

- All existing URLs, success envelopes and deletion204 remain.
- Organization/workspace/member lists: page>=1, page_size1..200, defaults1/20;
  response data remains `{items,total}`. Sort created_at ascending then entity UUID.
- Names: trim,1..255 characters. Description maximum4000, nullable.
- Slug: normalized lowercase/trimmed,3..63 alphanumeric/hyphen characters; no
  leading/trailing hyphen. Slug stays immutable after creation.
- PATCH must supply a field; name:null is invalid. Workspace description:null
  clears it, omission preserves it. Validation failures422.
- Roles exactly Admin, Operator, Read-Only. Member POST also restores removed users
  with requested role and201. Active duplicate409; unknown/inactive target404.
- Named409 errors: ORG_SLUG_CONFLICT, ORG_HAS_WORKSPACES,
  WORKSPACE_HAS_NETWORKS, ORG_LAST_ADMIN. Existing active-member duplicate remains
  the existing generic409 message. Display the server error and retain drafts.
- Audit GET `/api/v1/audit/logs`: optional search<=200 characters, case-insensitive
  literal substring matching event_type/correlation_id/resource_type/resource_id/
  actor_id. Empty/whitespace search ignored. Combine with existing filters.
  page>=1/page_size1..200(default50). Data `{items,total,page,page_size}`, existing
  actor/resource/metadata fields; timestamp/log_id descending order. Global Admin
  and current org membership still required; Operator cannot open Admin audit API.

## Changed files owned by this workstream

Application:
- `backend/app/modules/organization/{schemas,repository,service}.py`
- `backend/app/api/v1/{organizations,audit}.py`
- `backend/app/modules/identity/{repository,service}.py`
- `backend/app/events/consumers/audit_consumer.py`

Tests:
- `backend/tests/unit/test_org_service.py`
- `backend/tests/unit/test_audit_consumer.py`
- `backend/tests/unit/test_identity_repository.py`
- `backend/tests/unit/test_organization_validation.py` (new)
- `backend/tests/unit/test_rest_tenant_authorization.py`
- `backend/tests/integration/test_org_endpoints.py`
- `backend/tests/integration/test_identity_audit_repair_postgres.py` (new)

Docs: `docs/features/Organization.md`, `docs/features/Authentication.md`, this file.

## Verification

From backend:

```sh
poetry run pytest tests/unit/test_org_service.py tests/unit/test_audit_consumer.py tests/unit/test_identity_repository.py tests/unit/test_organization_validation.py tests/unit/test_auth_service.py tests/unit/test_dependencies_scope.py tests/unit/test_rest_tenant_authorization.py tests/integration/test_org_endpoints.py tests/integration/test_auth_endpoints.py tests/integration/test_auth_session_endpoints.py -q --no-cov
```

Final result: **318 passed**. Initial broader run exposed old authorization doubles
that assumed unconditional parent deletion and no locking SQL; updated those
fixtures to represent the descendant409 contract and mock the locking repository
boundary. Real locking behavior is tested separately against PostgreSQL.
Final attribution review retained requester-only Intent/Simulation events and
added two regressions; `poetry run pytest tests/unit/test_audit_consumer.py -q
--no-cov` then passed **35 tests** (overlapping the318-test run). Scoped consumer
Ruff passed again after that change.

```sh
IDENTITY_TEST_DSN=<disposable-postgresql-asyncpg-url> poetry run pytest tests/integration/test_identity_audit_repair_postgres.py -q --no-cov
```

Final result: **11 passed**, actual head migration0028 in unique schemas. Executed
using `/tmp/opencode/run_identity_repair.py` with LocalLab-owned loopback PostgreSQL:
`PYTHONPATH=/home/DHB/Documents/NANFO/backend:/home/DHB/Documents/NANFO poetry run python /tmp/opencode/run_identity_repair.py`.
Cleanup confirmed children reaped, private tree removed and port closed. Tests
exercise restore/re-role, concurrent restore, stale-state revocation, publication
failure/audit rollback, replay dedup, reserved/concurrent slugs, usable last Admin,
descendant guards, nullable description, search scope, ordering and immutable old
evidence. Redis publication is fakeredis; database operations are real.

```sh
poetry run ruff check app/modules/organization app/modules/identity/repository.py app/modules/identity/service.py app/events/consumers/audit_consumer.py app/api/v1/organizations.py app/api/v1/audit.py tests/unit/test_org_service.py tests/unit/test_audit_consumer.py tests/unit/test_identity_repository.py tests/unit/test_organization_validation.py tests/unit/test_rest_tenant_authorization.py tests/integration/test_org_endpoints.py tests/integration/test_identity_audit_repair_postgres.py
```

Result: **All checks passed**. Scoped `git diff --check` passed.

## Integration considerations

- Network's future event payloads must include authoritative org_id. Consumer uses
  that published scope; no speculative historical tenant lookup or row rewrite.
  Already-stored NULL-scope/wrong-actor evidence requires a separately explicit,
  owner-verified append-only correction process, not replay mutation.
- Workspace deletion calls existing `NetworkService.list_networks` with
  actor_user_id, page1/page_size1. It uses the actual active count and denies409.
  Organization's write-access path holds the org row lock until caller commit/
  rollback; callers must retain this same transaction through owned mutation.
  Resource writers now share the fence, while administration remains exclusive.
  Observer authority checks are explicitly separate (see integration repair below).
- Redis org event publication remains best-effort (no retry worker/outbox added).
  The immutable audit is durable independently. Safe deletion therefore does not
  depend on a consumer eventually suspending live inventory.
- Identity service additions are optional event_id on append_audit_log and a
  public can_administer_organization directory lookup used for last-admin usability.
  Pre-existing login timing/rate-limit changes in that file were preserved.
- Full cross-workstream backend/frontend gates remain the coordinator's combined
  verification; this handoff reports scoped tests plus real PostgreSQL only.

## Integration blocker repair — final real PostgreSQL verification

Resolved the eight Alert failures recorded in `AuditRepair-Verification.md`156+.
The original generic require_write check retained an exclusive Organization lock;
the measured observer then opened a fresh authorization session that waited on its
own caller. A shared lock alone is insufficient: a queued exclusive administrator
can block a later shared request while the original transaction waits on that
fresh request.

### Boundary and lock-order correction

- Organization/workspace/member administration retains exclusive organization
  locks, current-state reloads and atomic mutation/audit commits. Membership restore
  versus revocation serialization is unchanged.
- Ordinary resource writes retain a transaction-scoped Organization `FOR SHARE`
  fence. Compatible resource writers no longer serialize on an exclusive tenant
  lock. It still excludes parent deletion/member administration until commit.
- Shared acquisition uses NOWAIT. A conflicting authority change yields handled
  `409 ORG_AUTHORITY_BUSY` (retry the operation), never permission bypass. Caller
  must roll back the failed transaction, as existing request/service boundaries do.
  This also breaks the queued-admin cycle across assets' org→network order and
  inventory/spatial's network→org order without changing Network-owned locks.
- Organization exposes `check_workspace_write_authority` for observers: current
  active parent/membership and Admin-or-Operator checks without a retained write
  fence. It cannot replace fenced authorization for inventory creation.
- Minimal `alert/measured.py` adjustment uses that public observer boundary and
  read-only Network scope validation. Global capabilities, binding/device checks,
  fresh independent READ COMMITTED authorization after detector/incident locks and
  immediately before commit, expiry checks, and rollback fences are preserved.
  No Alert tests or existing assertions were weakened.

Additional files touched in this follow-up:
`backend/app/modules/organization/{repository,service}.py`,
`backend/app/modules/alert/measured.py`,
`backend/tests/integration/test_identity_audit_repair_postgres.py`, this handoff.
Pre-existing measured-observer changes were retained.

### Final commands and results

Initial requested two-file lane: **42 passed,0 skipped in43.39s**, all eight failures
resolved. Added four real PostgreSQL regressions for queued revocation/fresh
observer reads, deletion-versus-creation fencing, and inverse asset/inventory lock
order both with and without a queued administrator. Lock barriers use actual
`pg_blocking_pids`, not mocked database success.

Final expanded command from backend:

```sh
poetry run python -m scripts.audit_isolated_suite --test tests/integration/test_alert_postgres.py --test tests/integration/test_identity_audit_repair_postgres.py --test tests/integration/test_network_inventory_postgres.py --test tests/integration/test_spatial_postgres.py --test tests/integration/test_asset_postgres.py --test tests/integration/test_network_outbox_postgres.py --timeout 240
```

**89 passed,0 failed,0 skipped in70.83s; pytest exit0.** Includes all unchanged Alert
expiry/membership/inactive-actor lock barriers, spatial network/device/scene
revocation, asset final-response revocation, and inventory/spatial concurrency.
All cleanup fields true: children reaped, PostgreSQL port closed, owned private
tree removed. Runner JSON says `partial` solely because real Redis was not
requested; all selected real PostgreSQL tests passed.

```sh
poetry run pytest tests/unit/test_org_service.py tests/unit/test_auth_service.py tests/unit/test_dependencies_scope.py tests/unit/test_rest_tenant_authorization.py tests/unit/test_identity_repository.py tests/unit/test_audit_consumer.py tests/unit/test_alert_service.py tests/unit/test_alert_detector.py tests/unit/test_alert_consumer.py -q --no-cov
```

**302 passed in34.00s.** An earlier invocation named nonexistent
`test_measured_alerts.py` and collected no tests; the corrected command above is
the actual result.

Scoped Ruff for both Organization files, measured.py and the PostgreSQL regression
file: **All checks passed**. No shared global tracking documents edited.

## P2 follow-up — opaque X-Request-ID compatibility

Fixed `_commit_lifecycle` rejecting accepted non-UUID request headers such as
`req_8f92a1b4`. External header acceptance and response meta.request_id are unchanged.

- Identity's public append boundary now accepts string or UUID correlation IDs.
  Shared `normalize_audit_correlation` preserves valid UUIDs and maps opaque values
  using UUIDv5 with NAMESPACE_URL and name `nanfo:audit-correlation:<original>`.
- Opaque originals are retained exactly as audit `metadata.request_id`; input
  payload dictionaries are not mutated. Organization event envelopes retain the
  original correlation string and the same event_id used by the atomic audit.
- The event consumer uses the same normalization and metadata enrichment, so
  consumer-only delivery yields matching correlation/metadata and direct-event
  replay still deduplicates by event_id. Missing envelope correlation falls back
  deterministically to the event identity. Historical rows remain untouched.

Added a real PostgreSQL ASGI endpoint regression using actual JWT/session checks,
the accepted `X-Request-ID: req_8f92a1b4` header, Organization create/update and
member-add routes, actual services/repositories and event consumer. It checks
201/200/201, original response identity, persisted mutations and matching audit
correlation/metadata, repeated replay without extra rows, consumer-only equivalent
mapping, and rollback when audit append fails. Redis uses fakeredis.

Commands from backend:

```sh
poetry run python -m scripts.audit_isolated_suite --test tests/integration/test_identity_audit_repair_postgres.py --timeout 180
poetry run pytest tests/unit/test_org_service.py tests/unit/test_audit_consumer.py tests/unit/test_identity_repository.py tests/integration/test_org_endpoints.py tests/unit/test_rest_tenant_authorization.py -q --no-cov
poetry run ruff check app/modules/identity/service.py app/modules/organization/service.py app/events/consumers/audit_consumer.py tests/unit/test_audit_consumer.py tests/integration/test_identity_audit_repair_postgres.py
```

Results: **16 real PostgreSQL passes,0 skips in13.89s**, **245 targeted passes
in33.39s**, scoped Ruff passed. Isolated runner exit0; all cleanup fields true.
Runner status `partial` only denotes real Redis not requested.

Files changed in this follow-up: Identity service, Organization service, audit
consumer, audit consumer unit tests, Identity PostgreSQL regressions, this handoff.
