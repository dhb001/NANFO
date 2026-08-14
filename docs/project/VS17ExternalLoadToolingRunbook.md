# VS17 External Load-Tooling Runbook

## Purpose
Define deterministic execution and recovery guidance for the VS17 external load-tooling baseline while preserving existing API/event/channel/schema contracts.

## Scope
- External tooling path: `k6` telemetry health load profile with Docker fallback.
- Evidence flow: deterministic synthetic fixture pump + k6 run summary + telemetry counter delta artifact.
- Artifact path baseline: `backend/artifacts/load-testing/vs17/`.
- This runbook governs validation tooling only and does not redefine runtime product contracts.

## Preconditions
1. Backend dependencies are running (PostgreSQL, Redis, Neo4j) and API service is reachable.
2. Telemetry consumer loop is active so `stream:telemetry` events are processed.
3. Use a profile from the approved set:
   - `local-smoke`
   - `local-burst`
   - `staging-baseline`

## Execution Command

From `backend/`:

```bash
poetry run python scripts/run_vs17_external_load.py --profile local-smoke --base-url http://127.0.0.1:8000
```

Optional authenticated mode:

```bash
poetry run python scripts/run_vs17_external_load.py --profile local-smoke --base-url http://127.0.0.1:8000 --auth-token "$NANFO_AUTH_TOKEN"
```

Optional fixture-only mode (skip external k6 command):

```bash
poetry run python scripts/run_vs17_external_load.py --profile local-smoke --skip-k6
```

## Expected Outputs
- Script prints:
  - Artifact path
  - Run status (`success` or `failed`)
  - Counter deltas for `ingested`, `persisted`, `fanout`, `dropped`
- Evidence JSON includes:
  - Profile and runner metadata
  - k6 command and summary metrics (`http_req_failed_rate`, `http_req_duration_p95_ms`, `http_reqs_count`)
  - Fixture publish counts
  - Counter `before`/`after`/`delta`
  - Acceptance check booleans

If `backend/artifacts/load-testing/vs17/` is not writable, the runner falls back to:

- `/tmp/opencode/vs17-artifacts-<run_id>/`

## Rollback / Failure Handling

### Failure: no k6 runner available
- Signal: script fails with runner-resolution error.
- Action:
  1. Ensure host `k6` is installed, or
  2. Ensure Docker is installed/running for fallback mode.
- Recovery: rerun the same command; no product rollback needed.

### Failure: API unreachable or repeated 5xx
- Signal: k6 exit code non-zero and failed status checks.
- Action:
  1. Verify backend service process and `/health` endpoint.
  2. Verify `--base-url` target.
  3. Confirm dependencies via `../scripts/dev-start.sh` (from `backend/`) or `scripts/dev-start.sh` (from repo root).
- Recovery: rerun after service recovery; artifact history is append-only.

### Failure: fixture publish incomplete
- Signal: evidence `failure_reason` includes `fixture_publish_incomplete`.
- Action:
  1. Check Redis connectivity and event publish warnings.
  2. Re-run the command to confirm determinism.
  3. If repeated, inspect `telemetry_event_published` and publish-failure logs.
- Recovery: no schema/data rollback required; failed run is evidence-only.

### Failure: telemetry counter deltas missing expected signals
- Signal: `persist_signal_present` or `fanout_signal_present` false.
- Action:
  1. Verify consumer loop health and stream group readiness.
  2. Check telemetry consumer warnings and WS fanout warnings.
  3. Re-run with `local-smoke` profile for quick isolation.
- Recovery: fix infra/runtime issue, rerun command, keep prior failed artifact for audit trail.

### Failure: artifact directory permission denied
- Signal: warning that preferred output directory is not writable, or explicit write failure.
- Action:
  1. Use default fallback under `/tmp/opencode` for immediate rerun.
  2. Repair ownership/permissions on `backend/artifacts/load-testing/vs17` when persistent local artifact storage is required.
- Recovery: rerun after permission fix; evidence artifacts remain append-only by `run_id`.

## Notes
- Preserve fail-open behavior: tooling failures must not alter API availability semantics.
- Do not introduce new REST/WebSocket/event/channel/schema contracts in VS17 tooling runs.
- Keep artifacts as immutable evidence for VS18 threshold-hardening inputs.
