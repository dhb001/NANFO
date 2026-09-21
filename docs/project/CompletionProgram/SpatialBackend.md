# ADR-021/022 spatial backend handoff

## ADR-022 registration/history handoff (2026-09-20)

Contract is recorded before implementation in `docs/api/SpatialScene.md` under
ADR-022. Asset agent: import
`from app.modules.network.registration import AssetRegistration` and use nullable
`registration: AssetRegistration | None = None` on the existing asset request/response.
Persist its `model_dump(mode="json")` as JSONB in **0023**, leaving legacy null.
**0022 is history only**, per the user's explicit override of the ADR's initial split.

Exact registration object: `{version:1,translation:{x,y,z},rotation:{x,y,z},scale:{x,y,z},target_units:'m',target_up_axis:'y',source:string}`.
All fields required, extras forbidden, strict version, finite numeric translation
±1e6m, rotation±2π radians, positive bounded scale[1e-6,1e6], nonblank source≤128
characters/no NUL. Matrix `T × Rz × Ry × Rx × S`. Null means unregistered.

Frontend history routes: GET `/api/v1/networks/{network_id}/spatial-scene/history`
with `page` (default1) and `page_size` (default20, max100), envelope data
`{items:[{revision,recorded_at,actor_id,origin,object_count}],total,page,page_size}`.
Origin is `baseline` or `replacement`; baseline actor is null. Descending revisions.
GET `.../history/{revision}` returns the scene document directly in envelope data.
Restore strips historical `revision` and PUTs the remaining scene with the current
expected revision. No geometry extension is added in this increment.

### ADR-022 delivered and verified

- `0022_spatial_scene_history.py` imports owning metadata, creates immutable full
  revision bodies and copies each existing snapshot at its real current revision
  as a baseline (unknown actor). No missing historical bodies are invented.
  A snapshot-table write barrier protects baseline copying; drain old scene writers
  before deployment. Downgrade removes history only and preserves the current scene.
- Every successful replacement appends one new body in the same transaction as
  snapshot and audit. Database triggers reject UPDATE, DELETE and TRUNCATE history.
  History network references intentionally do not cascade on hard deletion.
- Both history routes use live membership and claim checks after expiration of ORM
  caches. Existing post-lock write authority checks remain. List counts and metadata
  use one SQL snapshot; independent pages are live offset views, not frozen exports.
- Final scoped gate: **164 passed in17.12s**, including **24 real PostgreSQL tests**
  and140 validator/registration/service/HTTP tests. Scoped Ruff and whitespace pass.
  Verified0022 upgrade/downgrade and an existing revision2 baseline; history database
  immutability; first/existing concurrent winners; history/audit/commit failure rollback;
  uncommitted history invisibility; exact pagination/out-of-range count; history reads
  after revocation; six real lock-barrier write-revocation races with stale ORM state;
  tenant/network isolation; restore as revision+1; stale inventory rejected on restore.
- Private PostgreSQL cluster `/tmp/opencode/spatial-postgres-OwjAhH` was restarted
  for the gate, test schemas dropped and cluster stopped afterward. No Docker,
  deployment/config/main/shared Network file edits or commits by this workstream.

```bash
# From backend/; use a private authorized PostgreSQL DSN for the real database gate.
SPATIAL_TEST_DSN='<private-dsn>' poetry run pytest tests/unit/test_spatial_scene.py tests/unit/test_spatial_registration.py tests/integration/test_spatial_endpoints.py tests/integration/test_spatial_postgres.py -q --no-cov
poetry run ruff check app/modules/network/spatial*.py app/modules/network/registration.py app/api/v1/spatial.py alembic/versions/0022_spatial_scene_history.py tests/unit/test_spatial*.py tests/integration/test_spatial*.py
```

## Delivered

Network owns canonical spatial scene snapshots and replacement through:

- `backend/app/modules/network/spatial_schemas.py`: exact version1 wire models,
  bounded finite transforms, strict integers/numbers, hierarchy/cycle/ID checks,
  provenance and unique device association rules.
- `spatial_transforms.py`: pure explicit local-to-world transform composition.
- `spatial_models.py`, `spatial_repository.py`: owner-only PostgreSQL snapshot,
  insert-on-conflict plus conditional revision update, inventory scope locks.
- `spatial_service.py`: existing public Network/Organization access checks,
  owner transaction and public Identity audit append, fail-closed rollback.
- `backend/app/api/v1/spatial.py`: GET/PUT route with live session/permission checks
  and canonical response envelopes.
- `backend/alembic/versions/0021_network_spatial_scene.py`: frozen reversible DDL,
  down-revision0020 and explicit import of owning table metadata.
- `0022_spatial_scene_history.py`: immutable owner history and snapshot baseline.
- `backend/app/modules/network/registration.py`: agreed schema for the asset owner.

Exact contract/design was written before implementation in
[`docs/api/SpatialScene.md`](../../api/SpatialScene.md). It is the canonical source
for field requirements, hierarchy rules, error codes, transform order and limits.
Audit action `network.spatial_scene.replaced` is a local append through the public
Identity service, not a new domain event. No publication path is added.

## Parent integration

Register in the application composition:

```python
from app.api.v1.spatial import router as spatial_router
app.include_router(spatial_router)
```

Apply the migration chain through **0022**, after0021 and the outbox's0020.
The router's schema/service import registers spatial model metadata at runtime;
the migration itself also imports it. No new dependency or configuration required.
Existing main exception handlers provide canonical error envelopes.

Public backend service is `SpatialSceneService(db, redis)` with `get_scene(...)`,
`replace_scene(...)`, `list_history(...)` and `get_revision(...)`.
All accept actor and optional narrowing workspace/org
claims. PUT also takes the typed request and correlation ID. HTTP permission checks
remain in the router; non-HTTP callers must supply authenticated authorization.
Service methods use request-scoped sessions; successful replacement owns commit.

## Historical ADR-021 verification (2026-09-19)

**103 tests passed**, comprising87 no-infrastructure validator/transform/service/API
tests and16 real PostgreSQL tests. JWT/session validation, current identity
permission reload and Organization membership rules run as production code in
API tests; only persistence infrastructure is substituted there.

```bash
# From backend/, using its existing Poetry environment:
poetry run pytest tests/unit/test_spatial_scene.py tests/integration/test_spatial_endpoints.py -q --no-cov
SPATIAL_TEST_DSN='<authorized-disposable-postgresql-dsn>' poetry run pytest tests/integration/test_spatial_postgres.py -q --no-cov
poetry run ruff check app/modules/network/spatial*.py app/api/v1/spatial.py alembic/versions/0021_network_spatial_scene.py tests/spatial_support.py tests/unit/test_spatial_scene.py tests/integration/test_spatial*.py
```

Initial combined run: `96 passed in 10.98s`; after the P2 authority fix, scoped
runs passed `87 passed in 2.15s` and `16 passed in 7.14s`. Scoped Ruff and `git diff --check`
passed. PostgreSQL tests performed the entire migration chain through0021,
downgraded to0020 and upgraded again inside each UUID-owned test schema. They
verified:

- Initial GET revision0 with no materialized row; successful PUT reload in a fresh
  session; whole-scene replacement/removal and monotonic revisions.
- Exactly one winner/one409 for simultaneous first writes and existing revisions.
- Audit and scene both roll back after an actual audit insert followed by failure,
  for first and existing scenes; injected commit failure also rolls both back.
- Uncommitted replacements remain invisible to independent readers.
- Foreign, missing and deleted device references are rejected without mutation.
- Real database membership downgrade and network soft-deletion enforcement.
- Stale initial expected revision leaves no placeholder scene or audit behind.

Local PostgreSQL binaries were used without Docker. The isolated cluster was at
`/tmp/opencode/spatial-postgres-OwjAhH`, Unix socket only, port55483, owned by this
workstream. All test schemas were dropped and the cluster was stopped after the
final run. Its disposable data and `server.log` remain outside the repository.
No deployment database was migrated and no commits were created.

### P2 authority refresh after blocking owner locks

- Confirmed the supplied read-only reproduction before the fix with
  `poetry run pytest -c pyproject.toml /tmp/opencode/test_adr021_readonly_review.py -k membership_revocation_during_spatial_lock -q --no-cov`
  (`1 passed, 2 deselected`: its assertion demonstrated the unauthorized commit).
  The initial invocation without `-c` did not load the project's asyncio mode;
  the corrected invocation reproduced the defect.
- Separated scene lock preparation from conditional replacement so the final
  authority check follows **all** network/device/scene lock waits, including
  concurrent first-insert contention. Expiring the session identity map ensures
  public Network/Organization service queries reload database state rather than
  returning retained stale membership roles. No owner snapshot replacement or
  audit occurs until that check succeeds; denial rolls back tentative placeholders.
- Six deterministic real PostgreSQL regressions cover both member downgrade and
  removal at each of network, device and scene row-lock barriers. They verify
  actual blocking via `pg_blocking_pids`, commit revocation on another session,
  retain a stale ORM member object and assert403 plus unchanged snapshot/audit.
- The private Unix-socket cluster above was restarted for these tests and stopped
  afterward. Only spatial-owned files/tests/docs changed; router registration is
  still owned by parent integration.

## Limits and remaining acceptance

- Parent still owns `main.py` registration, integrated regression/release gates,
  frontend wiring and journal/sprint summaries. This workstream did not edit shared
  dependency/config/deployment composition or existing Network service source.
- Scene limits:10,000 objects,128-character IDs/source,256-character names,
  local positions±1,000,000m, rotations±2π radians; revisions are JavaScript-safe
  integers. All nullable wire fields remain required.
- Parent types must strictly precede child types in the documented hierarchy;
  skipped levels and roots other than interfaces are allowed. Interfaces require
  direct device parents; only device objects carry `device_id`.
- Provenance is supplied metadata, not measured calibration. Fallbacks must remain
  explicitly labeled `schematic-fallback` with unknown accuracy. Asset coordinate
  conversion/registration must be explicit; no generated positions are persisted
  automatically. Matrix order is `T × Rz × Ry × Rx` with radians and local-to-parent
  coordinates; frontend/renderers must match this order explicitly.
- Device references are validated/locked during writes. A later independent
  inventory removal does not rewrite a historical saved placement automatically;
  subsequent PUT must clear or replace that reference. No new deletion event or
  reconciler is introduced.
- ADR-022 retains immutable full bodies from its migration baseline onward; earlier
  missing revisions remain unavailable. Asset persistence and binary storage are the
  asset agent's0023 workstream. No Neo4j projection, RF fidelity, production capacity
  or physical-network acceptance is claimed. History storage has no automatic pruning.
- Combined frontend/backend operation and full application regression remain parent
  acceptance work; scoped tests do not imply those gates passed.
