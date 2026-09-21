# ADR-026 workstream 7 — quality gates and verification

## Final integrated0029 gate — 2026-09-20,21:02 UTC

**Full default isolated suite:253 passed,12 skipped,0 failed (265 collected).**
**Deployment:248 passed,0 skipped/failed.** These are the latest complete runs,
superseding the blocked snapshots below. Commands ran serially while parent
backend testing was paused; no shared database or Docker operation was used.

### Current schema and historical compatibility

Preserved `0029_experimental_telemetry_coverage.py` unchanged: it adds no tables,
revokes Autonomy coverage and resets reconciliation metadata. Explicit current
contract is now0029; readiness/initialization/maintenance/lifecycle/verifier inherit
that centralized value. Ancestor tests cover every revision0029→0001 and explicitly
check0029's parent0028. `test_verify_measured_twin.py` uses the centralized current
target instead of freezing repository head at0028; its historical acceptance
constant/command remains0027. Both0027 and0028 migration evidence names remain
exportable unchanged, while current lifecycle rejects their historical markers.
No safety/archive capability floor or migration body was changed.

### Disposable PostgreSQL robustness and diagnostics

Only `AuditLab` in `scripts/audit_isolated_suite.py` adds test-cluster resource
settings:32MB shared buffers,2MB work memory,16MB maintenance memory,40 connections,
32MB minimum/128MB maximum WAL and30s checkpoints. Existing30s lock/120s statement
limits remain. WAL/fsync/full-page durability defaults are retained. Historical
`LocalLab` and deployed PostgreSQL settings are untouched.

Server stderr is now drained continuously to an in-memory tail capped at128 chunks
of4096 bytes. Reports retain **only** SQLSTATE/severity counts, fixed diagnostic
classifications (PANIC, allocation/disk/fsync failures, SIGKILL/SIGSEGV/SIGBUS,
recovery/missing-file/size-limit signals), pre-cleanup child return code and available
temporary space. No SQL, driver messages, credential strings or raw log tail are
exported; the tail is cleared on cleanup and the reader thread is joined.
Added regressions prove bounded log storage, credential-message exclusion, owned
spawn configuration and preserved durability.

The new full run recorded **no diagnostic error codes**, a still-running PostgreSQL
child before cleanup,3057 bytes in its private bounded tail, and1,646,227,456 bytes
free in the temporary filesystem at completion. Every cleanup field passed,
including the diagnostic thread. The previous server-recovery crashes were not
reproduced under the reduced resource configuration. **Their original cause is
not proven**: earlier code discarded server stderr, so OOM, disk, PANIC or outside
process interference cannot be asserted retroactively. This is a validated harness
mitigation with future diagnostics, not fabricated crash-root-cause evidence.

### Exact final commands/results

From `/home/DHB/Documents/NANFO/backend`:

```bash
poetry run python -m scripts.audit_isolated_suite --timeout 1200 \
  --report /tmp/opencode/nanfo-audit/workstream7-0029-diagnostic-001.json
PYTHONPATH=..:. poetry run pytest -c pyproject.toml ../deploy/tests ../deploy/test_lifecycle.py -q --no-cov
poetry run pytest tests/unit/test_runtime_health.py tests/unit/test_verify_measured_twin.py tests/integration/test_readiness.py scripts/test_audit_isolated_suite.py -q --no-cov
```

- Full default PostgreSQL: **253 passed,12 skipped in155.15s**, exit0, JSON `partial`,
  no failed cases. Includes all noncanonical UUID deletion/mapping cases, asset
  retirement, opaque request-ID endpoint/audit regression, experimental DB and
  current-head fixture migrations through0029.
- Full deployment: **248 passed in5.01s** (prior244 plus4 compatibility cases).
- Runtime/readiness/historical-verifier/runner: **87 passed in3.91s**.
- Earlier owned runner/unit check during this change:67 passed in3.68s; scoped Ruff
  passed. This is an overlapping subset, not an additional unique test total.

The12 skips remain exactly4 Intent Redis locks,1 Report Redis replay,1 login Redis
limiter,3 role-service login/rotation and3 real HTTP smoke profiles. Local Redis/
Valkey remains absent. CI supplies each URL and must pass the existing zero-skip
gate; local execution does not claim Redis/HTTP/browser or live deployment acceptance.
Parent owns final frontend/backend closure and global tracking. No commits made.

## Final requested verification — 2026-09-20, approximately20:40–20:55 UTC

**Historical blocked attempt; superseded by the integrated0029 gate above.**
Waited for the observed parent full-backend/frontend process IDs to exit, then ran
the full default isolated lane with1200s allowance and deployment tests serially.
No application/test/schema code was changed during this verification pass.

```bash
# Working directory: /home/DHB/Documents/NANFO/backend
poetry run python -m scripts.audit_isolated_suite --timeout 1200 \
  --report /tmp/opencode/nanfo-audit/workstream7-postgres-final-20260920.json
PYTHONPATH=..:. poetry run pytest -c pyproject.toml ../deploy/tests ../deploy/test_lifecycle.py -q --no-cov
```

- Full default lane collected **265 cases**. Its PostgreSQL fixture process began
  closing connections during migration/teardown; subsequent fixtures errored and
  JUnit was truncated/malformed. Report status `incomplete`, `counts: null`,
  `pytest_exit: 1`, failure `ParseError`. No aggregate pass count is inferred.
- Deployment rerun: **243 passed,1 failed in5.21s**. Failure:
  `test_schema_contract.py::test_explicit_current_contract_matches_entire_chain_and_readiness`.
  New concurrent `backend/alembic/versions/0029_experimental_telemetry_coverage.py`
  makes repository head0029, while `CURRENT_SCHEMA` remains0028. This migration and
  the existing explicit deployment target are preserved for parent/owner resolution.
- Full default retry, same command with report
  `/tmp/opencode/nanfo-audit/workstream7-postgres-final-retry-20260920.json`, again
  recorded `incomplete`, null counts and malformed JUnit. A read-only disk monitor
  observed `/tmp` free space remain above1.6GB during that retry; disk exhaustion
  is not established. PostgreSQL startup succeeded; failures appeared mid-suite.
- Full-file Identity diagnostic passed **16 tests in13.68s**, including
  `test_opaque_request_header_endpoints_atomic_audit_and_replay`:

```bash
poetry run python -m scripts.audit_isolated_suite --timeout 300 \
  --test tests/integration/test_identity_audit_repair_postgres.py \
  --report /tmp/opencode/nanfo-audit/workstream7-identity-final-20260920.json
```

To retain the first actual database exception before cascading failures, a
process-local diagnostic added pytest `--maxfail=1 -s` without editing the runner:

```bash
poetry run python -c 'from scripts import audit_isolated_suite as suite; original=suite.run_pytest; suite.run_pytest=lambda argv,env,root,timeout: original([*argv,"--maxfail=1","-s"],env,root,timeout); raise SystemExit(suite.main(["--timeout","1200","--report","/tmp/opencode/nanfo-audit/workstream7-postgres-diagnostic-20260920.json"]))'
```

Diagnostic result: **94 passed,5 skipped,1 setup error in62.48s**, stopped early
out of265 collected. First error in Spatial fixture migration commit:
`psycopg2.OperationalError: server closed the connection unexpectedly`, followed
by `FATAL: the database system is in recovery mode`. This establishes a local
PostgreSQL failure, not its root cause; no application assertion was weakened.
The runner's private logs are removed during owned cleanup, so server-side crash
diagnostics require a separately instrumented owned run before another full retry.

All four isolated invocations recorded child reaping, graceful stop, closed ports
and private-tree removal. Shared databases/services were not used. The first run
visibly passed the new asset-retirement and all noncanonical UUID-map deletion
cases before the later infrastructure failure; this is not a completed full gate.
Redis remains unavailable locally; the default lane still has12 Redis-dependent
cases expected to skip, but neither incomplete run provides a final skip total.
The fail-fast diagnostic's5 skips are its actual executed subset only.

**Parent handoff:** resolve/coordinate0029 current-source compatibility and diagnose
the disposable PostgreSQL recovery failure; then rerun the unmodified default
selection plus all244 deployment cases. Parent owns final backend/frontend and
global-doc closure. Earlier results below are retained as historical snapshots.

## Deployment schema follow-up (expanded user-authorized ownership)

Current-source deployment now targets0028 consistently; historical0027 evidence
and measured-twin acceptance target are preserved. Central contract:
`backend/app/core/schema_version.py`, host adapter `deploy/schema_contract.py`.
Runtime-health's concurrent0028 change was preserved. Fresh initialization and
readiness/maintenance share the constant; lifecycle markers/adoption and verifier
use it explicitly. Fresh start inspects the installed checkpoint before marking
success, rejecting stale images. New acceptance cases are named `migration_0028`;
old `migration_0027` evidence remains exportable unchanged.

Backup/restore cannot bypass0027 archive/autonomous safety checks at0028 or later.
It additionally checks0028 experimental run/resource/action release state, compares
restored proof and never clears ownership. Old-image cold restore remains exact
and version-neutral; current lifecycle adoption refuses old markers rather than
pretending they are a new accepted release. Details/tradeoff: `deploy/README.md`
and `deploy/VALIDATION.md`. No live images/datastores or historical records changed.

Verified from `backend/`:

```bash
PYTHONPATH=..:. poetry run pytest -c pyproject.toml ../deploy/tests ../deploy/test_lifecycle.py -q --no-cov
poetry run pytest tests/unit/test_runtime_health.py tests/unit/test_verify_measured_twin.py tests/integration/test_readiness.py -q --no-cov
```

**244 passed** deployment (the entire original216 plus28 new regressions),
**76 passed** runtime/readiness/historical-verifier. Scoped deployment/runtime Ruff
passed. Host CLI `--help` imports for manage/verify/release_manifest passed.
Full new0028 live deployment acceptance is still required; these results establish
source compatibility and regression coverage, not acceptance of a deployed image.
The earlier workstream note about leaving deployment constants untouched describes
the original scope, superseded only by this explicit deployment repair request.

Earlier snapshot, 2026-09-20. Then-current full isolated PostgreSQL lane: **246 passed,12 Redis-dependent
skips,0 failures**. Latest full backend: **3598 passed,269 skipped**. Redis/HTTP and
browser integration remain unverified locally. These results were obtained from
the concurrently edited worktree, using local Python3.14.7; hosted CI is configured
for Python3.12.14. Earlier failing runs below remain historical evidence.

## Earlier owner-convergence follow-up

Identity's measured-alert lock repair resolves all8 alert failures documented
below. Re-ran the **entire default runner selection**, not just failing cases:

```bash
# Working directory: /home/DHB/Documents/NANFO/backend
poetry run python -m scripts.audit_isolated_suite \
  --report /tmp/opencode/nanfo-audit/workstream7-postgres-005.json
poetry run pytest tests -q --no-cov
```

- Default isolated lane: **246 passed,12 skipped in186.04s**,258 collected, exit0.
  JSON status `partial`, empty failed-case list, all cleanup fields true.
- Full backend: **3598 passed,269 skipped in289.04s**. This command does not collect
  the separately wired `scripts/test_audit_*.py` cases or enable opt-in services.
- Newly added `test_asset_retirement_retains_bytes_and_unblocks_inventory[0028]`
  and both intent-owner detail-proof deletion cases were automatically collected
  from the existing `test_network_inventory_postgres.py` file and passed. Both
  runner and CI select whole files, so future additions there are included.
- An earlier default run alongside the full backend run recorded **244 passed,
  2 failed,12 skipped in240.28s**, report `workstream7-postgres-004.json`.
  `test_configured_factory_worker_stages_then_separate_receiver_executes` observed
  applied0 instead of1; `test_action_expiry_interrupts_blocked_verification` expired
  before execution (its budget is150ms). Both passed on the full serial rerun.
  Resource-contention sensitivity is still an owner follow-up; assertions and
  safety deadlines were not loosened and the failed run is retained.

### Redis/Valkey availability and version contract

Checked `command -v` for `valkey-server`, `redis-server`, `redis6-server`,
`redis7-server`, `redis-stack-server`; all absent. `/usr/bin/*redis*` and
`/usr/bin/*valkey*` searches also found none. No install, pull or shared service.
`--redis-server` accepts an explicitly supplied absolute installed Redis or Valkey
binary, runs bounded `--version`, requires server major version7+, and records the
normalized version in JSON. Tests cover Redis7.4.5/Valkey8.1.3 acceptance and
old/unrecognized version rejection. No actual compatible binary was available
to exercise startup locally.

```bash
poetry run pytest scripts/test_audit_isolated_suite.py -q --no-cov
poetry run ruff check scripts/audit_isolated_suite.py \
  scripts/test_audit_isolated_suite.py scripts/test_audit_role_profiles.py \
  scripts/test_audit_http_smoke.py
```

Runner regressions: **8 passed in0.42s**; scoped Ruff and Actionlint passed.

### New isolated real HTTP/service wiring smoke

`backend/scripts/test_audit_http_smoke.py` starts Uvicorn on an owned loopback
socket using the real application/router/envelopes. Only DB and Redis providers
point to the disposable fixtures; JWT/session checks, password verification,
permission mapping, tenant checks, services and repositories are real. Background
Neo4j/worker lifespan is disabled for this bounded HTTP lane.

For each Admin/Operator/Read-Only profile it exercises unauthenticated401, actual
login, `/auth/me`, refresh rotation,21-row pagination, foreign-tenant403,
write authorization and durable Network outbox creation, current membership
revocation, logout, and revoked-session refresh denial. Uses a dedicated Redis
database4 so earlier role-service logins do not consume its rate-limit budget.
No shared frontend files were changed. This is HTTP-client→FastAPI, **not a browser
UI smoke**. Its3 cases were collected but skipped locally because real Redis is
absent; they are not claimed as runtime-verified.

The default runner and CI now include this file. CI supplies
`AUDIT_HTTP_TEST_REDIS_URL` and still rejects any skipped JUnit case. All12 current
local skips have explicit CI URLs:4 Intent,1 Report,1 login limiter,3 role-service
login/rotation and3 HTTP cases. Hosted zero-skip execution remains required.

```bash
# After an approved Redis7+/Valkey7+ binary is available (not run locally):
poetry run python -m scripts.audit_isolated_suite \
  --redis-server /absolute/path/to/approved/valkey-server \
  --report /tmp/opencode/nanfo-audit/workstream7-real-services.json

# Focused HTTP lane, same prerequisite:
poetry run python -m scripts.audit_isolated_suite \
  --redis-server /absolute/path/to/approved/valkey-server \
  --test scripts/test_audit_http_smoke.py \
  --report /tmp/opencode/nanfo-audit/workstream7-http.json
```

Remaining: execute real Redis/HTTP lane with zero skips; independently wire a
browser UI smoke with the frontend owner; retain the two contention-sensitive
deadline cases for owner review. Parent owns existing frontend/browser suites.

## Changes and ownership

- `backend/tests/unit/test_verify_measured_twin.py` distinguishes the historical
  acceptance target **0027** from repository head **0028**. It asserts every
  ancestor from both heads through0001 and preserves the0027 migration command.
- `backend/tests/integration/test_network_outbox_postgres.py`: only the spatial
  interop fixture revision changes to0028. Every fixture still executes the
  original0020 →0019 → target roundtrip. Network-owner additions live separately
  in `test_network_inventory_postgres.py` and are included in the new lane.
- `backend/app/modules/autonomy/experimental/verification.py`: localized E731
  `identity` lambda-to-def conversion only.
- `backend/scripts/audit_isolated_suite.py`: reusable disposable PostgreSQL runner,
  optional explicitly approved installed Redis executable, repeatable `--test`
  file/node selectors, bounded timeout, JSON counts and cleanup evidence.
- `backend/scripts/test_audit_isolated_suite.py`: selection, environment isolation,
  evidence accounting, missing-binary rejection, startup failure and cleanup tests.
- `backend/scripts/test_audit_role_profiles.py`: migrates the full current chain,
  creates real users/role assignments, and checks repository and backend profile
  permissions against ADR026 for Admin/Operator/Read-Only. With real Redis it also
  checks real password login, token rotation and current authoritative permissions.
  Permission mapping and authentication are not mocked. This is a backend service
  gate, **not browser→HTTP end-to-end evidence**.
- `.github/workflows/disposable-integration.yml`: runs on relevant backend,
  emulation, deployment, workflow and ADR PRs; relevant main/master pushes; and
  manual dispatch. Uses existing pinned disposable hosted-runner PostgreSQL/Redis
  services. Adds experimental DB, real-role and new owner-provided inventory,
  identity/audit, alert-scope and workflow-history regressions. A successful lane
  must have executed cases and zero skips/errors/failures. Job timeout25 minutes,
  lock timeout30 seconds, statement timeout120 seconds. No privileged lab job.
- `.github/workflows/quality.yml`: adds the isolated runner regression command.

Historical deployment release constants and global project tracking were not
edited. No commits were made and no frontend files were edited by this workstream.

## Isolation and evidence contract

Run from `backend/`. `initdb` and `postgres` must already be on PATH, as a non-root
user. Each invocation allocates a new mode0700 root under `/tmp/opencode`, uses
random loopback ports and generated credentials, and stops its exact child handles
before removing its private tree. It does not accept an external DSN, inherit test
DSNs/lab opt-ins/pytest options, install software, or invoke Docker. PostgreSQL lock
and statement timeouts also bound cross-session stalls. Pytest runs in an owned
process group with an overall timeout (default600s, CLI bound1..1200s).

`--report` requires a new file in an existing directory; results are also printed.
Counts come from actual JUnit test cases, with failed/error case names retained in
new reports. Missing JUnit on interruption/timeout is recorded as `counts: null`,
never an inferred pass. Raw private logs/JUnit/credentials are removed with the
temporary root; displayed output redacts fixture DSNs and generated secrets.
The exit code propagates pytest failure; setup/timeout/cleanup failure returns2.
A PostgreSQL-only successful invocation can return0 while its JSON status remains
`partial`, explicitly recording unexercised Redis and actual skips.

Redis is absent locally (`command -v redis-server` returned no executable). No
installation, image pull or shared Docker service was attempted. Once an installed
executable is approved, the complete local command is:

```bash
poetry run python -m scripts.audit_isolated_suite \
  --redis-server /absolute/path/to/approved/redis-server \
  --timeout 600 --report /tmp/opencode/nanfo-audit/workstream7-with-redis.json
```

That command has **not** been run locally. CI supplies its disposable Redis URLs
directly to pytest and requires zero skips.

## Exact commands and observed results

All commands below ran from `/home/DHB/Documents/NANFO/backend` unless noted.
Repeated commands are separate snapshots, not additive unique-test totals.

### Offline owned regression and lint

```bash
poetry run ruff check \
  scripts/audit_isolated_suite.py scripts/test_audit_isolated_suite.py \
  scripts/test_audit_role_profiles.py tests/unit/test_verify_measured_twin.py \
  tests/integration/test_network_outbox_postgres.py \
  app/modules/autonomy/experimental/verification.py

poetry run pytest scripts/test_audit_isolated_suite.py \
  tests/unit/test_verify_measured_twin.py tests/unit/test_experimental_lab.py \
  tests/unit/test_experimental_campaign.py -q --no-cov
```

Scoped Ruff passed. Latest combined offline run: **89 passed in10.53s**. Earlier
snapshot before another owner's additional experimental test:84 passed without
the4 runner tests. These are not full backend-suite reruns.
After adding failure-node evidence accounting, the runner-only command
`poetry run pytest scripts/test_audit_isolated_suite.py -q --no-cov` passed4 tests
in0.26s; scoped Ruff, Actionlint and repository `git diff --check` passed again.

From repository root:

```bash
/tmp/opencode/actionlint .github/workflows/disposable-integration.yml .github/workflows/quality.yml
```

Passed after replacing a YAML path alias unsupported by the installed validator.

### Focused current-schema / experimental / real-role PostgreSQL gate

```bash
poetry run python -m scripts.audit_isolated_suite \
  --test tests/integration/test_network_outbox_postgres.py \
  --test tests/integration/test_spatial_postgres.py \
  --test tests/integration/test_experimental_lab_postgres.py \
  --test scripts/test_audit_role_profiles.py \
  --report /tmp/opencode/nanfo-audit/workstream7-targeted-001.json
```

**65 passed,3 skipped in34.46s**. Both repaired spatial/inventory lock-order cases
pass. The3 skips are real-Redis login/rotation profiles. Cleanup records child
reaping, graceful stop, private-tree removal and both allocated ports closed.

### Additional PostgreSQL batch

```bash
poetry run python -m scripts.audit_isolated_suite \
  --test tests/integration/test_asset_postgres.py \
  --test tests/integration/test_report_postgres.py \
  --test tests/integration/test_telemetry_lifecycle_postgres.py \
  --test tests/integration/test_fleet_postgres.py \
  --test tests/integration/test_simulation_postgres.py \
  --test tests/integration/test_plugin_postgres.py \
  --test tests/integration/test_autonomy_postgres.py \
  --test tests/integration/test_autonomy_operator_postgres.py \
  --test tests/integration/test_autonomous_execution_postgres.py \
  --test tests/integration/test_retention_complete_postgres.py \
  --test tests/integration/test_telemetry_history_sql.py \
  --timeout 300 --report /tmp/opencode/nanfo-audit/workstream7-remaining-postgres-001.json
```

**124 passed,1 skipped in71.48s**; the skip is Report's real Redis lost-ack case.
Owned cleanup fully passed.

Final runner smoke after confining pytest temporary files to the owned root and
disabling its shared cache:

```bash
poetry run python -m scripts.audit_isolated_suite \
  --test scripts/test_audit_role_profiles.py::test_seeded_role_and_backend_profile_match_adr026 \
  --report /tmp/opencode/nanfo-audit/workstream7-runner-final.json
```

**3 passed,0 skipped in3.24s**; empty failed-case list, all cleanup fields passed.
JSON remains `partial` because real Redis was not requested. New-script Ruff and
repository whitespace checks passed again.

### Expanded default lane: failures retained as integration evidence

```bash
poetry run python -m scripts.audit_isolated_suite --timeout 300 \
  --report /tmp/opencode/nanfo-audit/workstream7-postgres-003.json
```

**231 passed,8 failed,9 skipped in207.58s**,248 collected; pytest exit1. All new
Network inventory, Identity/audit repair, Alert scope and Simulation/Intent history
cases passed. All cleanup fields passed. Nine skips:4 Intent fenced-lock cases,
1 Report Redis replay,1 login-rate-limit Redis case,3 real-role login/rotation cases.

All8 failures are in `tests/integration/test_alert_postgres.py`:

- `test_real_consumer_persisted_fixture_and_duplicate_retry`
- `test_lock_barrier_rechecks_authority_and_wall_clock[expires-detector]`
- `test_lock_barrier_rechecks_authority_and_wall_clock[expires-incident]`
- `test_lock_barrier_rechecks_authority_and_wall_clock[expires-precommit]`
- `test_lock_barrier_rechecks_authority_and_wall_clock[membership-detector]`
- `test_lock_barrier_rechecks_authority_and_wall_clock[membership-incident]`
- `test_lock_barrier_rechecks_authority_and_wall_clock[membership-precommit]`
- `test_lock_barrier_rechecks_authority_and_wall_clock[inactive_actor-precommit]`

The concrete first failure is `LockNotAvailableError` on
`SELECT organizations.org_id ... FOR UPDATE`. Its path is
`MeasuredAlertService.apply_observation → authorize_observation(fresh=True)`
which opens a second session, then Network workspace access → Organization
membership → Organization lock. Several barriers time out awaiting that fresh
authorization or the subsequent precommit point. This is a concurrent owner
integration issue, not the repaired0021 spatial fixture. The initial replay-lock
hypothesis is superseded by this organization-row-lock stack evidence. Alert and
Identity owners need to reconcile nested authority reads/lock ownership while
preserving revocation fences; no application repair was made by this workstream.

Before database lock bounds were added, the default lane was interrupted by the
shell's120s cap (`workstream7-postgres-001.json`) and by its own600s bound
(`workstream7-postgres-002.json`). A90s isolated alert run
(`workstream7-alert-001.json`) located the first stalled case. All three cleaned
their owned PostgreSQL roots/children and recorded null counts. They are incomplete
runs, not extra pass results.

## Original integration handoff (superseded where noted above)

1. Alert/Identity owners resolve the8 lock/authority regressions above, then rerun
   the full default runner. The regular CI lane deliberately retains these tests.
2. Run the Redis-enabled lane in hosted CI or with an approved installed local
   binary. Local9 skips and the3 real-role login/rotation paths remain unverified.
3. Run full backend/frontend gates on the integrated, settled worktree. Original
   audit totals3371pass/1fail/239skip and216 deployment passes are historical inputs,
   not results from this workstream. No new hosted-CI execution is claimed.
4. A real authenticated browser→FastAPI→PostgreSQL/Redis workflow smoke is still
   needed: actual issued role profiles, token refresh while editing, current tenant
   membership,21+/200+ records, mutation failure recovery, and browser page-error/
   unhandled-rejection capture. This workstream provides real backend role-profile
   validation without editing shared frontend fixtures. Coordinate any later
   browser addition as new isolated spec/config files with the frontend owner.
5. New owner PostgreSQL regression files can be run via repeated `--test` selectors;
   additions needing a new DSN prefix must extend the runner's explicit mapping and
   CI environment rather than borrowing a shared database.
