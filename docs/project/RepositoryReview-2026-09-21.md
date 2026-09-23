# Repository review — 21 September 2026

## Verdict and scope

Reviewed commit `3f9f1f1` with an initially clean worktree. NANFO has a substantial,
tested operator-platform core and bounded measured-routing evidence. It is not yet
ready to be described as a completed production autonomous network platform.
The immediate priority is cross-layer correctness, evidence hygiene, dependency
maintenance and current-release acceptance, before further feature expansion.

This was a cross-repository inventory, targeted source/contract review, automated
suite execution, dependency audit and evidence-integrity review. It is not a claim
that every line of all 8,421 tracked files was manually inspected. The inventory
includes 6,470 files in `nanfo-experimental-campaign-014/`. Academic findings below
use the course guide and existing academic review; the ODT/PDF was not re-rendered
or visually re-audited in this session. Physical devices, RF accuracy, privileged
network campaigns, complete image deployment/restore and remote GitHub CI were not
re-executed.

No application source, dependencies, migrations, historical evidence or shared
services were changed. Review probes were created under `/tmp/opencode`. Newly
owned PostgreSQL/Redis resources were stopped and removed; their ports, process
cleanup and private-directory removal were verified. This report is the only
intended repository change.

## Fresh verification

| Check | Result | Boundary |
|---|---|---|
| Backend `poetry run pytest tests -q --no-cov` | **3,632 passed; 289 skipped** | Full default suite; opt-in skips remain skips |
| Backend Ruff `app tests scripts` | **PASS** | Current pinned Ruff |
| Backend Poetry lock / installed dependency consistency | **PASS** | Poetry metadata deprecation warnings remain |
| Frontend lint / TypeScript | **PASS** | Both TypeScript project checks |
| Frontend Vitest | **575 passed, 95 files** | Unit/component/contracts |
| Frontend Chromium, zero retries | **70 passed** | Default Vite development server and contract fixtures |
| Production build / unchanged bundle gates | **PASS: 387.96 / 410.16 KiB gzip** | Build tested; entire browser suite was not run against the built deployment |
| AI full suite / scoped Ruff | **463 passed / PASS** | Existing separate Python 3.12 AI environment and local artifacts |
| Disposable PostgreSQL audit lane | **253 passed; 12 skipped** | Owned fresh PostgreSQL; Redis initially absent |
| Follow-up disposable real Redis + PostgreSQL lane | **12 passed; zero skips** | All 12 previously skipped cases, including actual HTTP role/login/refresh smoke |
| Deployment logic suite | **248 passed** | `deploy/tests` and `deploy/test_lifecycle.py`; not a fresh image release |
| Emulation tests, from repository root | **111 passed; 6 skipped** | Unprivileged/default test scope |
| Four root qualification-script test modules | **23 passed; 1 skipped** | Run using the separate AI interpreter |
| Alembic metadata | **0029, single head** | Explicit `-c alembic/alembic.ini` |
| Campaign case-result referenced artifacts | **1,346 hashes matched; zero missing/mismatched** | Reference integrity, not independent scientific qualification |
| Campaign offline auditor | **FAILED: campaign_blocked_or_incomplete** | Agrees with retained final result |

Counts overlap; they are not an additive unique-test total. The default backend
suite still reports 289 skips even though the separate database lanes execute a
subset of those opt-in cases. Local backend Python is 3.14.7 and Node is 22.16.0;
deployment/CI uses different pinned versions.

An initial backend invocation hit the tool's 120-second timeout; the complete
rerun finished in 178 seconds. An initial mixed-environment auxiliary invocation
failed on an incorrect working directory, absent AI-only dependency and a
process-global permission-test interaction. Correct environment/root-separated
deployment, emulation and qualification runs passed as recorded above. Those
initial harness failures are not counted as application defects.

## Prioritized findings

### R01 — High: actual receiver credentials are committed in the campaign archive

- `nanfo-experimental-campaign-014/*/receiver-token`: **71 tracked, nonempty files**.
- These are authentication material, not merely token-named fixtures:
  `emulation/experimental_lab_receiver.py:55` loads the file and lines 244–249
  compare the request token to it before admitting operations.
- `.gitignore` excludes `.env`, but not these generated campaign credentials.
- Recorded campaign cleanup reports removal of owned services/resources. This
  review does **not** establish that the historical credentials are currently usable.

**Improve:** make exported evidence allowlist-based and credential-screened; preserve
raw evidence privately; publish sanitized manifests/results. Confirm these values
were never reused and invalidate any surviving authority. Review repository history
and access exposure before an explicitly coordinated history-cleanup operation.
Deleting the current files alone would not remove them from history. Add a
secret-scanning gate that covers extensionless files and nested archives.

### R02 — High: persisted Digital Twin model restore rejects actual backend responses

- Backend `backend/app/api/v1/networks.py:355–358` returns
  `Content-Type: application/octet-stream` and `ETag: "sha256:<digest>"`.
- Frontend `frontend/src/features/digitalTwin/assetDownload.ts:32–33` requires the
  stored model MIME and `ETag: "<digest>"`.
- `TwinPageContent.tsx:685` uses this path for `local_cas`, the storage backend used
  by new uploads (`backend/app/modules/network/service.py:799`).
- Reproduced by invoking the real frontend downloader with exact backend-style
  headers: both `model/gltf-binary` and `application/octet-stream` metadata reject
  with `Asset headers changed. Reload metadata.` The latter still fails on ETag.
- Unit and browser fixtures encode the incorrect frontend convention:
  `assetDownload.test.ts:11`; `tests/e2e/spatial-scene.spec.ts:102`.

**Improve:** align the client with the approved binary transport and digest-tag
contract, preserving byte-length and actual SHA-256 verification. Add a real
backend-response-to-client regression and upload → reload → restore browser test.
This explains how both separate test suites can pass while the real workflow fails.

### R03 — High: opaque request IDs break auth; failed refresh consumes the token

- `backend/app/core/dependencies.py:58–65` accepts arbitrary `X-Request-ID` strings.
- `backend/app/modules/identity/service.py:135,158,201,238,297` directly converts
  them with `uuid.UUID`, although the same module already has
  `normalize_audit_correlation` at lines 42–55.
- Reproduced login and refresh with an opaque request ID: both raise `ValueError`.
  Refresh rotates Redis state first (lines 289–292), then fails at line 297.
  Retrying the original refresh token returns 401 and deletes the session family.
- Report generation has the same unsafe conversion at
  `backend/app/modules/report/service.py:241`.

**Improve:** normalize/bound request identity before mutations and consistently
preserve the original identifier in audit metadata. Cover successful/failed login,
rate limit, refresh, logout and report generation with opaque IDs. Retain replay
protection; avoid consuming a token because downstream correlation handling fails.

### R04 — High: domain Redis streams accumulate without a retention policy

- `backend/app/events/publisher.py:73` appends without a bound.
- `backend/app/events/bus.py:110` acknowledges but does not delete entries.
- No `XTRIM`/`XDEL` implementation was found in the repository Python source.
  `deploy/retention.py` explicitly preserves streams and dead-letter queues.
- `deploy/redis-entrypoint.sh:9` caps Redis at **192 MB**, `noeviction`.
- A direct bus probe confirmed ten acknowledged events leave stream length ten,
  with zero pending entries. Redis acknowledgement does not reclaim stream data.

**Impact:** sustained ingestion grows memory until Redis rejects new allocations.
Event publishing, session creation/rotation and login rate-counter writes share
this store; telemetry load can therefore disrupt authentication too.

**Improve:** design durable archive/retention with consumer/pending watermarks,
safe replay boundaries and DLQ operations. Add memory/lag/oldest-pending alerts,
backpressure and a bounded-capacity soak test. Blind approximate trimming would
risk deleting events before their durable effects are complete.

### R05 — High: default development infrastructure binds publicly with sample secrets

- `backend/docker-compose.yml:10–11,28–30,44–45` publishes PostgreSQL, Neo4j and Redis
  on all host interfaces rather than loopback.
- `scripts/dev-start.sh:30–37` copies the sample environment and immediately starts
  those services. The sample contains `CHANGE_ME` database/JWT secrets.
- Core settings require strings but do not reject placeholder/weak JWT keys.

**Improve:** bind development stores to `127.0.0.1`, generate/require local secrets,
and reject unsafe configuration for non-development environments. The supervised
deployment has stronger private-network/secret handling; apply equivalent clarity
to the commonly used quick-start path. Actual remote reachability depends on host
firewall/network settings and was not probed.

### R06 — Medium/high: deployed clients share the gateway's login-rate-limit bucket

- `deploy/nginx.conf:37` supplies `X-Forwarded-For`.
- `deploy/Dockerfile.backend:23` starts Uvicorn without trusted proxy configuration;
  no deployment `FORWARDED_ALLOW_IPS` override was found.
- Installed Uvicorn defaults to trusted peer `127.0.0.1`, while nginx is a separate
  container. `backend/app/api/v1/auth.py:42` uses `request.client.host`.
- A middleware probe with a container-network peer and forwarded client address
  preserved the proxy address. Auth counts **all attempts**, with default five
  per minute (`identity/service.py:115–129`).

**Impact:** users behind the same gateway can exhaust each other's login allowance;
IP audit attribution also records the proxy.

**Improve:** explicitly trust only the deployed gateway/network boundary, retaining
nginx's overwrite of incoming forwarding headers. Test two distinct client IPs
through the real gateway plus a spoofed forwarding-header negative case.

### R07 — High-priority maintenance: current dependencies have reported advisories

Fresh advisory queries reported:

- Frontend production: **2 affected packages, moderate** (`react-router` and
  `react-router-dom`, installed 6.30.4). Full frontend: **5 affected packages**,
  including high-severity development `js-yaml` and moderate Vitest/mocker.
- Backend environment: Starlette 0.46.2 and ecdsa 0.19.2, plus development pypdf
  6.8.0 and pytest 8.4.2. The tool printed 65 entries containing duplicates;
  deduplication by package/advisory ID yielded **35 distinct pairs across 4 packages**.
- AI environment: pytest flagged. The CPU-specific `torch==2.8.0+cpu` distribution
  was skipped by the auditor; no clean Torch-security claim is made.
- Exact emulation requirements: advisories on **8 packages**: Ryu, eventlet,
  dnspython, WebOb, msgpack, requests, idna and urllib3. Raw output also contains
  duplicate advisory IDs and should not be quoted as unique flaw counts.

**Improve:** triage reachable runtime paths, update compatible locks and add recurring
dependency/image audits. Advisory matches are not proof of an exploitable NANFO
endpoint: React SSR findings need SSR exposure, pypdf/pytest are development
dependencies, and default JWT signing is HS256. The frozen emulation environment
must be versioned and requalified rather than silently changing historical runtime
identities to make a scanner green.

### R08 — Medium/high: asset listing is unbounded and includes every binary body

- `backend/app/modules/network/repository.py:366–375` has no list limit/pagination.
- `network/service.py:680–685` reads every active body; `asset_io.py:27–32` base64
  encodes it into the metadata response.
- The frontend then separately downloads a selected CAS asset during restore.

**Impact:** many models cause large response payloads, multiple in-memory copies,
slow scene initialization and possible process memory exhaustion. Per-object size
limits do not bound aggregate response size.

**Improve:** approve a bounded metadata-only pagination contract and fetch selected
binary bytes separately. Migrate compatibility consumers deliberately; preserve
existing historical identities and body verification.

### R09 — Medium: real browser/full-stack acceptance and portable CI are incomplete

- Default Playwright uses a Vite development server (`playwright.config.ts:11`) and
  mocked contracts. `production-twin.spec.ts` also uses route mocks; its name does
  not mean it exercises a production deployment in the default suite.
- Only one optional, read-oriented live browser test exists under `tests/live`.
  It skips without provisioned scope and is not run by the quality workflow.
- `.github/workflows/quality.yml:47–74` deselects historical-artifact backend tests;
  lines 135–141 select only the artifact-independent AI modules.
- General CI runs one deployment test module, not the full 248-test deployment suite,
  and does not directly run the standalone emulation/root-script suites.

**Improve:** provision an ephemeral full stack with actual workers, run critical
browser mutation/reload/download/revocation/reconnect flows against production
assets, and require zero skips in that lane. Deliver portable credential-free model
fixtures with hashes, explicit execution environments and full relevant CI coverage.
The twelve Redis/HTTP cases previously pending in docs now passed locally in this
review; remote CI and full browser-to-deployment acceptance remain separate.

### R10 — Medium: error recovery and observability need completion

- `frontend/src/app/App.tsx:33–61` has Suspense but no application/route error boundary;
  no `ErrorBoundary`/`errorElement` was found in frontend source. Lazy-chunk failures
  or render exceptions can remove the workspace without a recoverable error UI.
- Backend error envelopes repeatedly contain empty timestamps and, without a
  supplied header, empty request IDs (`backend/app/main.py:425,484,501,520`).
- Structured logging includes `merge_contextvars`, but no request-level
  `bind_contextvars`/cleanup was found. Unhandled-error logs omit request identity.

**Improve:** provide route-level recovery that preserves safe local state, plus
request metadata middleware used by both success/error responses and logging.
Add operational dashboards/alerts for event backlog, worker lag, saturation and
storage; runtime health alone is not a sustained-service SLO.

### R11 — Medium: current-status documentation conflicts with implementation/evidence

Examples:

- Root README line 42 and CompletionProgram README line 52 say schema **0027**;
  `backend/app/core/schema_version.py:7` and Alembic head are **0029**.
- Root README line 302 still describes legacy Ruff debt; the current full lint passes.
- `TechnicalDebt.md:14` reports a 408.36 KiB bundle; actual current size is 387.96 KiB.
- Fleet handoff lines 89–93 describe Operator as read-only; ADR026 and actual seeded
  role tests include write/rollback capability.
- `ai-engine/README.md:3–18` introduces v3 as current despite later qualified v4
  evidence and current-runtime compatibility distinctions.
- ExperimentalAcceptance still leads with preparation013/no-launch context;
  committed campaign014 contains a complete attempted matrix and a failed result.
- The “authoritative remaining checklist” in CurrentSprint lines 948–963 is fully
  checked, including old sandbox/production-readiness wording, despite current
  metadata-only plugin scope and open release/qualification obligations.

**Improve:** publish one current capability/evidence table keyed by source commit,
schema, image, qualification scope and validation date. Label historical sections
clearly and link newer outcomes. Resolve architecture-rule drift too: later ADRs
authorize owning-service calls and transactional audit/reference boundaries while
older rules still broadly mandate event-only integration and Celery.

### R12 — Lower priority: onboarding, repository organization and maintainability

- `backend/Makefile:12,15` invokes Alembic without its actual configuration path.
  Reproduced `alembic heads` failure: `No 'script_location' key found`; explicit
  `-c alembic/alembic.ini heads` succeeds.
- `scripts/dev-start.sh:39–46` says it waits for health but only sleeps two seconds
  and prints status. Quick start also does not start the six core workers or provision
  all private storage, although the README later explains this limitation.
- The tracked campaign expands to **1,317,464,024 bytes** (about 1.23 GiB) across
  6,470 files. Git pack storage currently compresses the whole repository to about
  97 MiB; do not confuse checkout size with clone transfer size.
- Large files include `telemetry/service.py` (2,601 lines),
  `TwinPageContent.tsx` (1,276), `deploy/verify.py` (2,995) and
  `verify_experimental_lab.py` (1,823).
- No tracked LICENSE, contribution guide, security-reporting policy or automated
  dependency-update configuration was found.

**Improve:** make documented setup executable and health-aware; publish a full-stack
development command; retain raw experiments in a checksum-addressed evidence store
with a compact repo index. Split large files along existing ownership boundaries
with behavior-preserving regressions. Clarify licensing/access and contribution
requirements before broader distribution. Preserve genuine raw evidence when
reorganizing; do not delete it merely to reduce file count.

## What remains by subsystem

| Area | Present | Remaining |
|---|---|---|
| Identity / tenancy / inventory | Current authorization, session families, role-aware CRUD, audit repair | R03/R05/R06; reviewed append-only remediation of old malformed audit records; better bootstrap/operator administration |
| Digital Twin | Canonical geometry, editing/history, model registration/CAS, groups, RF overlays | Fix R02; metadata-only asset paging; representative real-GPU geometry/model load; surveyed/geodetic registration as needed; canonical link IDs for measured path overlays |
| Telemetry / fleet | Real SNMPv3 collection, fenced scheduling, durable fleet spool, provenance/keyset history | R04; target-device/firmware and larger-fleet acceptance; discovery and wider protocol/interface coverage; enforce one collection owner |
| Simulation / RF | Deterministic bounded finite-buffer model, checkpoint/branch/compare, configured RF approximation | Real RF survey/calibration; richer interference/SINR/capacity and movement physics; evidence-linked automated scenario assembly; physical-fidelity validation |
| AI / recommendations | Qualified bounded v4 routing result, fresh recommendation evidence, confined inference | Sustained admitted operational deployment, independent training repetitions, workload/topology generalization, proactive timing and stability ablation; version-qualified promotion/drift workflows |
| AIOS vision | Operator-only registry/scheduling/consensus and SQLite tiered memory | Richer planning/retrieval/RAG/semantic graph integration and validated multi-agent operational usefulness; current runtime explicitly has execution unavailable |
| Governed autonomy | Safety/execution contracts, durable ownership/journals, STOP/recovery software | Authentic causal calibration, enforced future bounds, aligned observations/model/safety and joined receiver acceptance; successful recommendation/manual-driver tests do not close this |
| Experimental lab loop | Actual joined smoke and nominal/fault campaigns | Resolve campaign014's eight failures and complete a newly preregistered source-frozen acceptance campaign; independent signoff |
| Intent / vendor execution | Bounded manual emulation actions and compensation, persisted histories | Broad real-device driver/capability/rollback qualification; general production orchestration remains beyond current accepted scope |
| Plugins | Metadata registry lifecycle | Cryptographic package verification and actual sandboxed execution if the original runtime-plugin vision remains in scope |
| Reports | Durable real CSV/PDF pipeline, history/download/integrity | Fix opaque request IDs; more usable report layouts and Unicode font support; full browser/worker integration |
| Retention / storage | Conservative pin-before-reference archive/delete/restore | Scheduled owner reconciliation/jobs, partitioning, DB capacity admission, permanent-evidence lifecycle and safe CAS/history cleanup; ever-pinned records intentionally remain |
| Deployment | Supervised containers/workers, private secrets, health, historical backup/restore evidence | Source-matched 0029 image deployment and fresh encrypted restore acceptance, explicit 0027/0028 upgrade procedure, representative load/chaos and whole-host recovery |
| Research report | Working Chapters 1–6 and bounded experimental results | Refresh with verified newer evidence; promised proactive/stability/integrated evaluation, repeated training, intended-user study, source/admin issues |

### Campaign014: exact current recorded result

`nanfo-experimental-campaign-014/result.json` reports failed, not calibrated.
The offline auditor reproduced that verdict. Main matrix, excluding four completed
smoke cases: **68 attempted results; 60 completed, 8 failed**.

Completed outcomes include successful keeps, measured performance rejections followed
by restoration, fault restoration and predispatch rejection. They do not all mean
the selected route improved performance.

Failed cases:

1. `path0-1427-fixed1`: unproven; control error is not a performance outcome.
2. `path0-1429-fixed1`: measurement invalid.
3. `path0-1429-heuristic`: unproven; control error is not a performance outcome.
4. `path0-1433-fixed1`: unproven; missing `operator_policy` in outcome reconstruction.
5. `path0-1435-fixed1`: unproven; control error is not a performance outcome.
6. `path1-1432-heuristic`: measurement invalid.
7. `path1-1434-fixed1`: unproven; control error is not a performance outcome.
8. `path1-link-failure`: unavailable; controller records execution/recovery rejection
   `experimental_receiver_uncertain_or_rejected` and a bootstrap cleanup error.

Resource destruction/cleanup is recorded separately from verified routing restoration.
These classifications are retained evidence, not newly established root causes.
The 1,346 matching reference hashes establish byte integrity, not full replay of
every physical command or independent acceptance of each completed case.

### Academic obligations

The 18 September `ISPR2/Revised/Chapters_1_3_Reviewed/Academic_Review.md` identifies
unfinished objective-level evidence: proactive intervention lead time, normal/burst/
sustained workloads, independent trained initializations, safeguard ablation,
intended-user evaluation and complete recovery scope. Later software/deployment
evidence can update specific claims, but cannot automatically satisfy these research
questions. Keep the single working ODT/PDF and refresh Chapters 5–6 only from verified
results. Also resolve Cisco/Arista source-edition checks, genuine approvals/signatures,
repository access and the retained December Gantt versus November course target.

## Recommended order

1. **Contain evidence/credential exposure** and add export/secret-scanning controls.
2. **Repair current user-visible integration defects:** model restoration, request
   correlation/auth rotation, trusted-proxy attribution and local setup exposure.
3. **Add a production-build/full-stack browser lane** that reproduces these failures;
   broaden portable CI and dependency security gates.
4. **Bound operating resource growth:** domain streams first, then asset listing,
   retention scheduling, capacity alerts and soak tests.
5. **Build and qualify current0029 deployment/upgrade/restore**, with source/image
   evidence and representative workloads.
6. **Close campaign014 failures and research obligations** under unchanged historical
   evidence and newly frozen future protocols; qualify physical autonomy/RF only
   when authentic required measurements and installation evidence exist.
7. **Consolidate status docs and refactor large modules**, then prioritize broader
   AIOS, vendor, physics and plugin features against actual project scope.

No defensible single completion percentage follows from test counts or checked
historical slices. Track software delivery, integration acceptance, operational
readiness and scientific/physical qualification separately.
