# ADR027 current0029 deployment/recovery handoff

Date: 2026-09-21. **Core0029 live deployment and cold encrypted backup/fresh restore
ACCEPTED: 28 passed, 0 failed, 5 optional blocked; `core_passed=true`.** This
supersedes the earlier build blocker recorded below. No whole-vision, Step15,
privileged-lab or scientific qualification completion is claimed.

## Current-source acceptance refresh — c8rorfzd (2026-09-21)

**New actual core campaign:28 passed,0 failed,5 optional blocked; core accepted.**
This refresh includes the development fakeredis Lua lock, protected-read race fixes
and current experimental seed/inventory tooling. Earlier acceptance and all failure
records below remain unchanged. No deployment runtime changes were needed for this
refresh. Regression gate: **253 deployment tests +37 subtests, zero skips**.

- Fresh stable source: `/tmp/opencode/review0029-source-ckohdgb8` (**1,129 files**).
- Actual supervised command there: `python3 deploy/verify.py --live --agents-idle`.
- Original result: `/tmp/opencode/nanfo-deploy-verify-c8rorfzd/evidence/result.json`.
- Exact runtime source aggregate, both frozen and worktree at acceptance comparison:
  `f7105617ee9cad1ae51e2f223761885c9223ee22d4d586a08ff36a5f87e89d05`.
  **725 runtime paths, no additions/removals/byte drift.** Unlike the previous
  snapshot, the new freeze retains the empty `emulation/output/.gitkeep` placeholder.
- Full-freeze final comparison:1,128 unchanged, only `ai-engine/README.md` changed;
  that documentation is not copied into the core images.377 installed Python files
  matched frozen sources. manage.py/verify.py/backup_restore.py/Compose hashes remain
  exactly the values recorded in the previous accepted campaign below.
- Real Docker build reran Poetry2.4.1 lock check and **49 main package installs**
  after the dev-only lock change; pip check passed. New backend ID below. Frontend
  and Neo4j builds reused matching cache and truthfully retained their previous IDs.
  Pinned Python base is `782412e85d0f…`; no old backend image substitution.
- Installed read-only/network-none probe: FastAPI0.135.4, Starlette1.6.0,
  Pydantic2.13.4, cryptography50.0.0, Uvicorn0.32.1. The full frontend lock remains
  Router7.18.4/Vitest4.1.11/Vite6.4.3. AI lock is recorded only; no AI build/inference.

### Exact refreshed identities

| Input / image | SHA256 (image rows include Docker prefix) |
| --- | --- |
| Backend API / six workers / maintenance | `sha256:a2bf67af00b76980beec822f9c7f1fcb0e6d4ef2e1e6461b169b9b3ff3397b39` |
| Frontend gateway | `sha256:2e6f019d5807e7a4f97cd2d82d9a62c4349a68e5c2b2ed0493a8eb206119657d` |
| Neo4j | `sha256:1005d99b218a5a1eac3baf07c080e1d6d6a345af736785d6fbe307e2b0825185` |
| PostgreSQL | `sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3` |
| Redis | `sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb` |
| Backend poetry.lock | `f97fc09b91ebc80360feb2045b86b1a9471ad9d956e36f91c4648d6ee752bcae` |
| Backend pyproject.toml | `841bed1abe1b2e755394f8393146fe42ea296d9320560e877bea475f7af5cec6` |
| Frontend package-lock.json | `f4ee0f7d31f9e71af29f4d1d2812e2e53b59d74e5a2f5f55845414cbf8766acb` |
| AI uv.lock | `fb98d58d60838c69a0fab2a8c908b2023c7c351acdfc3c886be59ee6aa2560b1` |
| emulation/experimental_lab_contract.py | `e0c308e589baaf8eda78444d1ed22d3420f95d51343b488101e5f9e5caea74a9` |
| emulation/experimental_lab_receiver.py | `f58895c1bcb1c0a517dab64b1cc25ee8bc29353ae0778a15de476500e5628a73` |
| backend/scripts/verify_experimental_lab.py | `5c60fc2710942110580bcca92e0c5cd948677d902ca901b3ba9739c7353de19d` |
| Original verifier result | `aea363391faff9d85de241c7459ccc0dd79eb82b1bc5bec3bbc9cb7ad8cb742c` |
| Runtime source-manifest.json bytes | `ee231988815c4e6fae6f793577efe2f03f2c0160b7f62e9a290e08067d13698f` |
| Full freeze-manifest.json bytes | `150f15ce849681fc7986f2a486503394b255c22cbaf5f91009e112bb78010a9b` |
| Authenticated backup manifest | `6363dd09efaa29957c237182f0018412e7d2dec43ea21acfa884e5c789bed9a3` |

All five images are Linux/amd64. Core acceptance does not activate or qualify the
new experimental lab logic merely because its installed bytes match.

### Postacceptance host-tooling drift — explicit boundary

After `c8rorfzd` acceptance, the only source-code changes were the experimental
verifier's seed scanner and its test:

- `backend/scripts/verify_experimental_lab.py`: accepted hash
  `5c60fc2710942110580bcca92e0c5cd948677d902ca901b3ba9739c7353de19d`, now
  `9e46d086343fffa3c0cfe95fb6c636172d03be5bd175ff030fedb7b5ec0c87c0`.
- `backend/tests/unit/test_experimental_campaign.py`: current hash
  `200599ed6e52c5e13912d111257b44cda7a33de99497b4b4b73d82c1cae45937`.

The correction excludes a diagnostic count falsely treated as a seed reservation;
60 campaign tests passed. It changes host-operated experimental preparation tooling,
not serving API/six-worker core behavior or the accepted protected-read runtime.
The verifier script is copied into the backend image, so the accepted image still
contains its earlier bytes: **the entire current tree is not byte-identical to the
accepted source/image**. Documentation has also advanced. The725-path parity above
is the original point-in-time acceptance observation, not a new postcorrection
comparison. No replacement image or new campaign qualification is implied. Frozen
sources, manifests, results and backup bytes remain unchanged. See
[experimental recount](ReviewClosure-Experimental.md) for correction provenance.

### Repeated recovery and cleanup

Fresh0029 initialization/readiness, all six workers, generated bootstrap login,
frontend built-asset HTTP smoke, configured45% loss simulation, worker CSV/PDF,
negative PostgreSQL/worker readiness and queued-work API/worker restart all passed.
The delivered operator again performed **cold encrypted11-volume +1 binding-dir
backup**, authenticated it, restored into **11 distinct fresh volumes**, and retained
exact image/schema0029 without target migrations. Old unexpired access/refresh
tokens were rejected; new login, all three report bytes/receipts, spatial asset/
registration/history, workflow checkpoints and nonempty archive/pin/tombstone
restore all passed. No empty-to-empty measured-telemetry claim.

| Role | Exact owned project | Proxy subnet / nginx IP |
| --- | --- | --- |
| Source | `nanfo-deploy-verify-d6f19c7615c44d0e9229171d00e4dfee` | `10.42.191.0/24` / `10.42.191.254` |
| Restore | `nanfo-deploy-verify-a27324122dad479fa8c00bf7a89bc506` | `10.42.192.0/24` / `10.42.192.254` |

Cleanup removed **22 containers,22 volumes,6 networks**; independent exact-project
queries found zero remaining resources. Images/cache and private run archives remain.
No shared-service changes, lab profile, pruning, detached job or commit. Five cases
remain blocked by scope: distributed failover, lab binding, lab congestion, model
diagnosis and measured-telemetry survival. `all_green=false`, `step15_complete=false`
and documented core-only exit1 remain honest; no whole-vision completion claim.

### New safe compact evidence / preservation-owner handoff

New independent directory:
[`ReviewClosureEvidence/refresh-c8rorfzd/`](ReviewClosureEvidence/refresh-c8rorfzd/).
The existing `accepted/` bundle and original manifests were not changed. Exported
**8 pinned evidence files + selection/manifest/checksums =11 files /243,293 bytes**:
status-only projection, projection provenance, allowlisted acceptance detail,
runtime/full source manifests, final source comparison, proxy allocation and backup
manifest. Existing preservation exporter/verification and scanner passed with
**zero findings and zero fixture exemptions**. Raw result, logs, archive and key
are not exported into this compact bundle.

- New export manifest SHA256:
  `e4235f4eaadd09a0aa9f146c96cc36fc2d3dea832f05a388c3a5ab18b1677fa4`.
- New SHA256SUMS SHA256:
  `e48d632d8268fcbb699c0863fe484d4307ae0a4db849f42dd4b0531174cead2e`.
- Private new backup: `/tmp/opencode/nanfo-deploy-verify-c8rorfzd/backup/`;
  its32-byte key remains separately private in that run's `keys/backup.key`.
  Subsequent preservation verified new durable local copies under
  `ai-engine/artifacts/adr027-review-backup-c8rorfzd/`, separate
  `adr027-review-key-c8rorfzd/` and `adr027-review-originals-c8rorfzd/`.
  [Retention receipts](ReviewClosureEvidence/retention-c8rorfzd/) record exact-byte
  readback/authentication; the earlier `dr_i6gb8` copies remain intact. This is
  local private retention, not off-host escrow or a complete external-secret kit.
- Build logs remain in the new run directory; their exact hashes are in the
  published `deployment/source-comparison.json`. Prior run receipts remain retained.
- Verify without private keys:
  `python3 scripts/preserve_review_closure.py verify --destination docs/project/ReviewClosureEvidence/refresh-c8rorfzd`.

## Previous accepted campaign — after fixture relocation

Asset owner relocated the shared JSON fixture into
`frontend/src/test/fixtures/asset-download.json` and updated both readers. A new
stable freeze included that fix. The next actual build/migration attempt
`/tmp/opencode/nanfo-deploy-verify-ebgnv46i/evidence/result.json` recorded **7 passed,
2 failed, 24 blocked**: all images built,377 installed files matched and migration
reached0029, but gateway startup failed `Address already in use`. Docker attached
the API first and dynamically assigned `.2`, colliding with the selected nginx IP.

Fixed the owned allocator to select the **last usable /24 address, `.254`**, away
from the first-free addresses of the one/two serving APIs. The proxy boundary
contains only those APIs and nginx; no arbitrary additional tenants are admitted.
Added a regression; **253 deployment tests plus37 subtests pass, zero skips**.
Scoped Ruff and whitespace checks pass. Compose/Dockerfiles and shared services
were not modified by this owner. The failed live run's exact-owned cleanup passed;
its matrix and private Compose diagnostic remain retained.

### Accepted run and scope

- New stable source root: `/tmp/opencode/review0029-source-kamer_87`.
- Supervised command from that root: `python3 deploy/verify.py --live --agents-idle`.
  The source freeze is idle; the main repository may receive evidence/CI edits.
- Result: `/tmp/opencode/nanfo-deploy-verify-dr_i6gb8/evidence/result.json`.
- **33 matrix cases:28 passed,0 failed,5 blocked; core true; all_green and
  step15_complete false.** CLI exit1 is the documented core-only result because
  optional physical Step15 gates were not requested. There was no campaign error.
- Passed fresh11-volume emptiness,0029 initialization, bootstrap login, built-asset
  HTTP smoke, gateway readiness and all **six** work-coupled worker healthchecks.
- Actual PostgreSQL stop produced `/ready`503 while `/health` remained200; worker
  SIGSTOP produced stale-loop failure; both recovered. API/all six workers restarted
  and completed work accepted while workers were stopped.
- Configured simulation independently matched45% loss; CSV/PDF reports were actually
  worker-generated and downloaded. Synthetic archive bytes/pins/tombstones were
  retained and replay refused. These are not measured/physical-network evidence.
- Delivered operator CLI completed a **cold AES-256-GCM backup of11 volumes and1
  read-only binding directory**, after checkpoints and stopping all source owners.
  Verifier checked manifest HMAC, ciphertext hashes, permissions and archive
  authentication. Manifest SHA256:
  `387b4a533d6b48d7609e9293d2f10eb42ea32e5862d98edcbcb1cc7b6d371c90`.
- Distinct fresh restore recreated11 target volumes with identical image IDs,
  Linux/amd64 and schema0029; **no target migrations executed**. Neo4j18nodes/
  9device revisions and revision digest matched. Source stayed stopped.
- Unexpired source access and refresh tokens were rejected; a new login succeeded.
  **Three report downloads** (two CSV, one PDF) retained bytes and receipts. The
  61-byte glTF, registration, scene and two history revisions survived. Simulation
  checkpoint and queued-restart workflow matched. Nonempty578-byte telemetry
  archive restored with released pin, historical record and replay tombstone intact.
- Five explicitly blocked capabilities: distributed failover, lab binding, lab
  congestion, frozen-model diagnosis, and actual measured-telemetry survival.
  Privileged lab was not run. HTTP frontend smoke is not browser acceptance.

### Exact accepted images and frozen dependencies

All images below are Linux/amd64. Backend/frontend/Neo4j were actually built under
the new project using the delivered Dockerfiles; newly installed locked dependency
layers were reused where valid, not old application-image substitutions.

| Role | Exact local image ID |
| --- | --- |
| API / six workers / initialization / maintenance | `sha256:1926d2061253890120a1220c44a80b178e82c9a2789ccdbb9607a07515e6bdc3` |
| Frontend gateway | `sha256:2e6f019d5807e7a4f97cd2d82d9a62c4349a68e5c2b2ed0493a8eb206119657d` |
| Neo4j | `sha256:1005d99b218a5a1eac3baf07c080e1d6d6a345af736785d6fbe307e2b0825185` |
| Pinned PostgreSQL | `sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3` |
| Pinned Redis | `sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb` |

Read-only network-none installed backend probe confirmed FastAPI0.135.4,
Starlette1.6.0, Pydantic2.13.4, cryptography50.0.0 and Uvicorn0.32.1. Frontend
`npm ci`, lint, typecheck and production build passed in Docker with Router7.18.4,
Vitest4.1.11 and Vite6.4.3 locks. Backend uses Poetry2.4.1 main-only lock install
and pip consistency check. No host application packages or frozen-AI runtime were
used for acceptance. AI lock identity below is recorded, not an AI image qualification.

| Input | SHA256 |
| --- | --- |
| Backend poetry.lock | `88e4f0a1a946f003be341d415ffa690646f618fd2fbd35d60659eed1f5bcb9fd` |
| Backend pyproject.toml | `45e063803aaf06c334479848f6bbf91679263fad81c8a1ddbc7b9576cff2e774` |
| Frontend package-lock.json | `f4ee0f7d31f9e71af29f4d1d2812e2e53b59d74e5a2f5f55845414cbf8766acb` |
| Frontend package.json | `30a1c49e326b19c41103b4c134641439a8456428323394a73573740d6a2dd3e5` |
| AI uv.lock | `fb98d58d60838c69a0fab2a8c908b2023c7c351acdfc3c886be59ee6aa2560b1` |
| manage.py | `fe784665ab33777efc2e5bc6558da1786be1d5455022c95040f3bced18fbddb1` |
| verify.py | `e003d9b2a81a7e10c310ae80899878bd99336697b8ddc2b73a52df9675361a60` |
| backup_restore.py | `ac23ce7498c254d13ec05b1976aa423880b1e721a9038cce824dbaf98d2cc452` |
| compose.yaml | `64aa7cbac67f0e30d2a17e1963947d2a35074e16413e38fde981a7916c0a6a29` |

### Final source comparison and evidence retention

The accepted freeze has **1,127 files**; final byte comparison to current repository
found **zero changed or missing frozen paths**. Installed parity matched377 Python
files. The verifier's724-file runtime manifest aggregate was
`fe3eedfd7df0530c9d9e8f390957bc94c5bef11e2886525384472064c8fb2ea4`
before build and after recovery. Its deliberately narrower runtime fingerprint does
not include manage.py/verify.py; their exact hashes and full freeze cover them above.

The current-tree runtime fingerprint is
`ef771e8cdebc49620fb1e874e762526f01410097d17cb3fd8707096299963020`:
the sole additional path is `emulation/output/.gitkeep`, omitted when freezing
generated-output directories. No application-byte drift was detected; this empty
repository placeholder does not enter any application image. The two different
aggregate hashes are retained explicitly rather than silently equated.

Retained under the accepted source/run roots:

| Evidence | SHA256 |
| --- | --- |
| Source `freeze-manifest.json` | `4931ad08f920dc3a309c9cdec0f26d69c8d2b2a5062fbb6fc6ab44759caddff1` |
| Run `evidence/source-manifest.json` | `1674c218d0b5dd0077308cc66f003c5577c0732e9ea9074428ef72799a990bd0` |
| Run `evidence/result.json` | `df4ea858a9a7669cd7f0cce8ae211a041c8f782cb47f6f36fb2ed08b8c67d357` |
| Run `build-backend.log` | `42ffd978547cede8af07fb5bb8bdc65a6ec08d7ca08a9afbb9575cc86133cd50` |
| Run `build-frontend.log` | `10707a6f42bc7681cdc1ed7283d03cc32ec6ceefba33b064b52a47a4e26d678a` |
| Run `build-neo4j.log` | `62f5c165e96b1542786b8ceab06ad21b2bcb248ed7a4fe22a898dfd8bbe59c26` |

The successful encrypted archive remains in the run's `backup/`; key and source/
target secret files remain in separate private directories. Raw private diagnostics
are not publication inputs. Coordinator/evidence owner should preserve these exact
allowlisted manifests/results and escrow the archive/key separately before temporary
storage expires; this handoff does not claim an off-host escrow already occurred.

### Exact ownership and completed cleanup

| Role | Project | Proxy subnet / exact nginx IP |
| --- | --- | --- |
| Source | `nanfo-deploy-verify-e89f4ea622cf4caa8be968498b297c60` | `10.170.99.0/24` / `10.170.99.254` |
| Restore | `nanfo-deploy-verify-61ba32fae94b41669b658678e9fc76ac` | `10.170.100.0/24` / `10.170.100.254` |

Bounded exact-owned cleanup removed **22 containers,22 volumes,6 networks**.
Independent post-run exact-project label queries found **zero remaining containers,
volumes or networks for both projects**. Images/cache and encrypted/private evidence
are retained. Shared NANFO and other services were not stopped, migrated or deleted.
No pruning, privileged lab, detached jobs or commits. Historical0027/0028 upgrade
restrictions at the end remain binding; core acceptance does not authorize a shared
installation migration. The earlier failure sections below are historical evidence.

## Historical initial handoff — superseded blocker

## Delivered and verified

- `deploy/manage.py` allocates fresh private proxy /24s outside all inspected Docker
  IPAM pools and non-default IPv4 host routes. `init` persists the subnet and exact
  nginx gateway IP together in its private env. Requires `ip -j` on the Linux host;
  failed inventory/exhausted pools fail closed. Docker's host/none networks can have
  null IPAM configuration; the live-discovered null case is fixed and regression-tested.
- `deploy/verify.py` allocates source and restore together, avoiding collision before
  either network exists; records the two matched pairs in private run state. Docker
  still arbitrates races with unrelated operators at network creation. Serialize
  deployment operators; this selector does not reserve networks globally.
- Added explicit `--detect-source-drift` authorization for concurrent work without
  falsely attesting idle agents. Existing quiet/build/final gates remain mandatory.
  Each run now retains its exact per-file runtime source manifest.
- **252 deployment tests passed, 37 additional subtests passed, zero skips**, including
  four new allocation/authorization regressions. Scoped Ruff and `git diff --check`
  passed. Commands from `backend/`:

  ```sh
  PYTHONPATH=..:. /tmp/opencode/r07-backend/bin/python -m pytest -c pyproject.toml ../deploy/tests ../deploy/test_lifecycle.py -q --no-cov
  ```

  From repository root:

  ```sh
  /tmp/opencode/r07-backend/bin/ruff check deploy/manage.py deploy/verify.py deploy/tests/test_proxy_allocation.py
  ```

Dockerfile/Compose application setup files were not edited by this owner. No
`backup_restore.py` change was necessary before the current build blocker.

## Real build result and current blocker

Final frozen source: `/tmp/opencode/review0029-source-clxw_r0r`, 1,140 copied
tracked/unignored source files; no credentials, host virtualenv or node_modules.
Its `freeze-manifest.json` identifies every copied file. Verifier manifest:
`/tmp/opencode/nanfo-deploy-verify-p5xqpzxl/evidence/source-manifest.json`.

- Runtime source manifest: **722 files**;
  aggregate SHA256 `d599964d1ac178805b1b2b5fc422d8ced0698a6c8bb718fa420bf7ea9d90a938`.
- Frozen backend lock SHA256:
  `88e4f0a1a946f003be341d415ffa690646f618fd2fbd35d60659eed1f5bcb9fd`.
- Frozen frontend lock SHA256:
  `f4ee0f7d31f9e71af29f4d1d2812e2e53b59d74e5a2f5f55845414cbf8766acb`.
- New backend tag: `nanfo-deploy-verify-5874f30f5dc44bd6878087a98e1fc829:backend`.
- Exact backend ID:
  `sha256:2e0ba893b198ebccb2726ce27cf33741a08f7f1fbcbeeab36930685e96c40efe`,
  Linux/amd64. Actual locked Docker dependency install completed after two retained
  network-timeout failures. Independent non-root, read-only, network-none image
  inspection matched **377 installed Python files** to the frozen sources and
  confirmed **FastAPI0.135.4 / Starlette1.6.0**. This is a new build, not an old-image
  substitution. The final verifier build reused the newly completed locked layer.
- `npm ci` installed374 packages in the real frontend Docker dependency stage.
  The corrected frozen source then passes lint but fails typecheck at
  `frontend/src/features/digitalTwin/assetDownload.test.ts:7`:
  `Cannot find module '../../../../backend/tests/fixtures/asset-download.json'`.
  Existing frontend Dockerfile copies `frontend/` into `/build`; the backend fixture
  is outside that copy/layout. **No new final frontend image or new Neo4j build was
  reached.** Existing images were not substituted.
- Setup/frontend owner coordination is required: make the shared fixture portable
  to the frontend build while retaining its contract regression. This owner reported
  the blocker via parent commentary rather than changing another owner's Dockerfile.
- Final comparison of all722 manifest paths against the live repository found
  **zero changed paths** at handoff. Further source-owner edits require a new freeze
  and comparison; the successful source-parity probe does not accept a later tree.

## Executed attempts, all retained

Live command in the repository: `python3 deploy/verify.py --live --detect-source-drift`.
After a source freeze, command from the named frozen root:
`python3 deploy/verify.py --live --agents-idle`. Idle attestation applies to the
frozen tree only. Every run was supervised with a3,600-second outer timeout and
the verifier's own per-operation/cleanup bounds. No detached jobs.

Evidence paths below have prefix `/tmp/opencode/nanfo-deploy-verify-` and suffix
`/evidence/result.json`. Counts are matrix cases, not test counts.

| Run suffix | Passed | Failed | Blocked | Diagnosis |
| --- | ---: | ---: | ---: | --- |
| `8yu6g6am` | 3 | 1 | 29 | Quiet-source gate detected concurrent edits; no resources created |
| `xr8b_1zc` | 3 | 1 | 29 | Allocator TypeError on null Docker IPAM; corrected |
| `8wkjxjju` | 3 | 1 | 29 | Frozen-source reproduction of same null-IPAM defect; corrected |
| `brglqxq2` | 3 | 2 | 28 | Locked backend install PyPI wheel read timeout |
| `4yhow4en` | 3 | 2 | 28 | Second backend PyPI read timeout; network probe and subsequent install succeeded |
| `99gqrieu` | 3 | 2 | 28 | Backend built; temporary snapshot filter erroneously omitted frontend shared/state; additionally exposed cross-directory fixture |
| `p5xqpzxl` | 3 | 2 | 28 | Corrected snapshot; frontend fixture import is sole compiler blocker |

The first snapshot helper mistakenly excluded every directory named `state`;
it now excludes only `deploy/state/`. No repository source was deleted. Failed
snapshot/result/log evidence remains. Final result SHA256:
`10b068eb6d25bcdf4c3d5fefa67c0b506782b7426992bd4b8b7cfabb4633d663`.
Build logs are beside each run's `evidence/`, especially
`p5xqpzxl/build-frontend.private.log` and `p5xqpzxl/build-backend.log`.
Keep private logs/private generated secrets out of published evidence.

## Isolation, cleanup and blocked capabilities

Final exact-owned project pair and selected proxy boundaries:

- Source `nanfo-deploy-verify-5874f30f5dc44bd6878087a98e1fc829`:
  `10.4.128.0/24`, gateway `10.4.128.2`.
- Restore `nanfo-deploy-verify-25002dabc6f24f7ba5cd5e7a8186220c`:
  `10.4.129.0/24`, gateway `10.4.129.2`.

No application source/restore containers, volumes or networks were created; all
seven matrix cleanup cases passed with0 removed. Docker's legacy builder leaves
failed intermediate containers outside Compose registration: the four exact IDs
observed in these build logs were inspected as exited with matching build commands
and removed explicitly: `39960b10bf6c`, `152386f5c555`, `bac91a6fa0bd`,
`bd2490da2281`. Successful helper containers used `--rm`. Images/build cache and
private failure evidence remain; no pruning was performed. A connectivity probe
inadvertently pulled the current mutable Python tag (digest `392307d22300…`); it
was not used for builds. The subsequent wheel probe used the exact pinned base
`782412e85d0f…`. Shared NANFO services/stores were not changed or migrated.

**Blocked by compilation:** fresh0029 initialization/readiness/authenticated
workflows, negative readiness/restart, nonempty archive retention, cold encrypted
eleven-volume backup, distinct fresh restore, old-token invalidation and restored
report/asset/workflow/archive bytes. There is no completed encrypted backup to
recover from these runs. Generated key/secret directories alone are not backups.

Privileged lab, measured telemetry, frozen-model diagnosis and distributed failover
were not requested. They must remain explicitly unaccepted even after core closure.
Physical RF/participant evidence, full platform vision and production autonomous
qualification are separate external/program obligations.

## Resume and0027/0028 upgrade contract

1. Coordinate the fixture packaging fix with frontend/setup owners; rerun the252
   deployment cases plus affected frontend compilation checks.
2. Freeze all relevant source/lock inputs anew. Run the bounded verifier above from
   that tree (core only, no `--lab`), retain every matrix and compare final live-tree
   hashes. A normal core-only successful run still exits1 because Step15/lab gates
   are not complete; inspect `core_passed` and exact case counts, never relabel exit1.
3. Require current0029 fresh initialization and exact-image cold backup/restore.
   The verifier must never invoke initialization/migrations on restore targets.
4. Existing0027/0028 markers/images stay historical. Current `manage.py start` or
   restored adoption refuses old markers. Cold recovery uses identical original
   images, schema and matching historical tooling, with original secrets.
5. Upgrade is a **separately reviewed explicit release procedure**, not `start` or
   `restore`: preserve/authenticate the original cold backup; first rehearse the
  0027→0028→0029 chain (or0028→0029) on a distinct owned clone, review owner/domain
   release checkpoints and0029 telemetry-coverage invalidation/reconciliation,
   verify readiness/workflows and fresh backup/restore at0029, then obtain explicit
   operator authorization for any real installation change. No such shared upgrade
   was authorized or performed here; no rollback-by-silent-schema-downgrade promise.

No commits. Coordinator owns aggregate review tracking and final acceptance.
