# ADR021 P0 delivery and security handoff

## Implemented

- `backend/app/modules/identity/service.py`: password verification uses Starlette's
  bounded AnyIO thread pool, including inactive and missing users. A public dummy
  bcrypt hash uses the current 12-round cost; missing users always fail even if the
  dummy check succeeds. This reduces the obvious missing-user timing difference;
  it is not a constant-time guarantee for database/network/audit paths.
- Both existing IP/email counters use one Redis `MULTI/EXEC` transaction containing
  `INCR` and `EXPIRE NX`. Redis 7 is already the deployment baseline. Existing key
  names, five-attempt threshold, all-attempt accounting, independently anchored
  fixed windows, 429/audit behavior, and Redis failure denial remain intact.
  A legacy counter without expiry is repaired. No Lua/fakeredis extra dependency.
- Generic credential errors remain `401 Invalid credentials.` Redis failure retains
  the existing `401 Invalid or expired token.` Authentication/session/token transport
  contracts are unchanged; cookie refresh and WebSocket tickets still need an ADR.
- `deploy/nginx.conf` adds `X-Frame-Options: DENY` and enforced CSP:
  `base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'`.
  All security headers use `always`, including proxy errors and SPA fallback.

## CSP compatibility and development documentation

This is an intentionally limited enforced policy, **not a complete XSS resource
allowlist**. There is no `default-src`, `script-src`, `style-src`, `connect-src`,
`img-src`, or `worker-src` restriction. React inline styles, Vite development
scripts/HMR, same-origin or configured API/WebSocket connections, Three blob fetches,
blob textures/workers, and report blob downloads retain existing resource behavior.
FastAPI development `/api/docs` and its CDN/inline Swagger resources are not blocked
by this policy. Docs remain subject to the application's existing environment gate.
The gateway policy applies only when nginx serves/proxies the page; Vite alone does
not add these headers. External framing and plugin objects are intentionally denied.
Any later strict resource policy needs observed deployed asset origins plus browser
acceptance for model imports/restores, report downloads, and API docs; do not guess
a source allowlist or add broad script exceptions merely to obtain a green build.

Browser tests read the actual policy from nginx configuration and apply it to the
document response. Local nginx integration independently verifies actual response
headers on static, SPA, source-map 404, upstream 401, docs-path, and health responses.
The docs-path upstream is a fixture, not a live Swagger integration claim.

## CI contracts

`.github/workflows/quality.yml` runs on PRs, main/master pushes and manual dispatch:

| Job | Pinned environment | Commands / scope |
| --- | --- | --- |
| Backend | Python 3.12.14, Poetry 2.4.1, `poetry.lock` | `poetry check --lock`; `poetry sync --with dev --no-root`; pip check; Ruff app/tests/scripts; pytest unit + service-contract integration; local nginx header test |
| AI | Separate job/venv, Python 3.12.14, uv 0.8.22, CPU `uv.lock` | `uv sync --locked --group dev`; uv pip check; isolated backend-schema import; Ruff src/tests/shadow/runtime scripts; artifact-independent transport/PPO/holdout/shadow/agent-runtime tests |
| Frontend | Node 22.22.0, `package-lock.json` | `npm ci`; lint; typecheck; unit; `perf:bundle` (production build + existing budgets); lock-matched Chromium install; all Playwright tests with zero retries |

Actions are existing checkout/setup-python/setup-node/upload-artifact releases pinned
to verified commit IDs. Workflow permissions are contents-read, checkout credentials
are not persisted, timeouts are bounded, and test reports are retained for seven days.
Python static typing is not advertised: neither Python project defines a supported
typechecker gate. Frontend uses its existing TypeScript scripts.

### Clean-checkout historical evidence limitation

`ai-engine/artifacts/` is ignored and absent from Git checkout. The AI conftest's
`producerSpec()` reads `artifacts/adr014-001/release.json`; refinement suites also
read historical release/checkpoint data. Backend `tests/unit/test_model_diagnostics.py`
requires ADR014 checkpoint/history/source files and an AI runtime at its frozen path.
Default CI explicitly deselects only historical-fixture functions in that backend
module, retaining its artifact-free input-validation tests, and names the five
independent AI test modules. It also deselects the actual Linux confinement syscall test, which
hardcodes `ai-engine/.venv/bin/python` and requires Landlock ABI5; its fail-closed
unit test still runs. This is **partial AI/history coverage**, not full-suite acceptance.
An approved portable fixture/evidence delivery contract is required to expand these
gates. No historical artifacts, trained tensors, release hashes, or local environment
were manufactured or overwritten to make CI pass.

`.github/workflows/disposable-integration.yml` is manual-only and additionally
requires `run_database_tests=true`. It uses job-owned, digest-pinned PostgreSQL17.6
and Redis7.4.5 service containers with dynamically assigned ports. Public fixture
credentials are scoped to those ephemeral services. Existing supported DSN variables
select disposable-schema migrations/CAS/recovery/outbox tests for Intent, Report,
Autonomy, Simulation, Alert, Plugin, Telemetry, Network outbox and Spatial. The new
`AUTH_TEST_REDIS_URL` test exercises real concurrent login transactions, fixed TTLs,
legacy TTL repair and lost EXEC acknowledgement. Tests clean only their owned keys
or UUID schemas; hosted-runner services are discarded with the job. No live topology,
privileged network lab, model campaign, Compose deployment, or infra launcher runs.

## Verification performed locally

- Auth/security/session and auth HTTP regression selection: **87 passed**.
- `NANFO_TEST_NGINX=1 poetry run pytest tests/integration/test_gateway_headers.py
  tests/integration/test_login_rate_limit_redis.py --no-cov -q`: **6 passed, 1 skipped**
  (real Redis URL intentionally unconfigured; no database/container provisioned).
- `npm run test:e2e -- tests/e2e/gateway-csp.spec.ts --project=chromium --retries=0
  --workers=1`: **2 passed** (React login/Twin, inline styles, blob fetch/worker,
  same-origin frame denial). Existing local Node22.16 and Chromium used.
- Scoped backend Ruff and browser-test ESLint passed; frontend typecheck passed.
- Backend lock check and installed-environment pip check passed. Existing local
  backend interpreter is Python3.14; the pinned CI Python3.12 install is not claimed
  locally executed. Poetry emits existing project-metadata deprecation warnings.
- Artifact-independent AI command: **124 passed** in the existing AI environment.
- Explicit disposable database-lane selection: **98 tests collected**, confirming
  the named commands and fixtures exist; database execution was not performed.
- Workflow syntax/context validation: actionlint1.7.7, shellcheck unavailable.
  Initial actionlint caught job-level service-port context misuse; moved service
  URLs to the test step environment and used string port keys; rerun passed.
- Initial new concurrent auth tests had an async-generator assertion mistake;
  corrected to awaited per-key assertions, then all87 passed.

**CI has not been remotely executed.** Full clean-runner install, all frontend
browser/build gates, the opt-in database lane, and integrated concurrent workstream
acceptance remain parent/release verification. Shared dependency/config/main/Compose,
deployment tools, README, sprint and journal files were not edited by this workstream.
No commits or shared infrastructure operations were performed.

## Final CI integration check

- Exact backend lint `poetry run ruff check app tests scripts`: **passed** after
  workstream integration. No legacy violations observed, no narrowed scopes or
  new exclusions required.
- Created a fresh AI-only environment at `/tmp/opencode/adr021-ci-ai` using
  **uv0.8.22**, **Python3.12.14**, and `uv sync --locked --group dev`. Existing
  project environments and dependency locks were not modified. All25 installed
  packages passed `uv pip check`.
- With ambient `PYTHONPATH`/`VIRTUAL_ENV` removed, user site disabled, and both
  thread-count variables set to1, ran the exact CI command:
  `uv run --no-sync pytest -q --junitxml=quality-results.xml tests/test_transport.py
  tests/test_ppo.py tests/test_holdout.py tests/test_shadow.py`: **136 passed**.
  This includes the six new script/module × record/POST/GET backend-export CLI
  cases. The local generated report was removed after inspection.
- Confirmed SQLAlchemy, FastAPI, pydantic-settings, Redis and asyncpg are absent
  from that environment. Actual backend `ModelDiagnosticRecord` and
  `ModelDiagnosticsResponse` imports passed; only backend package initializers,
  `artifact_io` and `model_diagnostic_schemas` were loaded. CI now explicitly checks
  this boundary before tests, with isolated Python and disabled user site.
- Exact AI lint `uv run --no-sync ruff check src tests scripts/shadow
  scripts/shadow_evaluate.py`: **passed** in the fresh locked environment.
- Python3.12.14 is stable in the published
  [setup-python version manifest](https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json).
  The Ubuntu24.04 x64 asset in release
  [3.12.14-31661455385](https://github.com/actions/python-versions/releases/tag/3.12.14-31661455385)
  returned HTTP200. Backend, AI and disposable-database workflow Python pins remain
  valid; no version substitution was needed.
- Workflow validation remains local; GitHub CI and disposable services were not run.

## ADR023 CI update — migrations0025/0026/0027

Only `.github/workflows/quality.yml`, `.github/workflows/disposable-integration.yml`
and this handoff changed. The AI job and its existing artifact-independent selection
are unchanged in this increment. Backend lint remains the exact unfiltered command
`poetry run ruff check app tests scripts`.

### Automatic no-infrastructure gate

`poetry run pytest tests/unit tests/integration -q --junitxml=quality-results.xml`
uses the explicit `--deselect` function-node list in `quality.yml`. Directory
discovery includes all new retention, fleet, replay, distributed startup/fanout,
geometry, independent-validation, provider configuration and autonomous execution/
FRR/safety regression modules. No broad `-k`, marker, module-ignore or best-effort
failure suppression was added.

Historical-fixture exclusions are precise and intentional:

| Module / dependency | Excluded cases (including parameter expansions) | Retained cases |
| --- | --- | --- |
| `test_model_diagnostics.py` / `registered` fixture | 17 | 7 input/path/schema cases |
| `test_live_providers.py` / `registered` fixture | 26 | 2 explicit opt-in/partial-configuration cases |
| `test_passive_observer.py` / `source` fixture | 20 | 8 feed/tamper/session-format cases |
| `test_model_diagnostic_confinement.py` | 1 actual Linux syscall proof | missing-Landlock fail-closed test |

The first three fixture chains read ignored `ai-engine/artifacts/adr014-001` and/or
`adr014-holdout-001` checkpoint, source, history, plan, selection and benchmark/raw
session files. Some also execute the frozen `ai-engine/.venv/bin/python`; a backend
clean checkout has neither that runtime nor those historical artifacts. All27
deselected function names were checked against current source definitions. New tests
in these files are discovered automatically and are not silently excluded. Full
historical provider acceptance still needs authentic evidence and its supported
confined runtime, not synthetic replacements installed by CI.

Existing opt-in tests retain their explicit environment skips. In particular,
`NANFO_LIVE_PROVIDER_POSTGRES`, `RUN_DISTRIBUTED_REALTIME`, `FLEET_LOCAL_SNMP`, and
`NANFO_REPLAY_PROBE_CAPTURE` are not enabled by automatic quality CI. The
`test_live_provider_worker.py` gate additionally requires historical artifacts and
starts disposable Docker services itself; it is not part of the new PG lane.

### Manual disposable PostgreSQL gate

The workflow still requires manual dispatch with `run_database_tests=true` and
uses only its job-owned PostgreSQL/Redis services. Exact added test contracts:

| Module | Environment | Migration/test boundary |
| --- | --- | --- |
| `test_retention_complete_postgres.py` | `RETENTION_TEST_DSN=postgresql+asyncpg://…` | Unique schema, chain through0025; owner references, archive/delete/restore, pin races, CLI and worker checks |
| `test_fleet_postgres.py` | `FLEET_TEST_DSN=postgresql+asyncpg://…` | Unique schema,0026→0025→0026; lease/lock races and actual owned-child SIGKILL/spool recovery; mocked SNMP I/O |
| `test_autonomous_execution_postgres.py` | `AUTONOMY_TEST_DSN=postgresql+asyncpg://…` | Unique schema, actual0027 migration/reversal, durable receiver/journal fencing; FakeDevice/FakeFRRNetwork, no network namespace or physical command |

`AUTONOMY_TEST_DSN` changed from psycopg2 to asyncpg because the new execution test
passes it directly to `create_async_engine`; earlier autonomy tests convert the
driver explicitly and remain compatible. Fleet's recovery child also consumes its
DSN directly as asyncpg. Retention converts drivers as needed. None of these tests
requires a new Redis variable; fleet and execution use their existing fake Redis
fixtures. Existing Spatial/Asset/Telemetry DSNs and tests remain in the lane.
This is fixture migration coverage, not an independently executed full deployment
upgrade/restore certificate through0027.

### Distributed real-socket lane portability blocker

The three existing socket tests are collected but not enabled automatically:

```sh
# Only on a separately admitted disposable host with the exact prerequisite images:
RUN_DISTRIBUTED_REALTIME=1 poetry run pytest --no-cov -q \
  tests/integration/test_distributed_realtime_sockets.py \
  tests/integration/test_distributed_main_sockets.py
```

Both fixtures use Docker `--pull=never` with hardcoded **local image IDs**, not
pullable registry manifest references:

- Redis: `sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2`
- Neo4j: `sha256:9f75e8df4325a24f00fdd7a8c0bcce650a58375049b1058e496e8b43d6c36b37`

A fresh GitHub-hosted runner cannot acquire those IDs through a documented fixture
input. No runnable hosted manual socket lane was invented or enabled. A future
owner change must expose reviewed pullable references or provide verified image
archives before wiring this lane. The tests themselves use UUID-owned containers,
loopback ports and child APIs; they do not launch the privileged emulation lab.
Local SNMP fleet acceptance separately needs `FLEET_TEST_REDIS_URL`,
`FLEET_LOCAL_SNMP=1` and installed snmpd/snmpget; it was not enabled here.

### Verification for this increment

- Exact backend lint: **passed**, no exclusions or legacy violations.
- Executed the literal backend pytest command parsed from `quality.yml`, with
  infrastructure opt-in variables absent: **2936 passed,202 skipped,64 deselected**,
  coverage81%,114.22s on the existing local Python3.14.7 backend environment.
  The first tool invocation hit its120s wall timeout near suite completion;
  the second invocation completed with the same selection and a larger tool timeout.
- Full manual PG command: **188 tests collected**. New ADR023 modules account for
  **61** of those tests; distributed socket modules separately collect **3**.
- All27 explicit deselection names exist. Actionlint1.7.7 and owned-file whitespace
  checks passed. Shellcheck is unavailable locally.
- No PG/Redis/Docker/hardware gate, privileged lab, deployment operation, training,
  or remote GitHub CI run was executed. Local Python3.12 clean backend installation
  was not rerun; the previously verified released CI pin remains3.12.14.
