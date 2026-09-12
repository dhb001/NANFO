# Steps 9-10: Safety and Governed Autonomy Foundation

## Status

Implemented and tested the fail-closed foundation, NOT full neuro-adaptive safety
or live autonomous intervention. Those acceptance gates remain OPEN. The deployed
model/inference/calibration/executor providers explicitly report unavailable rather
than fabricate compatible observations, safety confidence or manual approval.

## Delivered

- Strict one-step queue-envelope/Lyapunov drift evaluator with exact arithmetic,
  timestamp/expiry, input/action/calibration binding, connectivity/capacity checks,
  dwell/rate limits, deterministic admissible projection and explicit no-dispatch.
- Conditional proof in `docs/architecture/SafetyModel.md`; not a continuous-time
  neural adaptation law or global queue-stability claim. Counterfactual bounds
  require actual calibration; ordinary port utilization is insufficient.
- Autonomy-owned controls/decisions (migration 0013), scoped API, independent worker,
  mode/approval leases, current authorization, immutable certificate handoff and
  exact-owned execution recovery interfaces. Online learning remains disabled.
- Monitor exposes real telemetry availability. Recommendation records blockers
  while inference is unavailable. Autonomous PUT returns 409 with unchanged mode.
- Durable emergency latch, revision-bound mode changes, certificate-expiry rechecks
  and separate server-owned recovery boundary; unavailable recovery stays blocked.
- Operator route `/ops/autonomy`: provider readiness, gate reasons, decision history,
  conditional certificate fields, explicit mode requests and acknowledged stop.

## Training Outcome

Background run002 stopped cleanly after about 49 minutes under its predefined
low-quality rule: 144 transitions/3 rounds. Best validation mean 0.4915357015;
better constant 0.4909348651; heuristic 0.5375797398. Required qualification mean is
strictly greater than 0.5109348651. The best pointer is retained but UNQUALIFIED.
No new training or model promotion was launched by this change.

## Verified Evidence

- Backend default suite: 1,601 passed / 14 opt-in skips; Ruff app/tests/scripts passed.
- Six new real PostgreSQL lock/transaction/revision tests separately passed.
- Disposable real HTTP and independent-worker verifier:
  `/tmp/opencode/autonomy-verification-4c_q51nq/result.json`.
  Monitor, blocked recommendation, autonomous rejection, stale PUT after STOP and
  durable latch passed; ZERO execution jobs, as required for unqualified deployment.
- Frontend lint/typecheck: passed; 313 tests across 50 files passed.
- Browser: 31/31 passed with retries disabled; production-browser suite separately
  passed, including narrow/mobile view. Browser APIs are mocked, not actuation proof.
- Production build/performance passed unchanged bounds: 404.18 KiB total JS gzip.
  Existing large Three.js and mixed session import warnings remain.
- Shared databases were not migrated. No training/lab owner was started or changed.

## Use

Review/apply migration 0013 to the intended deployment before starting the new API
or worker (verification migrated disposable databases only). From `backend/`:

```bash
poetry run alembic -c alembic/alembic.ini upgrade head
PYTHONPATH=. poetry run python scripts/run_autonomy_worker.py
```

The worker is not automatically started by FastAPI. Provider installation remains
fail-closed; running the worker cannot enable automatic network changes. Full API
schema and behavior: `backend/app/modules/autonomy/README.md`, ADR-012 and feature PRD.

## Remaining Gates

1. Qualified model with beneficial validation behavior, not a mutable best pointer.
2. Compatible continuous observation/inference contract; current experiment PPO
   cannot consume ordinary ADR-009 telemetry without fabricating missing UDP/history.
3. Physically calibrated, action-conditioned arrival/service/error bounds.
4. Actual server-authorized durable executor/recovery integration with receiver-side
   stop, expiry, authorization and certificate checks; no manual-approval bypass.
5. Live closed-loop safety interventions, measured action outcomes and evidence that
   any claimed proactive response precedes the defined congestion condition.

Tests using injected qualified providers exercise orchestration only. They do not
close any missing physical/model/provider gate. Production control stays disabled.
