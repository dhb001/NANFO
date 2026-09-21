# Package Validation

## Integrated0029 verification — 2026-09-20,21:02 UTC

User-approved current-source contract advances to0029, preserving the external
telemetry-coverage invalidation migration unchanged. It adds no tables;0028
experimental ownership and0027 archive/autonomous safety floors still apply.
Historical0027 **and0028** matrices remain exportable unchanged; current lifecycle
refuses both old markers. Exact chain checks now cover0029→0001 through the
centralized target. The historical measured-twin target remains0027.

```bash
# From backend/, after the full isolated suite completed:
PYTHONPATH=..:. poetry run pytest -c pyproject.toml ../deploy/tests ../deploy/test_lifecycle.py -q --no-cov
poetry run pytest tests/unit/test_runtime_health.py tests/unit/test_verify_measured_twin.py tests/integration/test_readiness.py scripts/test_audit_isolated_suite.py -q --no-cov
```

**248 deployment tests passed in5.01s** (all prior244 plus4 additional historical/
current compatibility cases). **87 runtime/readiness/verifier/runner tests passed
in3.91s**. The full owned PostgreSQL default lane separately passed253, skipped12
Redis-dependent cases, failed0; details in `AuditRepair-Verification.md`.
These supersede the prior schema-drift failure, without relabeling earlier evidence.
No live Docker deployment acceptance or existing-store migration is claimed.

## Current-source compatibility repair — 2026-09-20

Source target0028 now agrees across fresh initialization, runtime readiness,
maintenance, lifecycle metadata/adoption and the deployment verifier. The existing
runtime-health0028 work was preserved, replacing its literal with the centralized
dependency-free `app.core.schema_version.CURRENT_SCHEMA`. Host CLIs import that
same contract through `deploy/schema_contract.py` without backend dependencies.
New verifier runs use `migration_0028`; original0027 matrices remain exportable
without renaming or changing statuses. Historical records below are not rewritten.

Fresh start verifies the actual installed maintenance checkpoint before issuing a
current marker. Historical0027 markers/archives cannot be adopted by current
composition; no implicit upgrade is added. Cold restore can still authenticate and
use exact historical images with their own maintenance tooling. Archive safety
requirements use revision floors:0027+ retains archive and autonomous release
proof,0028+ also requires experimental ownership fully released. Maintenance checks
all three experimental ownership dimensions without mutation, and restored proof
is compared to the authenticated source checkpoint before session invalidation.

Offline verification (from `backend/`):

```bash
PYTHONPATH=..:. poetry run pytest -c pyproject.toml ../deploy/tests ../deploy/test_lifecycle.py -q --no-cov
poetry run pytest tests/unit/test_runtime_health.py tests/unit/test_verify_measured_twin.py tests/integration/test_readiness.py -q --no-cov
```

**244 deployment tests passed** (original216 plus28 compatibility regressions),
**76 runtime/readiness/historical-verifier tests passed**. Scoped Ruff passed.
Direct host `python deploy/{manage,verify,release_manifest}.py --help` imports passed
without initializing app settings or requiring backend dependencies. An initial
deployment-only command omitted the required repository PYTHONPATH/config and
failed collection; the explicit command above is the verified invocation.

No Docker build, service mutation, schema upgrade, live deployment acceptance or
historical-image certification was performed. New0028 live acceptance remains
required before claiming a new accepted release; source consistency and unit
tests do not substitute for that evidence.

## Current ADR021 Inspection — 2026-09-19

**Read-only inspection complete; live acceptance not run.** The five ADR020 rebuild
images in `core-build-adr020-current.json` are present as Linux/amd64. The
Compose-pinned PostgreSQL 17.6 and Redis 7.4.5 images are absent. Existing verifier
capacity check reports 276,187,082,752 bytes available on Docker's `/home` filesystem
and 7,969,120,256 bytes on staging, above its 1 GiB minimum. No build, pull, container
lifecycle, migration, pruning or lab command was executed.

ADR021 migration 0020/0021 integration, source-matched release images, persistent
full build records and missing pinned stores block acceptance. Initializer,
runtime-health and verifier assertions still target 0019 at inspection time; parent
must align these before the serialized run. Current images predate the latest
frontend/ADR021 changes. Optional frozen checkpoint is absent despite an available
AI runtime image.

New `release_manifest.py` creates/verifies exact-byte lock/source/build-record
manifests and atomically exports bounded, allowlisted status/resource evidence
with original and exported checksums. Secret/key directories and free-text
diagnostics are excluded; export preserves failed/blocked statuses. It is offline
integrity tooling, not a live acceptance result or a replacement for encrypted
backups. 24 release tests and 46 verifier tests pass; 76 operations/lifecycle tests
pass with the existing backend interpreter.

Exact IDs, missing store digests, prerequisites, safe integration command template,
evidence export instructions and limits:
[`CompletionProgram/Deployment.md`](../docs/project/CompletionProgram/Deployment.md).

## Previous Resume Status — 2026-09-14 (Historical)

**Authorized resume on 2026-09-14: BLOCKED by missing pinned images, not disk.**
The live command ran with `deploy/core-build-adr020-final.json` and all four exact
image IDs. Result: **4 passed, 0 failed, 24 blocked**, exit code 1.
Evidence: `/tmp/opencode/nanfo-deploy-verify-i3nv_lbp/evidence/result.json`.

- No verifier processes, containers, or volumes existed before this resume. The
  previous `/tmp/opencode` evidence directories were already absent; they were not
  removed by this attempt and cannot be recovered from the current filesystem.
- Docker now reports `/home/.system-data/docker`, on the `/home` filesystem with
  282,511,859,712 bytes free. Staging had 8,004,255,744 bytes free. Capacity passed.
- The daemon has **none** of backend `b69f37...be108`, frontend `9f820...ac96d`,
  Neo4j `ec702...bee62b`, or operator lab `d91efe...3c05c`. The older backend
  `00aad...ea1ee` is not an acceptable substitute. No matching image exports were
  found under the operator home directory.
- The packaging stack is not currently running: only three stopped packaging
  worker containers are visible. Its nine named volumes still exist. The original
  stopped lab container is not visible in this daemon. These are observations of
  the resumed environment, not changes made by the verifier.
- Cleanup passed with **zero created/removed resources**. No images were built,
  pulled, retagged, or deleted. No shared database or packaging volume was changed.
- Fresh migration, actual congestion/manual control, negative readiness, queued
  restart recovery, encrypted backup, and distinct-project restore remain unproven.
  Optional AI remains blocked separately. **Step 15 is not complete.**

Required next action: recover/load the original four exact images into the current
Docker daemon from the original Docker store or exported archives. If they cannot
be recovered, a separately authorized reproducible rebuild and new recorded image
pins are required; rebuilding cannot silently stand in for the missing exact IDs.

The executed command is ready to rerun once the exact images are restored:

```bash
python3 deploy/verify.py --live --agents-idle --lab \
  --reuse-build-record deploy/core-build-adr020-final.json \
  --backend-image sha256:b69f37bb8f5404b6ef81beef965f11ba90aba7e3ddf0ceec7f66a1ee7e8be108 \
  --frontend-image sha256:9f8206ed5a0a8553fe5ec27ebcfd47e3d3539fcf87fa50a838e161c4996ac96d \
  --neo4j-image sha256:ec7023058bfc067054cd89778bde826ffe22a97c25dd96647a9ff9f47bbee62b \
  --lab-image sha256:d91efe1717f29a277683b735418877d73243ae24ab80e4c2c3311f6f0343c05c
```

Resume fixes: structured JSON build-record support, explicit missing-image blocked
case before resource creation, protected Docker directory capacity measured at its
kernel-reported containing mount, and binding schema-serialization regression fixture.
**44 verifier tests pass**, scoped Ruff and formatting pass. Installed parity now
inspects the exact image in a registered read-only/no-network helper, not the
packaging stack. No application function is invoked as a substitute for acceptance.

## Historical Attempts

**Parent-authorized live preflight ran on 2026-09-12 and is BLOCKED. Step 15 is not complete.**
Result: **4 passed, 0 failed, 24 blocked**, exit code 1. Evidence:
`/tmp/opencode/nanfo-deploy-verify-5z12cncf/evidence/result.json`.

- Docker storage had 868,569,088 bytes free (about 828 MiB), below the required
  1,073,741,824-byte minimum. Staging on `/tmp` had 7,936,843,776 bytes free, but
  that does not expand default Docker named-volume storage. No tmpfs-driver volume
  workaround was used: the cold-backup contract refuses driver options.
- The pinned backend's installed `deploy/maintenance.py` and worker health source
  match current source. Its `backend/app/api/readiness.py` does not: the image lacks
  the subsequently added report-storage capacity check. This is recorded separately
  from prior locked-build provenance; the existing image was not rebuilt or retagged.
- Prior core locked builds are referenced from `deploy/README.md` with its SHA256,
  exact backend/frontend/Neo4j image IDs, and installed-source hashes. The existing
  operator lab image was inspected only. **Zero builds and zero pulls** occurred.
- No verifier containers, volumes, networks, database migrations, or backups were
  created. Cleanup passed with zero registered resources. All ten packaging services
  remained healthy; the original stopped lab remained stopped and unchanged.
- Optional AI is blocked: its final image is unavailable and the parent prohibited
  further large builds. Dependency-stage success is not inference acceptance.

An earlier attempt at `/tmp/opencode/nanfo-deploy-verify-h8yw0wgy/evidence/result.json`
recorded the image/source mismatch as a failed build check. It is retained; the final
run separates build provenance, installed-source parity, and disk capacity correctly.

To unblock, free or expand Docker storage to at least 1 GiB available (about 196 MiB
above the final measured free space; additional operational margin is preferable),
without pruning unrelated resources. Integrate the current readiness/storage changes
into a small runtime image using existing dependency layers, record its new exact ID
and provenance, and rerun. No full reinstall or large AI image rebuild is required.

Owned files: `deploy/verify.py`, `deploy/tests/test_verify.py`, this document only.
No existing deployment or stopped original lab is migrated, restarted, or removed.

## Commands

Run verifier-only tests without application dependencies or Docker:

```bash
python3 -m unittest discover -s deploy/tests -p test_verify.py -v
ruff check deploy/verify.py deploy/tests/test_verify.py
python3 deploy/verify.py --help
```

After all contributing agents have finished and the parent explicitly authorizes
live execution, run from the repository root:

```bash
python3 deploy/verify.py --live --agents-idle --lab --model
```

For the Step 15 campaign without optional historical model diagnosis:

```bash
python3 deploy/verify.py --live --agents-idle --lab
```

The authorized low-disk attempt used this exact no-build command (currently blocked
by the conditions above; update the build record and backend ID after integration):

```bash
python3 deploy/verify.py --live --agents-idle --lab \
  --reuse-build-record deploy/README.md \
  --backend-image sha256:00aad16e9ef1763c3b62fdc61aa2f34c9855f42e62edf6ef0cc87b58e14ea1ee \
  --frontend-image sha256:9f8206ed5a0a8553fe5ec27ebcfd47e3d3539fcf87fa50a838e161c4996ac96d \
  --neo4j-image sha256:ec7023058bfc067054cd89778bde826ffe22a97c25dd96647a9ff9f47bbee62b \
  --lab-image sha256:d91efe1717f29a277683b735418877d73243ae24ab80e4c2c3311f6f0343c05c
```

Reuse mode requires all exact core IDs, a prior build record containing those IDs
and locked-build evidence, and an existing exact lab ID when `--lab` is requested.
It refuses `--model` so an optional AI rebuild cannot happen implicitly. The running
packaging API is inspected read-only to compare installed maintenance/readiness
source; its database and lifecycle are not verification targets.

Both authorization flags are mandatory. `--agents-idle` is an explicit operator
attestation, not an unreliable process-name detector. Source fingerprints detect
changes across the build/campaign and invalidate the result. Do not start a build,
test that modifies source, training run, or other acceptance campaign concurrently.

Host prerequisites: Python 3.12+, Docker Engine, Compose v2 with Dockerfile-specific
ignore support, sufficient disk/RAM, and the delivered backup operator tool's
`cryptography` dependency. The verifier installs **no host packages**. Backend,
frontend and optional AI dependencies are installed in actual Docker build stages
from their locks. Build cache is allowed; host virtual environments and application
packages are not acceptance inputs. The optional AI image can be large even though
the selected checkpoint is small. The copied artifact set is bounded to 32 MiB;
no full training tree or original model directory is archived.

## Case Matrix

Each run writes a named matrix with `passed`, `failed`, or `blocked`, plus counts.
Not-run prerequisites become blocked, never successful placeholders.

| Case | Required Evidence |
| --- | --- |
| `disk_capacity` | At least 1 GiB available on Docker storage and staging before creating any fresh stores |
| `installed_source_parity` | Installed maintenance/readiness bytes match current source, or fresh fingerprinted build |
| `package_contract` | Delivered Compose/initializer/operator interfaces, pinned bases and locked install stages |
| `locked_container_build` | Actual Docker builds, or explicitly referenced prior locked-build record and exact inspected image IDs; never label reuse a new build |
| `fresh_volumes` | New UUID project, absent prior volume names, every created volume independently observed empty before initialization |
| `migration_0019` | Fresh-only installed initializer; actual database revision exactly `0019` |
| `bootstrap_login` | Dedicated bootstrap actor, generated protected password, authenticated login and Admin profile |
| `frontend_http` | Gateway HTML root, fetched built JS/CSS rather than SPA fallback, API liveness; not browser/Playwright acceptance |
| `full_stack_readiness` | Gateway canonical `/ready` and all five actual worker healthchecks |
| `simulation` | Authenticated configured finite-buffer simulation; worker completion and independent 45% loss expectation |
| `report_csv` | Worker-generated download; actual CSV simulation cells, SHA256, media type and length |
| `report_pdf` | Worker-generated download; PDF page streams decoded independently for simulation text, SHA256 and length |
| `database_stop_readiness` | Actual PostgreSQL stop, canonical `/ready` 503 with database failure, `/health` 200, dependency recovery |
| `worker_stale_heartbeat` | SIGSTOP of PID read from the work-loop heartbeat, not tini; stale-heartbeat failure while stores remain healthy; SIGCONT recovery |
| `api_worker_restart` | Jobs accepted while workers stopped; API and all worker start timestamps change; pending simulation/report complete |
| `lab_binding` | Installed topology manifest, authenticated inventory creation, protected operator file mounted at the exact runtime path; disconnected scoped lab |
| `lab_congestion` | Actual iperf/OVS/qdisc congestion, API measured telemetry, approved manual shaping with independent readback and throughput change, explicit restore |
| `model_diagnostic` | Independent locked AI interpreter inside actual API image, frozen copied artifacts and registry read-only, authenticated historical inference, hashes and non-actuation flags |
| `coordinated_encrypted_backup` | Delivered operator CLI quiesces/checkpoints/stops owners; all named volumes and operator binds encrypted; manifest HMAC and payload checksums validated |
| `distinct_fresh_restore` | Different UUID project, no existing target containers/volumes, distinct empty bind roots, operator authentication/extraction/verification |
| `restore_image_schema` | Exact local image IDs/OS/architecture pinned through override; `0019` retained without target migrations |
| `old_tokens_invalid` | Unexpired source access token and old refresh token rejected, new authenticated login accepted |
| `restored_report_bytes` | Same report IDs, byte hashes, lengths and snapshot receipts for CSV/PDF and restart job |
| `restored_workflows` | Identical configured-model output/checkpoint and physical workflow provenance; restart job retained |
| `restored_telemetry` | Nonempty actual persisted telemetry in a fixed historical interval has identical row identities/values after restore |
| `source_unchanged` | Campaign fingerprint equals build input fingerprint |
| `campaign` | Overall orchestration returned without an unclassified exception |
| `cleanup` | Only registered owned container IDs, volume names and network IDs removed within a total 120-second bound |

`core_passed` excludes the optional lab/model/telemetry capabilities.
`step15_complete` additionally requires configured lab binding, actual congestion
control, nonempty telemetry survival, restart and restore. Model diagnosis is not a
Step 15 physical-control gate. `all_green` is false if **any** case is blocked.
The exit code is zero only for Step 15 completion, and also requires model diagnosis
if `--model` was requested. A core-only run can pass its core cases and still exit
nonzero, correctly leaving Step 15 incomplete.

## Isolation And Secrets

Projects are generated internally as `nanfo-deploy-verify-<32 hex UUID>`; no CLI
argument accepts an existing project or API URL. PostgreSQL/Redis/Neo4j and workers
publish no host ports. Only the gateway receives an engine-assigned random
`127.0.0.1` port. Lab ports/interfaces live in its disconnected namespace, so they
cannot collide with the original stopped lab. No broad prune, Compose down, old-lab
reset, Docker-socket application mount, host networking, or host PID namespace is
used. Operator helper containers get only explicitly owned paths/volumes.

All state is below a newly created private directory under `/tmp/opencode` (or an
explicit existing `--work-root`). Its subdirectories are separated:

| Directory | Contents |
| --- | --- |
| `evidence/` | Credential-free result and append-only registered resource ledgers |
| `secrets/` | Random bootstrap and store/auth secrets, mode 0600 |
| `keys/backup.key` | Exactly 32 random raw encryption-key bytes, mode 0600, outside evidence and backup |
| `backup/` | Protected authenticated manifest and encrypted GCM payloads only |
| `binding/`, `models/`, `model-registry/` | Generated operator inputs; copied originals remain unchanged |
| `restore/` | Distinct restore bind roots and private copies of required external secrets |

Passwords/tokens are never command arguments, printed diagnostics, report fields,
or saved in evidence. Subprocess output is withheld on failure. Generated operator
copies become root-owned/read-only for the runtime trust checks; original frozen
artifacts are never chmod/chowned. Backup encryption keys and external secrets must
be retained separately from any evidence shared with others. Docker images/build
cache and private encrypted archives are intentionally retained, not pruned.

Cleanup registers only resources with the generated project labels, rechecks
ownership before deletion, and ignores already-removed container incarnations.
The total cleanup deadline is 120 seconds; a failure leaves a failed matrix case
and an exact resource ledger for operator review. SIGINT/SIGTERM trigger bounded
cleanup; SIGKILL or host loss cannot be recovered automatically. No automatic
cleanup targets are reconstructed from an old lab or shared namespace.

## Parent Handoff

Before live authorization, confirm these cross-agent contracts against final files:

- Compose services `volume-init`, `initialize`, stores, `api`, all five `*-worker`
  services and `gateway`; `NANFO_STATE_DIR`, project/image/email variables and random
  port `NANFO_HTTP_PORT=0` still match.
- `backup_restore.py` supports its `backup`, `verify`, `restore` CLI and encrypted
  read-only bind directories, including distinct empty restore binding/model roots.
- Installed `deploy.maintenance` at `/opt/nanfo/deploy/maintenance.py` supplies
  `quiesce`, `checkpoint`, and `restore-verify`. The operator stops admissions and
  writers; there is no fictional application maintenance latch to release.
- Restore validates report receipts/schema and invalidates only old session
  families/API lease, preserving streams/jobs. No physical command may replay into
  the new project; restored API/workers start in production/stub mode and the lab
  stays stopped.
- Optional frozen interpreter satisfies confinement and runtime dependencies.
  An actual diagnostic 503 is blocked, never a host fallback or fabricated result.
- All contributing agents are idle. Review final diffs before running the command.

Current verification: **42 verifier unit tests passed**, scoped Ruff/format passed.
Authorized live preflight executed and blocked safely. No new live install,
migrations, lab, restart, backup, or restore is claimed.
