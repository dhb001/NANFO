# ADR027 R09 — Production full-stack browser regression lane

## Readiness (2026-09-21)

**Actual production full-stack acceptance passed:5/5, zero failures/errors/skips,
zero retries.** Final receipt `/tmp/opencode/r09-live-08.json` has SHA-256
`bd87ef5a83f44b0da975f4bef4931c4a9a2f25ee906da5a0b0a24ef64ce6322b`.
The before/after source digest was identical:
`3d93b99289a5b5b94dd5d56e7a4afa29c3d4ef30e87f8e57d31936d49315b825`.
Actual execution used `/tmp/opencode/r07-backend/bin/python` (Python3.12.14), UID1000,
and `npm ci` from the upgraded current frontend lock. The runner rejects a successful
browser run when its source digest changes during acceptance.

Executed standalone checks: **17 harness tests passed**, scoped Ruff passed,
fullstack TypeScript and ESLint passed, CLI help passed. Direct Playwright
collection without the private fixture failed as intended (`R09 missing
R09_FIXTURE`), confirming that an unprovisioned dedicated lane does not skip.
The17 harness tests, Ruff, TypeScript and ESLint passed again after live debugging.

### Live attempts and preserved failure receipts

All allocated resources were cleaned successfully on every attempt. The final run
explicitly verified frontend/API/Postgres/Redis ports closed, all child process
groups reaped, both exact-owned containers and the Redis volume removed, and the
private runtime tree removed. A post-run Docker ownership-label query returned no
remaining R09 Neo4j containers. Shared services were not selected or changed.

| Receipt under `/tmp/opencode/` | Actual result / diagnosis |
| --- | --- |
| `r09-live-01.json` | Neo4j startup timeout before browser; insufficient private transaction-log preallocation space. |
| `r09-live-02.json` | Docker rejected diagnostic logging setup; changed to bounded `json-file` logging. |
| `r09-live-03.json` | Neo4j log confirmed default transaction-log preallocation exhausted256MiB private data mount; configured16MiB rotation,32MiB retention, no preallocation. |
| `r09-live-04.json` |5 browser timeouts: production CSS adds `↗` to login's accessible button name. |
| `r09-live-05.json` |5 failures confirming that exact login-name mismatch; selector now accepts the actual suffix. |
| `r09-live-06.json` |5 selector timeouts: scope labels include option text in `getByLabel`; role/accessible-name selectors fixed this. |
| `r09-live-07.json` |4pass/1fail; CAS upload/reload/restore passed, but page-2 wait captured the preceding page-1 refresh. Exact query predicate corrected. |
| `r09-live-08.json` |**5pass/0fail/0error/0skip**, stable source digest, every cleanup check true. |

Two additional preflight rejections during a concurrent `npm ci` created no runtime
resources. After that installer exited leaving dependencies absent, this workstream
ran `npm ci --no-audit --no-fund` successfully against the existing upgraded lock.
No application defect was reproduced; changes from live diagnosis were confined to
harness provisioning, diagnostics and browser selectors/synchronization.

Failure JSON receipts01–07 are retained unchanged. Opt-in raw diagnostic directories
`/tmp/opencode/r09-private-01` through `r09-private-07` are0700 and **private**; they
can contain disposable credentials/DOM snapshots and must not be published. There
is no successful-run raw diagnostic directory08.

Owned files:

- `backend/scripts/review_fullstack.py`
- `backend/scripts/test_review_fullstack.py`
- `frontend/playwright.fullstack.config.ts`
- `frontend/tests/fullstack/{support.ts,regression.spec.ts,tsconfig.json}`
- This handoff.

## Runtime and boundaries

The runner builds **Vite production mode, explicitly Terser-minified**, into a new
private temporary directory, then serves only that output through a loopback static
SPA server. It does not start Vite development or reuse an existing frontend server.
Build-time HTTP/WebSocket origins point to its newly allocated loopback API socket.
It records hashes of the exact build files.

It reuses `AuditLab`/`LocalLab` and `DockerRedis` from the existing isolated acceptance
tooling. PostgreSQL is a newly initialized password-protected local child; Redis is
either an explicitly selected installed Redis/Valkey7+ executable or an exact locally
installed Redis7+ Docker image. Neo4j5 Community is one new, labelled, pinned-image
container with private ephemeral data/log storage and only a high loopback Bolt
port. No shared Compose/core resource is selected. Images use `--pull=never`.
Neo4j logs are bounded to one1MiB Docker JSON log and disappear with the container;
transaction logs use16MiB rotation and32MiB retention in the private data filesystem.

The actual FastAPI application runs with its full lifespan and current migrations.
Independent production network-outbox, report and simulation workers run against
the same private stores. This extends the loopback HTTP-smoke approach rather than
importing its auth fixtures, provider overrides or disabled-lifespan fixture.
Only initial identities/password hashes/roles are provisioned through the owning
Identity repository. Tenants, membership,21 networks and21 devices are created by
real authenticated public HTTP calls. Browser login uses the public UI. The lane
uses no API response mocks, fake workers or dependency-auth overrides.
Bootstrap waits for all21 devices to reach the actual Neo4j topology read API
through the inventory outbox/Redis consumer before admitting the browser suite.

The launch environment is allowlisted; caller DSNs, app settings and browser URLs
are not inherited. Backend children run from the new private directory so a shared
backend `.env` cannot supply settings. Generated credentials pass privately to the
children; a UID-private0600 fixture supplies browser identities. API/worker CAS and
report roots are new0700 directories owned by the runner's non-root UID. Run the
lane under a **dedicated CI/test UID separate from deployed service users**; it
does not create accounts or change shared filesystem ownership. Root is rejected.
Login rate limiting remains enabled at30attempts/window to accommodate fixture
bootstrap plus all browser logins within one minute. Auth, role/membership checks,
JWT rotation/revocation and production credential validation remain real.

## Required browser checks

All five tests are required, single-worker, zero-retry, zero-skip:

1. Authenticated21-row network/device pagination; foreign tenant403; UI-created
   network and workspace survive page reload and real HTTP reads.
2. Real self-contained glTF upload and registration → protected CAS persistence →
   full browser reload → authenticated binary restore and actual GLTFLoader render.
   Requires `application/octet-stream`, quoted `"sha256:<digest>"` ETag and exact
   byte equality, then `model ready` in the minified app. Twenty additional distinct
   assets exercise21-record metadata pages, stable page reads, omitted inline bytes,
   page-size validation and UI second-page navigation. Foreign tenant metadata and
   binary reads must fail403. Identical-body dedup is respected by using distinct
   fixture bytes for pagination.
3. UI report request → independent report worker → generated CSV → real browser
   download with exact HTTP bytes and UI SHA-256 verification → persisted history.
4. UI simulation start → independent configured-model worker → completed numerical
   output/hash/trace → persisted history after reload. No physical qualification is
   inferred from the modeled output.
5. Actual topology socket subscription and automatic reconnect after closing only
   browser-owned sockets; real membership deletion makes old-token HTTP reads fail
   and socket resubscription close without an acknowledgement. UI logout invalidates
   access and refresh tokens and clears tab-local session state.

The socket fault injector wraps only native `WebSocket.send` to retain references
to actual application sockets, then calls their native `close`. It neither replaces
WebSocket nor injects frames. Browser tests listen to real backend frames.

**Owner prerequisites:** ADR027 binary download/frontend MIME handling and metadata
pagination (`include_data=false&page=1&page_size=20`, limit100) must be integrated,
along with current request-identity, dependency and setup owners' changes. The lane
fails on absent contracts. It does not silently fall back to legacy inline bodies.

## Exact parent/CI integration

Install locked backend dependencies, locked frontend dependencies and Playwright
Chromium/system libraries in the CI setup step. Provide installed `initdb` and
`postgres` on PATH, Node compatible with the locked frontend, and an available
Docker daemon. Provision the approved Neo4j5 Community image before running; pass
its **full local image ID**, not a tag. Provision Redis7+/Valkey7+ locally, or an
approved Redis7+ image. Allow approximately1GiB for Neo4j plus Chromium/build,
PostgreSQL and workers. `/tmp/opencode` must be writable by the dedicated UID.

CI step, **working-directory: `backend`**, with `R09_NEO4J_IMAGE_ID` and
`R09_REDIS_IMAGE_ID` containing approved locally installed `sha256:<64 hex>` IDs:

```sh
poetry run python -m scripts.review_fullstack --neo4j-image-id "$R09_NEO4J_IMAGE_ID" --redis-image-id "$R09_REDIS_IMAGE_ID" --report "$RUNNER_TEMP/r09-fullstack.json" --timeout 900
```

Exact locally verified invocation (choose a new report filename for a rerun):

```sh
/tmp/opencode/r07-backend/bin/python -m scripts.review_fullstack --neo4j-image-id sha256:9f75e8df4325a24f00fdd7a8c0bcce650a58375049b1058e496e8b43d6c36b37 --redis-image-id sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2 --report /tmp/opencode/r09-live-09.json --timeout 900
```

Those IDs were inspected from local `neo4j:5.26.12-community-bullseye` and
`redis:7-alpine`; no image pull or shared-container startup was used.

Installed-binary variant, same working directory:

```sh
poetry run python -m scripts.review_fullstack --neo4j-image-id "$R09_NEO4J_IMAGE_ID" --redis-server /usr/bin/redis-server --report /tmp/opencode/r09-fullstack.json --timeout 900
```

Report parent must exist and report filename must be new. Change the filename for
a subsequent run; the runner never overwrites prior acceptance evidence. Missing
images/binaries/browser dependencies, failed migrations, absent contracts, timeouts,
fewer than five browser cases, any skip/failure, source mutation or incomplete
cleanup return nonzero. There is no optional-dependency skip mode in this lane.

The runner directly invokes installed Vite/Playwright CLIs, so CI needs **no package
script**. If the parent adds an internal frontend alias, the exact command is
`playwright test --config playwright.fullstack.config.ts`; it requires the runner's
private `R09_*` environment and is not a replacement for the orchestration command.
The parent owns `.github` integration and any package-script changes.

### Standalone tooling checks

From `backend/`:

```sh
poetry run pytest scripts/test_review_fullstack.py --no-cov -q
poetry run ruff check scripts/review_fullstack.py scripts/test_review_fullstack.py
poetry run python -m scripts.review_fullstack --help
```

From `frontend/`:

```sh
node node_modules/typescript/bin/tsc -p tests/fullstack/tsconfig.json --noEmit
node node_modules/eslint/bin/eslint.js playwright.fullstack.config.ts tests/fullstack
```

The separate fullstack TypeScript project is necessary because the shared node
tsconfig's test glob currently covers `tests/e2e` and `tests/live` only.

## Cleanup and evidence

Every run reaps exact child process groups (including browser descendants), closes
the owned HTTP listeners, verifies the Neo4j container ID/image/random ownership
label before removal, and invokes the existing owned PostgreSQL/Redis teardown.
The cidfile recovers an interrupted Neo4j create. No container-name glob, shared
volume deletion, Docker prune or external DSN is accepted. TERM/interrupt and
subprocess-timeout paths run teardown; an unsuccessful cleanup fails the lane.

Public JSON contains stage/status, counts, fixed failure codes, failed test names,
source/build hashes and cleanup results. Passwords, tokens, raw HTTP bodies, process
logs and JUnit failure details stay in the private temporary tree and are removed
by default. For explicitly private diagnosis, `--private-diagnostics /new/path`
preserves only failure logs/JUnit/browser error contexts in a newly created0700
directory before runtime teardown. Failure to preserve diagnostics does not prevent
store/process teardown. Never publish that directory.
Playwright trace/video/screenshots are disabled because network/DOM artifacts can
contain credentials. Publish only the final JSON. Investigate a failing named case
in an explicitly controlled private rerun rather than publishing raw traces.

This lane tests browser reload and asset restore, not cold all-volume disaster
recovery. Source-matched current0029 deployment/backup/fresh-restore acceptance
remains the separate ADR027 deployment workstream.
