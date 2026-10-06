# ADR022 Network asset storage handoff

## Wire contract (recorded before implementation, 2026-09-20)

Existing routes remain **GET and POST `/api/v1/networks/{network_id}/campus/model-assets`**,
both HTTP200 with the canonical `{success,data:{items,total},meta,errors}` envelope.
POST retains the bounded (8MiB decoded) base64 request and all existing fields.
GET/POST responses continue returning actual `model_data_base64`, reconstructed
from verified object bytes for new assets; it is never silently blanked. (Superseded by
ADR-028 C4 on 2026-09-24: GET now defaults to metadata pages without
`model_data_base64`, `include_data=true` is bounded, and POST returns metadata only; see
`docs/api/ADR028-ContractChanges.md`.) Additive fields:

- `registration`: nullable `{version:1,translation:{x,y,z},rotation:{x,y,z},scale:{x,y,z},target_units:'m',target_up_axis:'y',source:string}`.
  Rotation is radians; coordinates are finite; scale is positive. Omission on an
  existing same-body update preserves registration; explicit null clears it.
  Legacy rows remain unregistered until an explicit write.
- `storage_backend`: `inline` or `local_cas`.
- `download_path`: `/api/v1/networks/{network_id}/campus-model-assets/{campus_model_asset_id}/download`.
  The existing `model_sha256` and `model_size_bytes` are the storage integrity metadata;
  filesystem paths and physical object keys are never returned.

New **GET `/api/v1/networks/{network_id}/campus-model-assets/{asset_id}/download`**
requires bearer authentication, `read:topology`, current Organization membership,
and matching network/workspace/org scope. Success is verified binary HTTP200 with
attachment disposition, digest ETag, `Cache-Control: private, no-store`, and nosniff.
Errors use the existing canonical envelope: 401/403 authorization, 404 missing or
inactive scoped identity, 503 unavailable/corrupt store, 507 storage quota admission.
No static/public volume serving or unauthenticated URL is introduced.

The asset UUID never changes its network/hash/size identity. `replace_existing=true`
soft-replaces active records with a new UUID; false updates metadata on the latest
record only for the same body, otherwise creates a new UUID. Soft-deleted and
historically referenced object bodies are retained. No automatic garbage collection.
(ADR-028 adds `python -m app.modules.network.asset_gc`, which the deployment's supervised
`asset-gc` loop runs daily. It removes only published objects that *no* asset row,
active, retired or inline, references, plus abandoned upload temporaries. Soft-deleted
and referenced bodies are still retained.)

## Ownership and implementation plan

Network asset-only model/schema/repository/service/routes, new Network storage
modules, migration0023 after0022, and focused tests. The spatial owner's shared
`network.registration` schema is reused. Registration JSONB is nullable in0023
(0022 owns scene history). No shared main/config/deploy edits. Steps: protected
atomic CAS and settings; persistence and API wiring; explicit bounded backfill/
rollback command; focused functional and available disposable PostgreSQL checks.

## Deployment and operational handoff

Separate `AssetSettings` reads `NETWORK_ASSET_*` environment variables, without
changing shared application settings. Parent composition must provision a private
persistent directory owned by the non-root backend UID, mount it for API and
operator commands, and include the **whole asset volume plus PostgreSQL** in a
coordinated cold backup/restore. Local filesystem POSIX locking/atomic publication
is required; this is not S3 or a multi-host distributed filesystem contract.

Publication precedes DB commit. A failed DB commit can retain an unreferenced
object; it must never delete a potentially shared/referenced body. Quotas count all
physical objects, including leftovers. Downloads verify bounded bytes before any
response starts. A missing or corrupt object fails closed, including compatibility
list reads. Restoring DB without its matching volume cannot restore assets.

Migration0023 does not read or rewrite existing binary payloads. Explicit backfill
and reverse-inline commands will validate each row, use bounded batches and row
locks, and commit only after durable verification. Reverse-inline must complete
for every CAS row (including soft-deleted rows) before schema downgrade; downgrade
refuses otherwise. Object files remain retained across rollback.

## Delivered settings and operator commands

`backend/app/modules/network/asset_settings.py` reads these environment variables
directly (no shared config or `.env` loader modification):

| Variable | Default | Meaning |
| --- | --- | --- |
| `NETWORK_ASSET_ROOT` | `/var/lib/nanfo/network-assets` | Pre-provisioned absolute private directory, mode0700, owned by API/operator effective UID. Every path component must be non-symlink. |
| `NETWORK_ASSET_MAX_OBJECT_BYTES` | `8388608` | Admission bound, configurable downward only; reads retain the original8MiB bound. |
| `NETWORK_ASSET_MAX_TOTAL_BYTES` | `1073741824` | Physical byte admission cap, including abandoned upload files and unreferenced retained objects. |
| `NETWORK_ASSET_MAX_OBJECTS` | `10000` | Physical file admission cap,1..1000000. Deduplication consumes no new quota. |

The process refuses filesystem access as root. Provision the volume as the same
non-root UID for API and backfill. It is deliberately not created automatically.
Files are digest-named, mode0400; publication uses fsync, an exclusive directory
flock and no-replace atomic linking, then directory fsync. Reads reject nonregular
files, symlinks, foreign ownership, group/world permissions and external hardlinks.
Failed publication removes only its own temporary file. It never removes a
published object. A crash may leave temporary/unreferenced bytes: those count
toward quota and require a future owner-aware maintenance decision.

Apply0023 after the spatial owner's0022 before running this application version.
0023 adds nullable registration JSONB, `storage_backend`, nullable inline text,
storage consistency constraints and a database trigger protecting UUID/network/
SHA256/size identity. Model MIME and filename remain metadata; download uses
`application/octet-stream` and a safe UUID-based `.bin` attachment filename.

From `backend/`, with existing PostgreSQL environment and the same volume settings:

```bash
poetry run python -m app.modules.network.asset_backfill to-cas --limit 10
poetry run python -m app.modules.network.asset_backfill to-inline --limit 10
```

Each command processes one transaction of1..100 locked records, including deleted
records, returning JSON `{direction,processed,last_asset_id}`. Repeat without a
cursor until `processed` is0; already converted records are excluded. Optional
`--after <uuid>` is exclusive keyset continuation, not proof all earlier rows were
converted. Bad bytes, missing files or commit failures roll back the whole current
batch; earlier successful batches remain durable. Registration is untouched by
both commands. Dry-run/delete/GC operations are not part of this command.

For rollback: stop writers, retain a coordinated backup, run `to-inline` until0,
then downgrade0023 to0022 and deploy the old application. The SQL downgrade guard
checks **all** rows, including soft-deleted ones, so an incomplete conversion cannot
silently discard object references. Downgrade removes registration JSONB: retain
the pre-downgrade DB backup to recover that metadata. The object volume remains
untouched and must still be retained for backups/history. Upgrading again does not
infer registration or auto-migrate inline bodies.

Storage failures are handled as `CAMPUS_MODEL_ASSET_STORAGE_UNAVAILABLE`503;
hash/length mismatches as `CAMPUS_MODEL_ASSET_INTEGRITY_FAILED`503; admission quota
as `CAMPUS_MODEL_ASSET_QUOTA_EXCEEDED`507. The canonical shared error handler is used,
including its existing request-ID behavior (echoes `X-Request-ID` when supplied).
Network row locks serialize asset writes. Owner authority is reloaded after lock
waits and filesystem work; downloads also recheck owner authority/active identity
after reading verified bytes. Compatibility list reads recheck owner authority.

## Validation (2026-09-20)

**153 focused/regression tests passed**, plus **6 real PostgreSQL tests passed**.
Scoped Ruff and `git diff --check` passed. CLI `--help` was also executed.

```bash
poetry run pytest tests/unit/test_asset_storage.py tests/unit/test_asset_service.py tests/unit/test_network_schemas.py tests/unit/test_network_service.py tests/integration/test_asset_endpoints.py tests/integration/test_network_endpoints.py -q --no-cov
ASSET_TEST_DSN='<isolated-postgresql-dsn>' poetry run pytest tests/integration/test_asset_postgres.py -q --no-cov
```

Coverage includes concurrent dedup/quota admission, restart reads, tamper/size/hash
checks, symlink parent/root/body and traversal refusal, hardlinks/private modes,
non-root requirement, injected atomic-publication failure, actual CAS downloads,
legacy base64 compatibility, permission and membership revocation, foreign/deleted
asset denial, canonical error envelopes, nullable registration preserve/clear,
new UUID on changed content, and DB failure retaining objects without references.

Real PostgreSQL runs exercised the complete chain through0023 and0023→0022→0023
in UUID-owned schemas, persistence in fresh sessions, SQL immutable-identity guard,
soft-deleted backfill/reverse, downgrade refusal, corrupt-batch atomic rollback,
replacement rollback after injected commit failure, and real current-membership
revocation while a writer is blocked on a network lock with stale ORM membership.

The disposable non-root cluster is `/tmp/opencode/assets-postgres-PUeIOZ`, socket
only, port55493. All test schemas were dropped; the cluster was stopped after the
final run. No Docker or deployment database was used; no commits were created.
An initial API-test assertion expected an automatically generated error request ID;
the fixture was corrected to supply the documented `X-Request-ID`, preserving the
existing shared handler behavior. Final runs above are green.

Parent integration remains: provision/mount/configure the private persistent volume,
include it in cold backup/restore, apply the final migration chain and run integrated
deployment/restore acceptance. This workstream claims the isolated source/DB gates,
not deployment backup qualification or a frontend binary-download migration.

## Security review corrections (2026-09-20)

Confirmed both supplied reproductions before editing:
`poetry run pytest -c pyproject.toml /tmp/opencode/test_adr022_backend_review.py -k 'crash_after_link or upload_commits_after_revocation' -q --no-cov`
reported **2 passed, 3 deselected** (those assertions demonstrate the defects).

- **P1 interrupted hard-link publication:** reads and writes now hold the same
  exclusive directory lock while recovering interrupted publication. Recovery
  removes only a `.upload-<32 lowercase hex>` name for an owned, mode0400 regular
  inode with exactly two links, whose bounded bytes hash to the other same-inode
  digest name in this protected directory. Descriptor and both names are checked
  again before unlink; the digest remains intact and the directory is fsynced.
  External/additional hardlinks, unknown aliases, symlinks, mismatched digests and
  unpublished standalone temporary files are not removed or excused from storage
  validation. Regular unrelated files remain untouched and count toward quotas.
  Reads serialize with publication, avoiding exposure to the transient two-link
  state of an active writer as well as recovering a stopped writer's state.
- **P2 final-read authority race:** `CampusModelAssetService.upsert_asset` now
  expires the identity map and rechecks current Network/Organization write access
  after awaited response construction and immediately before commit. A denial
  rolls back the flushed replacement/soft-deletes while retaining published bytes.

Changed source: `backend/app/modules/network/asset_storage.py` and only the
asset-service class in `backend/app/modules/network/service.py`.
Regression files: `backend/tests/unit/test_asset_storage.py`,
`backend/tests/unit/test_asset_service.py`, and
`backend/tests/integration/test_asset_postgres.py`; this handoff was also updated.

Final checks: **162 scoped/regression tests passed**, **8 real PostgreSQL tests
passed**, scoped Ruff and whitespace checks passed. The commands are the same
scoped pytest/PG commands recorded above. New tests use actual subprocess exit
after `os.link`, fresh store instances with read-first and unrelated-upload-first
recovery, protected unrelated aliases, and real database member removal/downgrade
committed while the final worker-thread read is blocked. They retain stale ORM
membership and verify403, unchanged prior asset metadata and retained object bytes.
The private socket-only PostgreSQL cluster was restarted for these checks and
stopped afterward; test schemas were dropped.

**Parent deployment action:** rebuild the backend image from these corrected source
files and refresh integrated asset/backup/restore acceptance against that image.
Earlier image verification does not cover these fixes. No dependency, shared
configuration, deployment source, migration or wire-contract changes were needed.
