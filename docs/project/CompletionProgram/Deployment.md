# ADR021 P0 Release Evidence and Deployment Handoff

## Final asset-security correction accepted — 2026-09-20

**Latest source-matched0024 core result:26 passed,0 failed,4 optional blocked;
`core_passed=true`, `failure=null`.** This is the final accepted backend after
the delivered `asset_storage.py` publication-recovery fix and
`CampusModelAssetService` final authorization recheck before commit. Previous
results remain preserved as pre-correction evidence.

Only backend runtime source/COPY layers were rebuilt. Poetry main-install/pip-check
dependency layers were cached unchanged; no dependency reinstall, frontend build,
pull, SNMP change or emulation/model execution. Independently compared frontend,
nginx, lock/project manifests and Neo4j source hashes with prior accepted snapshot.
Only the two production asset files and three asset test files differed.

| Final accepted role | Exact image ID |
| --- | --- |
| Backend/API/six workers/init/maintenance | `sha256:feecb2f3ad41554364df2ef745d0ace4de8be83cf96f1e90bc1417990a62eeba` |
| Unchanged frontend | `sha256:712b31ddc68c7757eb6eda1a54bbd9c83feab6bc8720ed675e36d331a1c116a6` |
| Unchanged Neo4j wrapper | `sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7` |

Frozen snapshot `/tmp/opencode/nanfo-adr021-core-source-qtsyac8_`,860 files,
source-map SHA256 `2205f4c12ce7c6aed3f26be99d34a3ad441af46beeeb2c2279be186bb62b3678`.
Verifier source-unchanged gate passed; independent post-run snapshot verification
and workspace comparison recorded **zero source drift**.

Executed from that frozen snapshot:

```sh
timeout --signal=TERM --kill-after=150s 1800s \
  python3 deploy/verify.py --live --agents-idle --work-root /tmp/opencode \
  --reuse-build-record /tmp/opencode/adr022-build-corrected.md \
  --backend-image sha256:feecb2f3ad41554364df2ef745d0ace4de8be83cf96f1e90bc1417990a62eeba \
  --frontend-image sha256:712b31ddc68c7757eb6eda1a54bbd9c83feab6bc8720ed675e36d331a1c116a6 \
  --neo4j-image sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7
```

Run `/tmp/opencode/nanfo-deploy-verify-ha7l2qmw` passed the complete existing core
campaign again: fresh0024/grants, login/six workers, authenticated CAS upload/list/
download and registration, two spatial revisions, simulation/reports, outage/
restart recovery, encrypted10-volume+1-bind backup, distinct fresh10-volume restore,
exact schema/images without target migration, token invalidation, report/workflow
equality and asset/history recovery. Restored asset UUID
`679f7d51-1621-44a9-acb7-4bca91b39cc8`,61 bytes, body SHA256
`58cbc1cdab6449017cc429d7b6b068b43b21050c7261d9577ac017d03cf80b0b`.
Authenticated backup registration/body receipt SHA256:
`9152535fdd112ee5d751a54b94b5ef1b6270f1333b9ecaae9cdca2a8e845e9bf`.

New durable credential-free evidence (previous directory untouched):
[`DeploymentEvidence-20260920-corrected/`](DeploymentEvidence-20260920-corrected/).
Archive SHA256:
`5a14eff3e158749bd1ce51b9e22ab1646dff559a9254f020604034ef553ee590`.
Release manifest, exact build/image record, full reviewed matrix, status projection,
asset checkpoint, source hashes/drift and checksums are retained and verified.
No secrets, keys, private logs or backup payloads were exported.

Tests: **174 deployment tests passed**, **42 focused asset storage/service/endpoint
tests passed**. Actual campaign passed first try. Cleanup removed22 owned containers,
20 volumes,4 networks; subsequent inspection found no verifier resources and shared
services retained their original states. No commits. Four blocked cases remain
unrequested lab binding/congestion, model diagnosis and measured telemetry survival;
CLI exit1 is expected core-only Step15 semantics, not a failed core case.

## ADR022 final0024 acceptance — 2026-09-20

**CORE PASSED:26 passed,0 failed,4 blocked; `core_passed=true`, `failure=null`.**
Final run `/tmp/opencode/nanfo-deploy-verify-nyqt17jk/evidence/result.json` passed
on its first0024 campaign attempt. This supersedes earlier0021 acceptance without
rewriting its historical evidence. UTC records are2026-09-19T21:38Z onward,
corresponding to2026-09-20 local date; original timestamps are retained.

### Actual asset/history recovery and full-stack results

- Fresh initialization migrated through0022/0023/**0024** using parent-owned
  `runtime_health.SCHEMA_HEAD`. Runtime DML assertions passed for spatial history,
  campus assets, telemetry pins/coverage, previous Network tables and identity
  sequence. History immutability triggers remain enforced.
- New private `network_assets` volume:0700,UID10001, API read/write; separate
  `maintenance` profile mounts assets and reports read-only. Initialization helper
  provisions the empty volume. No static/public asset serving or SNMP package added.
- Real authenticated POST uploaded a61-byte glTF fixture into `local_cas`, then
  authenticated compatibility GET and binary download verified exact bytes,
  SHA256, digest ETag, no-store headers and persisted registration.
- Real spatial PUTs created revisions1 and2 with distinct positions. Current scene,
  history listing/receipts and revision1 body were fetched and retained for exact
  comparison after recovery; no fabricated history or decrementing revision.
- Coordinated cold backup encrypted **10 named volumes +1 bind directory**,
  including the asset object volume and PostgreSQL. Every source writer stopped.
  Owner storage reads verified all retained asset bodies, including soft-deleted
  identities if present, and bound registration/identity/body receipts.
- Authenticated backup asset checkpoint:1 verified asset,61 bytes,
  receipt SHA256 `74073437fb15ebef119455533d9243088007ffbd220ed01413e2edce891f59c8`.
- Distinct fresh target restored **10 different volumes**. Schema0024, exact image
  IDs/OS/architecture retained; **no target migration**. Asset checkpoint compared
  equal, then authenticated API download/list verified the same asset UUID, bytes,
  registration and metadata. Current scene and both history receipts/body matched.
- Asset UUID `5bd89912-0093-4df8-865f-6a7bb12324bd`, body SHA256
  `58cbc1cdab6449017cc429d7b6b068b43b21050c7261d9577ac017d03cf80b0b`;
  registration SHA256 `ef4d34802ad008d88b647948325dc435152c57bd2511bc79d8ae4bffd8786ab5`.
- Admin login, latest gateway assets, six-worker readiness, configured simulation,
  CSV/PDF rendering, database-stop readiness, stale-heartbeat recovery, API/all-six
  worker restart, unexpired-token rejection/new login, three identical restored
  report downloads and restored workflows all passed again.
- Source fingerprint unchanged; cleanup passed:22 containers,20 volumes,4 networks
  removed. Follow-up Docker inspection showed no verifier-owned resources and
  unchanged pre-existing running stores/stopped packaging workers.

Four blocked cases remain explicitly optional/unrequested: lab binding, physical
lab congestion, frozen model diagnosis, and measured-telemetry survival (no measured
rows were created, so empty-to-empty is not credited). Thus CLI exit1 is expected
for core-only verification; `all_green=false` and `step15_complete=false` are retained.

### Exact accepted images and executed command

| Role | Exact local image ID |
| --- | --- |
| Backend/API/six workers/init/maintenance | `sha256:0876615dee3c7faf11c50ca42fdb27b75242f099913983d4d0747b83df212221` |
| Latest frontend | `sha256:712b31ddc68c7757eb6eda1a54bbd9c83feab6bc8720ed675e36d331a1c116a6` |
| Neo4j same-UID shutdown wrapper | `sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7` |

PostgreSQL/Redis remain the exact pinned17.6/7.4.5 digests recorded below.
Backend Poetry/main-install/pip-check layers and frontend `npm ci` layer reused
unchanged caches. New backend runtime sources/migrations and latest frontend
lint/typecheck/production build ran in Docker. No reinstall, pull, shared mutation,
emulation lifecycle or model training was needed. Builds were individually bounded
to420s,2GiB and512 CPU shares; campaign used existing service resource caps.

Frozen final snapshot `/tmp/opencode/nanfo-adr021-core-source-pjh8ee_o`,860 files;
canonical source-map SHA256:
`a364b9836792bd5cb1b66550e4f42489eb8fbe28cd3e0deb815c2cc87e19348f`.
Frontend hashes independently matched its earlier build snapshot. Final source
bytes were rechecked after the campaign; **zero recorded source drift** at export.

Executed from the frozen final snapshot:

```sh
timeout --signal=TERM --kill-after=150s 1800s \
  python3 deploy/verify.py --live --agents-idle --work-root /tmp/opencode \
  --reuse-build-record /tmp/opencode/adr022-build-final.md \
  --backend-image sha256:0876615dee3c7faf11c50ca42fdb27b75242f099913983d4d0747b83df212221 \
  --frontend-image sha256:712b31ddc68c7757eb6eda1a54bbd9c83feab6bc8720ed675e36d331a1c116a6 \
  --neo4j-image sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7
```

### Durable evidence and checks

[`DeploymentEvidence-20260920/`](DeploymentEvidence-20260920/) contains the full
reviewed credential-free result, strict status projection, authenticated asset
checkpoint projection, exact build/image record, source map, release manifest,
drift report, archive and checksums. Backup keys/secrets/private logs/encrypted
data archives remain outside shared evidence. Snapshot source bytes remain temporary.

Evidence archive SHA256:
`dffe851356545e594084f8a773f87207e00d13706b4c0acd37d0ce43435d1aef`.
Manifest and archive checks passed. The conservative source inventory is explicitly
not a fabricated per-image COPY inventory. Earlier0021 archives/results remain intact.

Deployment suite **174 passed**, scoped Ruff/formatting/whitespace passed. New
tests cover read-only maintenance mounts, retained/deleted asset body validation,
registration-bound checkpoint hashes, corruption/caps, download/registration
tampering, exact0024 expectations and grants. Initial test correctly failed while
parent runtime was still0021; it passed after the actual parent update, no mocking
away the integration mismatch. Latest observed free space: Docker `/home`
274,809,806,848 bytes; staging4,727,197,696 bytes.

## ADR022 source integration notes — 2026-09-20

Deployment now targets0024, importing the parent-owned runtime `SCHEMA_HEAD` in
fresh initialization. New `network_assets` named volume is provisioned0700/UID10001,
mounted read/write only by API and read-only in a dedicated maintenance profile.
The whole volume is covered by existing configuration-derived cold backup/restore.
`asset_checkpoint.py` verifies every retained asset (including soft-deleted rows)
through the owning storage reader and hashes registration/identity/body receipts;
restore compares this checkpoint. Historical manifests without this checkpoint
remain interpretable by matching historical images/composition.

Verifier adds authenticated CAS upload/download, two scene replacements and history
body reads, then exact asset registration/bytes and scene/history equality after
fresh restore. No SNMP package/image change. Fresh runtime grants assert all four
ADR022 tables in addition to prior Network tables and outbox identity sequence.
Final source-matched campaign above observed parent runtime head0024 and model
imports stable and verified the actual asset/history restore contract.

## Recovery closure — genuine core acceptance passed, 2026-09-19

**24 passed, 0 failed, 4 blocked; `core_passed=true`.** This supersedes the partial
status below while retaining every earlier failure. Final run:
`/tmp/opencode/nanfo-deploy-verify-gx9u923y/evidence/result.json`.
Core-only CLI exits1 by its existing Step15 contract; `failure=null`, campaign and
cleanup passed. Four explicitly blocked cases are lab binding, lab congestion,
optional model diagnosis and measured-telemetry survival. No lab/model execution
or physical-safety claim was added to obtain core acceptance.

### Diagnosed and fixed, without weakening acceptance

1. **Neo4j cold shutdown:** a separate fresh three-store probe reproduced
   PostgreSQL0/Redis0/**Neo4j1**, with no OOM. Root-owned tini lacked permission
   to forward signals after its child dropped to neo4j UID with CAP_KILL absent.
   `Dockerfile.neo4j` now enters the wrapper directly; `neo4j-entrypoint.sh` executes
   **`su-exec neo4j:neo4j tini -g -- ...`**, making forwarder/Java the same UID.
   A new probe observed all three stores exit0. Kept dropped capabilities and
   strict clean-shutdown requirement; no nonzero exit was accepted as clean.
2. **Verifier encrypted header:** it compared an11-byte read with the10-byte
   `NANFO-GCM-1\0` magic. Read length now comes from the actual magic. The backup
   itself had completed correctly; the previous false verifier failure is retained.
3. **Restore tar descriptor:** buffered validation's `seek(0)` did not reliably
   rewind the kernel offset after read-ahead when the descriptor became subprocess
   stdin. Restore now uses unbuffered anonymous plaintext files. A real subprocess
   regression validates and then feeds tar from that descriptor; archive validation
   still completes for every input before creating any target volume.
4. **Restore startup race:** Neo4j HTTP health can precede successful authenticated
   query readiness. The restored checkpoint now has a bounded dependency wait,
   accepting only exact typed `safe:false` dependency-unavailable responses for
   retry. Arbitrary failed subprocesses, unsafe domain checkpoints and graph/report
   mismatches still fail closed. A failed subprocess reporting `safe:true` is refused.

Added code-owned backup/restore stage identifiers and exception-type diagnostics.
Verifier exposes only allowlisted stage/type pairs or constant reasons; raw driver
stderr/stdout is kept in bounded0600 private diagnostic files outside evidence/
backup manifests. Private logs were inspected locally and are excluded from all
durable exports. New stages distinguish inventory, quiescence, store shutdown,
archive/extraction, restored readiness and session invalidation.

### Actual final acceptance evidence

- Fresh0021 initialization, Admin login, six-worker readiness, gateway assets,
  configured simulation, real CSV/PDF reports, negative readiness/heartbeat and
  API/all-six-worker restart recovery passed again.
- Cold encrypted backup: **9 named volumes +1 external bind directory**, every
  source writer stopped, authenticated manifest/payload verification passed.
- Fresh target: **9 different volumes**, same image IDs/OS/architecture, schema0021
  retained **without target migration**. Neo4j checkpoint:18 nodes,9 event revisions,
  same revision hash; no graph data substituted or waived.
- Unexpired old access/refresh tokens rejected; new login accepted.
- **Three restored report downloads** (CSV/PDF/restart report) matched original
  bytes/receipts. Simulation checkpoint and restart workflow survived identically.
- Source fingerprint unchanged; campaign completed. Cleanup removed22 owned
  containers,18 volumes and4 networks. Subsequent inspection found no verifier
  resources. Existing shared stores and old stopped packaging workers retained
  their states. Diagnostic restore probes also cleaned only their own targets.

### Final images and reproducibility

| Role | Exact accepted local ID |
| --- | --- |
| Backend/API/workers/helpers | `sha256:c2c35eeda19ca7448f865cf9e2f48069b2533aee0eeaf998cff7d81ad648820d` |
| Frontend | `sha256:0b276d12f471b356fa62881f7eb8063a32f4558a6d7b47883216278bb52cb0f7` |
| Neo4j wrapper | `sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7` |

PostgreSQL/Redis retain the exact pinned IDs listed below. Only changed deploy
runtime COPY/metadata and Neo4j wrapper layers were rebuilt; Poetry installation,
application source, frontend and pinned bases reused their observed unchanged
layers. No dependency reinstall, pull, training or broad rebuild was needed for
recovery. An initial workspace-context build refused an unreadable old emulation
path before sending context; the build was rerun from the frozen snapshot.

Snapshot `/tmp/opencode/nanfo-adr021-core-source-skgtb461`,813 files, canonical map
SHA256 `28bb2a55da6c642971136c2f071c4023e0bd41e140dcec2f2061a4457a20493c`.
All source hashes verified after acceptance. Only verifier test additions differ
from that snapshot in the workspace; production source is unchanged at handoff.

Executed from that snapshot:

```sh
timeout --signal=TERM --kill-after=150s 1800s \
  python3 deploy/verify.py --live --agents-idle --work-root /tmp/opencode \
  --reuse-build-record /tmp/opencode/recovery-build-final.md \
  --backend-image sha256:c2c35eeda19ca7448f865cf9e2f48069b2533aee0eeaf998cff7d81ad648820d \
  --frontend-image sha256:0b276d12f471b356fa62881f7eb8063a32f4558a6d7b47883216278bb52cb0f7 \
  --neo4j-image sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7
```

Durable credential-free evidence:
[`DeploymentRecovery-20260919/`](DeploymentRecovery-20260919/).
Contains final matrix/projection, both intermediate campaign failures, exact
locked-build record, source map, conservative observed-build manifest, release
manifest, source-drift record and checksums. Source snapshot bytes remain temporary;
private logs, keys, secrets and encrypted backup payloads are not shared evidence.

Evidence archive SHA256:
`156dd4fccadb1644457dfb50e4940c62ac755be7328d4afbe585ed30442aace4`.
Manifest verification and archive verification passed. Existing historical archive
authentication/schema matching remain unchanged; these are operational fixes, not
a backup-format migration.

Final deployment unit/regression gate: **171 passed** (existing dependency
deprecations only); scoped Ruff/formatting and whitespace checks passed. Remaining
Step15 blockers are strictly the unrequested physical lab/model/measured-telemetry
capabilities, not core backup/restore. Optional collector/net-snmp work remains
separate as documented below.

## Authorized core Docker acceptance — 2026-09-19

**PARTIAL: source-matched core builds and application acceptance through restart
passed; coordinated encrypted backup failed and fresh restore remains blocked.**
Final matrix: **16 passed, 2 failed, 10 blocked**, exit1. This is a genuine core
failure, not merely the expected Step15 exit caused by omitted physical lab/model.

Latest runtime/main were read before execution: schema0021, Network `outbox`
heartbeat and six worker roles, spatial router included. Each campaign used a
new read-only-file source snapshot with an independent local Git index so the
existing fingerprint/quiet gates inspected that frozen input, not other agents'
active workspace. `--agents-idle` applied to the snapshot build inputs, not a
claim that other workspace agents had stopped. No emulation lab or model/training
command was invoked; the concurrent Redis acceptance project was not targeted.

Executed documented core-only command, in each snapshot root:

```sh
timeout --signal=TERM --kill-after=150s 1800s \
  python3 deploy/verify.py --live --agents-idle --work-root /tmp/opencode
```

Docker29.8.0/Compose5.5.1 used the legacy builder (Buildx absent). Required pinned
base/store pulls succeeded; dependency builds stayed in Docker. Direct frontend
diagnostic builds used420s/180s timeouts,2GiB memory and512 CPU shares. Compose
service runtime memory/CPU/PID limits applied to the disposable stack. No old
ADR020 application ID was substituted as current source evidence.

### Durable evidence and attempts

Credential-free evidence is retained adjacent to this document in
[`DeploymentEvidence-20260919/`](DeploymentEvidence-20260919/): reviewed complete
verifier matrices, stricter status projections, source hash inventories,
observed image/build record, release manifest, bounded evidence archive and
`checksums.json`. No run secrets, encryption keys, backup payloads, environment
dumps or arbitrary container logs were copied.

| Attempt | Original run suffix | Result | Explanation |
| --- | --- | --- | --- |
| 1 | `udwbms27` | 3pass/2fail/23blocked | Snapshot helper mistakenly excluded legitimate `frontend/src/shared/state`; fixed helper, retained failure |
| 2 | `oilgq65i` | 16pass/2fail/10blocked | Core through restart passed; backup failed. Read-only contract inspection proved default Compose config omitted persisted `init_secrets` |
| 3 | `e0p8wb8e` | 3pass/2fail/23blocked | Compose build exited1 with withheld output. Bounded direct frontend build then succeeded from identical snapshot/cache; exact initial transient reason unavailable |
| 4 | `fnkn0pd4` | 16pass/2fail/10blocked | Complete profile inventory fixed; backup still exited1 with withheld output; stopped retries |

Final snapshot: `/tmp/opencode/nanfo-adr021-core-source-jlfa7rez`,813 files.
Canonical source-map SHA256:
`59e4975a07ea1ec7814035314ee5260db97f51a80b4422902eb322649486001e`.
Verifier runtime fingerprint:
`48e4a8af01b03ed8f1df1df31532a107539436dca28f59497104d14f81a1ccea`.
Every captured source hash was rechecked after the campaign and before export.
The verifier's own final `source_unchanged` case was blocked by its earlier failure;
this separate post-run check must not be relabeled as that case passing.

Archive SHA256:
`1ea7835165b6237a6a15f51e4d4aac2b7fd2dbcc6397944758b731b12f4f32a7`.
Archive and manifest verification passed. `observed-build.json` binds the complete
conservative snapshot to observed image IDs; it explicitly is not a per-image
COPY inventory or a fabricated `manage.py` build record. The original full build
result is also retained. Snapshot source bytes remain temporary; hashes are durable.

Post-export workspace drift is explicitly recorded: only `deploy/release_manifest.py`
and its test changed from the final snapshot, to support the existing verifier's
12-hex Docker network ledger IDs (containers still require64 hex). Thus the final
image is source-matched to the recorded snapshot, not asserted to equal all future
workspace edits. Source-map verification does not detect subsequently added files.

### Observed final exact image IDs — Linux/amd64

| Role | Observed ID |
| --- | --- |
| Backend/API/all six workers/init helpers | `sha256:c45ea8b74b60a2e24cbe745a5c4a1a0d8a6bf60fc9644cf25fd92f8f3dbd6f9e` |
| Frontend gateway | `sha256:0b276d12f471b356fa62881f7eb8063a32f4558a6d7b47883216278bb52cb0f7` |
| Neo4j wrapper | `sha256:528085775326695ef4475242b924336b50da47ee23b229c6ec68ccdf166fdc27` |
| PostgreSQL17.6 | `sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3` |
| Redis7.4.5 | `sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb` |

### Acceptance scope and remaining blocker

Passed: locked container builds, snapshot build parity, nine independently empty
volumes, migration0021 including initializer privilege assertions, authenticated
Admin bootstrap, gateway assets, six-worker readiness, configured45% loss simulation,
real CSV/PDF bytes, database-stop negative readiness/recovery, stale-worker heartbeat
recovery, API plus all six worker restart with pending report/simulation recovery.

Failed: `coordinated_encrypted_backup`, then `campaign`. The exact retained safe
diagnostic is **`Command failed (/usr/bin/python3, exit 1); output withheld`**.
Backup directory is empty; no completed archive exists. Current exact diagnostic
allowlist did not match the underlying stderr; do not infer a successful checkpoint
or encryption step. The initial profile omission is fixed but was not sufficient.
Next investigation should add code-owned stage/error codes to the backup CLI or
locally inspect a controlled invocation, preserving secret suppression, then run
one separately scheduled fresh recovery acceptance. No further automatic retries.

Blocked: distinct fresh restore, restored schema/image match, old-token rejection,
report/workflow/telemetry survival and source-unchanged case. Physical lab/model
were deliberately unrequested; frozen model absence remains independent.

Cleanup passed: final run removed11 containers,9 volumes and2 networks; inspection
found no remaining verifier-named containers/volumes/networks. Four known legacy
builder intermediate containers from these attempts were removed by their exact
inspected IDs; no prune or shared-resource removal. All pre-existing running stores
and stopped packaging workers retained their states. Latest disk observation:
Docker `/home`275,781,046,272 bytes free; staging7,751,598,080 bytes free.

### Fixes and checks from live investigation

- `backup_restore.Deployment` and verifier `Stack.compose("config", ...)` now inspect
  `--profile '*'` to include initialization-only persisted volumes. Profiles are
  not enabled on lifecycle commands. Current backup format/signatures/schema
  comparison remain unchanged; older archives still need matching composition.
- Verifier permits only exact code-owned operator refusal strings across its
  subprocess boundary; arbitrary JSON reasons remain suppressed.
- Evidence export accepts12/64-hex **network** IDs from existing verifier ledgers.
- Full deployment suite **165 passed**; scoped Ruff and formatting pass.

Optional net-snmp collector image/profile is **not delivered** in this bounded
core acceptance slot. Core images received no net-snmp package or SNMP credentials.
A separate collector profile needs an independently resolved/pinned base and apt
package source/version, protected operator config/credential mounts, explicit
read-only target scope and its own acceptance. No guessed pin or inherited
core-image SNMP support is claimed.

## Deployment integration update — 2026-09-19

Parent-authorized source integration is complete; **live execution remains deferred**.
This update supersedes the initial schema/composition blockers recorded below.

- `deploy/initialize.py` now migrates fresh stores explicitly to **0021** before
  issuing runtime DML grants on all tables and USAGE/SELECT on all sequences.
  Existing owner default privileges cover future table/sequence creation. Added
  post-grant assertions for `network_outbox`, `network_spatial_scenes` and the
  identity sequence discovered with `pg_get_serial_sequence('network_outbox',
  'sequence')`; absent grants fail before bootstrap. Existing migration-table/audit
  restrictions and refusal of nonempty databases remain enforced.
- `compose.yaml` adds `network-outbox-worker`, command
  `python -m scripts.run_network_outbox_worker`, and the existing health tool with
  `--worker network`. It inherits private networking, runtime secrets, bounded
  resources, read-only filesystem and work heartbeat settings.
- `manage.SERVICES` and `verify.WORKERS` include the sixth worker, covering
  start/stop, readiness, outage recovery, restart identity checks and lab transitions.
  Backup already derives writers from **all configured non-store services**;
  regression coverage verifies the new publisher stops after admission quiescence
  and before store shutdown. No duplicate backup worker list was introduced.
- Current verifier migration case, exact installed-schema check and restore result
  require0021. Maintenance returns the parent-owned runtime `SCHEMA_HEAD` after
  dependency validation and includes `network_outbox` in read-only diagnostics.
- Fresh/current restore markers record0021. Current lifecycle refuses old or
  schema-less markers and historical restore adoption rather than silently
  starting the new publisher against old tables. This is not an upgrade procedure.
- **Archive compatibility:** `backup_restore.py` authentication, archive format,
  matching-image/matching-schema restore validation remain version-neutral.
  Authenticated0019 archives remain valid; recovering them uses their matching
  images/composition/operator version, not current0021 lifecycle adoption. Tests
  cover0019 and0021 archive validation and refusal to adopt0019 here. Release
  evidence export explicitly retains support for historical `migration_0019`
  matrices as well as current `migration_0021`.

Additional owned integration files: `deploy/initialize.py`, `manage.py`,
`maintenance.py`, `verify.py`, `compose.yaml`, `test_lifecycle.py`,
`tests/test_initialize.py`, `tests/test_operations.py`, `tests/test_verify.py`;
small archive-compatibility update in release tool/test. Historical records and
prior validation documentation were not rewritten during integration.

Required parent actions before acceptance:

1. Set runtime `SCHEMA_HEAD="0021"` and `WORKER_LOOPS["network"]=("outbox",)`;
   these are explicitly parent-owned. Complete application/router/migration
   integration and confirm a single Alembic head0021.
2. Perform separately authorized, serialized source-matched image builds, retain
   full source/build manifests on persistent storage, and provision the exact
   missing PostgreSQL/Redis images identified below. No SNMP package installation
   or measured-SNMP image acceptance is included in this deployment scope.
3. Validate actual fresh runtime-role insert/update of both Network tables and
   identity allocation, six-worker health and interrupted outbox publication,
  0021 backup/restore without target migration, existing report/restart/lab gates.
   Unit tests verify SQL ordering/refusal but do not prove live PostgreSQL grants.
4. Preserve no-pull preflight and isolated lifecycle boundaries described below;
   only parent authorizes image/container/lab execution. Reverify release inputs
   and durably export every final attempt, including blocked/failed cases.

Integration checks: backend Poetry interpreter `python -m pytest deploy -q`:
**162 passed** (dependency deprecation warnings only). Scoped Ruff, formatting
and whitespace checks passed. One newly added restart fixture initially omitted
`simulation_id`; corrected its response to the existing verifier contract and
reran the complete deployment suite. No Docker commands or live stores were used
by this integration/testing stage.

## Status — 2026-09-19

Offline release evidence implementation is delivered. **Integrated deployment
acceptance remains blocked and unexecuted by this workstream.** Inspection used
Docker version/info/image-list/image-inspect/container-list/volume-list only, plus
the existing verifier's read-only `disk_capacity()` function. No builds, pulls,
container lifecycle, migrations, lab execution or pruning occurred.

Owned files:

- `deploy/release_manifest.py`
- `deploy/tests/test_release_manifest.py`
- `docs/project/CompletionProgram/Deployment.md`
- New dated current section in `deploy/VALIDATION.md`

## Implementation contract

The standard-library CLI provides `create`, `verify`, `export`, `verify-archive`.
It consumes `manage.py`'s existing per-build `source_sha256` records rather than
duplicating its build-context selection, the verifier, or encrypted backup logic.

- `create` hashes **exact bytes**, including build-record whitespace, and verifies
  each recorded source hash against the supplied source root. Records must have
  exact `sha256:` image IDs and collectively cover `backend/poetry.lock`,
  `frontend/package-lock.json`, and `ai-engine/uv.lock`. Contradictory records,
  missing locks, missing inputs and source drift fail closed. Optional repeated
  `--source` adds host verifier/composition inputs outside image build records.
- Canonical `nanfo-release-v1` JSON contains source paths, byte lengths, SHA256s,
  build-record byte lengths/SHA256s, exact image IDs and each record's source list.
  It contains no source or build-record payloads, host paths, timestamps or Git
  dirty-state claims. `verify` rereads both roots and rebuilds the complete manifest.
- Export allowlist is **only** `evidence/result.json` and
  `evidence/resources-<32 lowercase hex>.json`. No recursive copying or arbitrary
  include option. Secrets, keys, backup/restore, binding, model directories, env
  files, logs and other diagnostic JSON are excluded.
- Exported result is a typed projection: code-owned verifier case names and enum
  statuses, independently counted statuses and boolean `reported_flags` only.
  Failure/detail strings, URLs, arbitrary fields and host paths never enter it.
  Failed/blocked/pending cases remain visible; raw failure explanations are omitted.
  Resource ledgers accept only scoped verifier project names, hex resource IDs and
  project-prefixed volume names. Original evidence byte lengths/hashes remain in
  the catalog, so an independently retained original can be compared later.
- One deterministic uncompressed USTAR contains `release.json`, `checksums.json`
  and projected evidence. Sorted members, fixed permissions/owners/mtime and
  canonical JSON make identical inputs byte-reproducible. File/content checksums
  are internal; CLI prints the **whole archive SHA256** for independent retention.
  `verify-archive` requires that trusted digest and never extracts files.
- Limits: 8 MiB/input or member; 64 MiB aggregate evidence input and final archive;
  4,096 archive entries (directory scan capped at 4,094), 20,000 source files,
  64 build records and 128 verifier cases. No compressed archives. Entire bounded
  bundle is held in memory; these limits are not a large-log archival interface.
- Descriptor-relative opens reject symlink ancestors/files, hardlinks, FIFOs,
  traversal and protected path names. Archive validation additionally rejects
  links/devices/duplicates/sparse/PAX/noncanonical metadata/trailing bytes.
- Output parent must already exist, be operator-owned and mode0700. Output is
  mode0600, file-fsynced and atomically published with no overwrite via a same-
  directory hardlink; temporary name removal and parent fsync complete publication.
  Export must be outside its temporary run directory. Select a persistent local
  filesystem, not `/tmp`, and retain the printed digest in a separate trusted log.

### Evidence limits

Hashes establish integrity, not build authenticity, image reproducibility across
toolchains, physical safety or acceptance success. Build records remain trusted
producer inputs: this tool does not independently enumerate a Docker context or
inspect installed image source. Supply all per-build records, not a summary with
partial `source_sha256` coverage. Exact build/lock coverage is mandatory even when
optional AI inference is unavailable; the core backend build already stages the
AI lock. An AI image is not required merely to hash that lock.

An exported manifest/result pair is an explicit operator association, **not proof
that that run used those images/inputs**. Parent integration must compare the
verifier's build/input evidence and serialize source changes before pairing them.
Preserve the full original failure evidence privately when explanations are needed;
the durable shareable bundle intentionally retains statuses and original hashes,
not unrestricted diagnostic prose. Verification of the bundle alone does not
recheck source roots, Docker availability or any live case.

### Parent release/evidence commands

After source integration and separately authorized builds, provision an existing
private persistent directory and set `RELEASE_DIR`, `BUILD_ROOT`, `RUN_DIR` to the
approved paths. The following assumes the existing `manage.py` output filenames;
repeat `--build-record` for any additional build variant used in acceptance.

```sh
python3 deploy/release_manifest.py create \
  --root "$PWD" --build-root "$BUILD_ROOT" \
  --build-record build-backend-adr021.json \
  --build-record build-frontend-adr021.json \
  --build-record build-neo4j-5.26.12.json \
  --build-record build-lab-operator-paths-adr020.json \
  --source deploy/verify.py --source deploy/release_manifest.py \
  --source deploy/compose.yaml --source deploy/compose.lab.yaml \
  --output "$RELEASE_DIR/release.json"

python3 deploy/release_manifest.py verify \
  --root "$PWD" --build-root "$BUILD_ROOT" \
  --manifest "$RELEASE_DIR/release.json"

# After the serialized verifier finishes, including its cleanup/result write:
python3 deploy/release_manifest.py export \
  --manifest "$RELEASE_DIR/release.json" --run-dir "$RUN_DIR" \
  --output "$RELEASE_DIR/evidence.tar"

python3 deploy/release_manifest.py verify-archive \
  --archive "$RELEASE_DIR/evidence.tar" --sha256 "$TRUSTED_ARCHIVE_SHA256"
```

These are integration templates, not executed release claims. Actual record
filenames follow the selected build tags; use their exact basenames. Re-run
`verify` after acceptance before publishing the pair. Export failed runs as well;
use a distinct durable output path for each attempt, never overwrite prior evidence.

## Exact read-only environment observations

Observed 2026-09-19; recheck before the parent acquires the serialized integration slot.

| Prerequisite | Observation |
| --- | --- |
| Python | 3.14.7; verifier requires 3.12+ |
| Host cryptography | 50.0.1 available; existing backup dependency |
| Docker client/server | 29.8.0, API1.56, default context, Linux/amd64 |
| Compose | 5.5.1 (v2-or-newer interface present) |
| Docker root/driver | `/home/.system-data/docker`, overlayfs |
| Existing verifier disk check | `/home`: **276,187,082,752 bytes free**; `/tmp/opencode`: **7,969,120,256 bytes free**; each exceeds its 1,073,741,824-byte floor |
| Host resources | 12 CPUs; 16,074,448,896 bytes RAM; initial `free -b`: 7,322,152,960 bytes available RAM; swap unused |
| Shared resources | Three healthy development stores running; two unrelated database containers running; three old packaging workers exited; nine packaging named volumes still present |
| Verifier/lab resources | No verifier or lab container visible in the inspection |
| Full historical per-build records | No `/tmp/opencode/nanfo-deploy-step15-rebuild/build-*.json` found |
| Optional model input | `ai-engine/artifacts/adr014-001/train-06/checkpoint.ptz` absent |

All five current ADR020 rebuild IDs were independently inspected successfully as
`linux/amd64` (availability only, not installed-source parity):

| Image | Exact available local ID |
| --- | --- |
| Core backend | `sha256:55a65205a6ba81c1ce489e9fab1abfba1dd9dd57c24ee2676de76ee5deaddec7` |
| Frontend | `sha256:7ec667ab18129019d5587610b62ad4b896cb395208ffef2a53003ec1df3931c2` |
| Neo4j wrapper | `sha256:feda142d85d1cae43b6a3835b9c9820f4cce2249a288b77b1597e2827e87155a` |
| Operator lab | `sha256:aafbad31e766488bbfd0709a5b12798677505c8bae3cc7b957405b0b16ecee03` |
| Optional AI backend | `sha256:68eb136293a728c83ee2126904f7bc7c1f86e8b483ab229eb649925bfc14460d` |

**Both Compose-pinned stores are missing**, confirmed by exact `docker image inspect`:

- `postgres:17.6-bookworm@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3`
- `redis:7.4.5-bookworm@sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb`

Available development `postgres:16-alpine`/`redis:7-alpine` are different images.
Their running stores must not be substituted as disposable acceptance targets.
The older four IDs from `core-build-adr020-final.json`/the September14 resume remain
absent from the image inventory. Current rebuilt images are not aliases of them.

## Integration blockers and recommended verifier command

1. **Migrations:** ADR021 introduces0020 after0019 and0021 after0020. Parent must
   integrate the single intended head and update `deploy/initialize.py` (currently
   explicitly upgrades0019), `backend/app/core/runtime_health.py::SCHEMA_HEAD`
   (0019), `deploy/verify.py::CASES`, `installed_schema()`, initialization case and
   restore-schema evidence (all0019), with matching tests. Align worker composition
   and readiness with the owning outbox workstream. Do not simply accept any head
   or relabel an0019 run as0021. Restore must retain the exact source revision
   without target migrations. Historical acceptance scripts also contain0019;
   review any of them selected for the ADR021 campaign.
2. **Source-matched images/records:** available September14 images predate the
   September18 frontend and ADR021 sources. The current summary record is not a
   full release manifest and its referenced per-build records are missing. Parent
   needs independently authorized source-matched builds and full records retained
   on persistent storage. New backend/frontend pins and companion locked-build
   references must agree with `referenced_build()`; never reuse old IDs as current
   source proof. No full current-release manifest was fabricated during active edits.
3. **Pinned stores:** separately authorize provision of both exact missing store
   images before acceptance. Existing reuse mode avoids explicit image build calls,
   but Compose `up` has no universal `--pull never` enforcement and can fetch
   missing stores. Parent should fail preflight on every absent service image and
   enforce no-pull behavior before calling the campaign under a no-pull requirement.
4. **Serialization:** all contributing workstreams must finish, source manifest
   must verify, and parent must explicitly authorize live lifecycle. Even image
   parity in reuse mode invokes a short-lived helper container, so the verifier is
   not a read-only inspection command. Preserve current shared containers/volumes.
5. **Optional model:** do not request `--model` until frozen checkpoint/history/
   source/benchmark inputs and registry requirements are independently available.
   AI image availability alone does not prove inference or calibration.

After these blockers are resolved, recommended no-build reuse command:

```sh
python3 deploy/verify.py --live --agents-idle --lab \
  --work-root /tmp/opencode \
  --reuse-build-record "$INTEGRATED_LOCKED_BUILD_RECORD" \
  --backend-image "$INTEGRATED_BACKEND_SHA256" \
  --frontend-image "$INTEGRATED_FRONTEND_SHA256" \
  --neo4j-image sha256:feda142d85d1cae43b6a3835b9c9820f4cce2249a288b77b1597e2827e87155a \
  --lab-image "$INTEGRATED_LAB_SHA256"
```

Use the observed lab ID only if its exact inputs remain appropriate after parent
integration; the Neo4j ID likewise requires retained build provenance. The command
starts/stops disposable resources and executes the disconnected lab. **It was not
run here and is not authorized by this inspection.** There is no current verifier
flag that repairs its0019 assumptions. Core-only execution omitting `--lab` is not
Step15 completion and intentionally may exit nonzero.

## Checks performed

- `python3 -m unittest discover -s deploy/tests -v`: **70 passed** (24 new release
  tests and46 existing verifier tests; unittest discovery does not run pytest-style
  operations tests).
- Backend Poetry interpreter, `-m pytest deploy/tests/test_operations.py
  deploy/test_lifecycle.py -q`: **76 passed**, dependency deprecation warnings only.
  Initial system-Python attempt:72 passed/4 failed because ReportLab was absent;
  rerun with the existing backend environment resolved all four, no installs.
- Scoped Ruff check/format check, CLI help and `git diff --check`: passed.
- Meaningful tests cover exact-byte record/source/lock tampering, missing lock
  coverage, conflicting builds, input-order/mtime-independent determinism, durable
  verification after deleting the temporary run, canary exclusion, typed ledgers,
  content tampering with/without recomputed catalogs, traversal/links/FIFOs,
  duplicates, truncation/trailing data, bounds, no-clobber/fsync failure cleanup,
  private permissions, duplicate/nonfinite JSON and the complete CLI roundtrip.

All test evidence above is offline. Fresh deployment,0020/0021 upgrade/restore,
outbox interruption recovery, live lab, cold backup/restore and optional model
acceptance remain parent-owned, evidence-gated integration work.
