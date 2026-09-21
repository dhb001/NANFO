# NANFO Backend

This file satisfies Poetry package metadata (`pyproject.toml` uses `readme = "README.md"`).

For full project setup and local run instructions, use the repository root `README.md`.

## ADR020 Readiness

`GET /health` is unchanged liveness (`200 {"status":"ok"}`). `GET /ready`
is an unauthenticated, read-only operational probe, not an authorization bypass
for application endpoints. It returns 200 only when all required checks pass,
otherwise 503. Both use the canonical `success`, `data`, `meta`, `errors`
envelope on `/ready`; `data` contains `ready`, named `checks`, and `capabilities`.
Failures use `SERVICE_UNAVAILABLE` with a fixed message, never exceptions,
credentials, connection addresses, lease tokens or stack traces. Responses are
`Cache-Control: no-store`.

Required checks:

- `postgres`: real `SELECT 1`, including connection acquisition.
- `schema`: exactly migration `0019` in `alembic_version`; missing tables,
  old/new/multiple heads fail closed. No migrations are run by a probe.
- `redis`: real `PING`.
- `neo4j`: acquire an actual session, execute `RETURN 1 AS ready`, consume and
  verify the single record. Merely constructing a lazy driver is insufficient.
- `api_lease`: local lease/task health and Redis `GET` ownership match; never
  renew, acquire or release a lease from readiness.
- `api_consumers`: every expected stream consumer task exists and is not done.
  This is task availability, not a claim about queue age or delivery success.
- `telemetry`: required when an adapter is configured or execution mode is
  explicitly `emulation`. Missing/failed collector, stopped task or exhausted
  polling retries degrade readiness. Unconfigured emulation fails closed.

Each dependency check has a two-second deadline, including connection/query
work. PostgreSQL/schema share one deadline; datastore probes run concurrently,
followed by the bounded lease verification. No job is claimed or processed.
Existing mandatory API startup fencing remains unchanged.

Optional telemetry in demo/production with the default stub is explicitly
`unavailable`, not a required failure. `model_inference` and
`autonomous_control` remain `unavailable`: packaging/worker liveness does not
install or qualify those providers or enable physical control.

## Worker Healthcheck

From the backend directory, deployment's exact command (example report worker):

```sh
PYTHONPATH=. python scripts/check_worker_health.py --worker report
```

Local Poetry equivalent, without using an inherited/frozen virtual environment:

```sh
env -u VIRTUAL_ENV PYTHONPATH=. poetry run python scripts/check_worker_health.py --worker report
```

Accepted worker names: `simulation`, `report`, `alert`, `execution`, `autonomy`.
Output is one sanitized JSON object with `ready` and named `checks`; exit 0
means healthy, exit 1 means unavailable. The probe uses PostgreSQL `SELECT 1`,
schema `0019`, Redis `PING`, and all that worker's heartbeat files. It does not
import worker implementations, execute jobs, touch Neo4j, or mutate stores.

Set **the same** `WORKER_HEARTBEAT_PATH` in the worker and healthcheck environment
to a private file prefix in an existing writable deployment tmpfs, for example
`/run/nanfo/worker`. Use a separate prefix or separate mount namespace per worker
process. No directory is created automatically. The default is an empty string:
local workers write nothing and do not fail startup for lack of `/run` access;
a healthcheck without a configured heartbeat correctly fails unavailable.

Each actual loop atomically replaces its own `0600` file after a successfully
returned bounded iteration, including a successful empty poll. Failed,
cancelled or timed-out calls do not refresh it; sleep is outside the iteration.
No detached timer can keep a stalled worker healthy. Files contain only PID,
Linux process start identity and monotonic progress time. The probe rejects
dead/reused PIDs, malformed/future/stale records and missing loop files.

| Worker | Suffixes appended to the configured prefix |
| --- | --- |
| simulation | `.simulation`, `.outbox` |
| report | `.report`, `.outbox` |
| alert | `.outbox` |
| execution | `.execution`, `.outbox` |
| autonomy | `.cycles`, `.overrides` |

Defaults: `WORKER_ITERATION_TIMEOUT_SECONDS=330` (maximum 600),
`WORKER_HEARTBEAT_MAX_AGE_SECONDS=360` (maximum 900). Configure freshness above
the iteration deadline plus polling/healthcheck scheduling margin. A worker
starting its first long operation is not healthy until its first completion;
allow an appropriate supervisor start period. Existing inner job deadlines,
lease fencing, uncertain-state recovery and provider safety gates still apply.
Healthy progress means the loop returned, not that a domain job succeeded or
that an unresolved physical operation is safe to replay.

## DSN And Quality Gates

PostgreSQL user/password/database and Redis password are URI-component encoded
once with `urllib.parse.quote(..., safe="")`. Empty passwords are preserved;
reserved delimiters, literal percent escapes and password newlines round-trip
without altering the target host. Host delimiters/whitespace are rejected.
Alembic escapes `%` as `%%` only when calling `set_main_option`, so subsequent
configuration reads restore the ordinary encoded DSN. Settings repr excludes
passwords, JWT secret and computed secret DSNs; never log/model-dump settings.

Ruff is pinned to `0.15.6` in the backend dev dependency group. Deployment owns
the coordinated lock refresh/install. No backend packages belong in the frozen
AI runtime. Backend gates, from this directory:

```sh
env -u VIRTUAL_ENV poetry run ruff check app tests scripts --no-cache
env -u VIRTUAL_ENV poetry run pytest tests -q --no-cov -p no:cacheprovider
```

Opt-in infrastructure skips are not live fault/restore certification. Deploy
builds, isolated boot/restore verification, manifests and operational recovery
remain the separate deployment/backup workstream under ADR020.

Backend verification (2026-09-12): full suite **2,094 passed, 89 opt-in skips**;
Ruff `0.15.6` full `app tests scripts` gate and `git diff --check` passed.
`poetry check --lock` remains pending the deployment-owned lock refresh for the
new exact Ruff pin; no other dependency changes were made by this workstream.
