# Remaining Operator Workflows (ADR-018)

## Implemented

- Selected-probe capture with actual per-interface packet identity/timestamps,
  raw-PCAP replay, trusted canonical device binding, freshness, partial/ambiguous
  states and an ordered-hop Twin panel. Approved configuration stays separate.
- Network-allowlisted, pinned frozen-model diagnostics: explicit historical input
  selection, original restricted loader/evidence validation, probabilities/value,
  model/input/source hashes and measured inference timings. Not live actuation.
- Immutable versioned operational/training configuration with optimistic revisions,
  reasons/history and effective-vs-requested distinction. Operational settings feed
  worker gates; reward changes require retraining and never mutate frozen weights.
- Persisted timed override enrollment for an exact verified manual execution,
  expiry/restart/revocation/STOP-triggered compensation and verified restoration.
  Independent worker rather than browser timers. Superseded/uncertain state rejects.
- Return workflow rechecks restoration, revision, STOP, original approval/model
  and live provider readiness. Unavailable autonomy stays return_blocked/monitor.
- New UI panels with permissions, server-authoritative countdown/status, conflict
  handling and keyboard/mobile checks. Execution owner means approving actor,
  not necessarily the original intent requester.

## Actual Verification

Real selected probes: baseline3 hops -> rerouted5 hops -> restored3 hops for all
three probes, backed by24/36/24 per-interface sightings. Captures never substitute
planned routes for observations. Capture cancellation now services the cancel-only
mailbox and publishes no false complete evidence when interrupted.

Real timed override verifier used isolated migrated DB/API/Intent+Autonomy workers
and actual OVS lab. Six cases passed: expiry with worker kill/restart, actor
revocation, STOP during restoration, expiry during capture, STOP during capture,
and lab restart while holding. Each removed10 owned flows to0, set active=null,
and passed independent3/3 ping. During capture, receiver-side receipts appeared
within0.649s/0.486s; full backend verified restoration took roughly6-8seconds.
Artifact: `/tmp/opencode/operator-override-verification-1j3zdsiz/result.json`.
This is bounded asynchronous restoration, not instantaneous undo.

Frozen inference under actual Landlock+seccomp confinement reproduced action0,
probabilities[0.9718289375,0.0281710345], value3.2172513 and exact recorded hashes
in separate processes via authenticated HTTP. Disposable PostgreSQL and dedicated
real Redis were used. Same-UID control-file read/write and filesystem escape probes
were denied; allowed read-only model files/private scratch worked. Linux x86_64
Landlock ABI>=5 and libseccomp are required; unavailable sandbox fails closed.

Final backend tests:1,858 passed,50 opt-in skips. Added pytest pythonpath entries
so standard backend tests can import the separate emulation contract package.
Frontend465 tests and38 browser tests passed (dev and production, retries disabled),
typecheck/lint/build and unchanged bundle limits passed:408.48KiB/410.16KiB.
Edited-scope Ruff0.15.6 passed. Full backend lint is NOT certified clean: no pinned
Ruff config/version exists, and defaults expose six pre-existing E741/E402 findings
under0.15.6 (21 under AI0.12.12). Version/PATH drift is documented rather than hidden.

## Deployment Required

Apply migrations0015(configuration/overrides),0016(model diagnostics) to the intended
database after review; live verifiers migrated disposable databases only. Restart
the API after migration, then run both independent workers:

```bash
poetry run alembic -c alembic/alembic.ini upgrade head
PYTHONPATH=..:. poetry run python scripts/run_execution_worker.py
PYTHONPATH=..:. poetry run python scripts/run_autonomy_worker.py
```

Use separate terminals/services for workers. An activated AI virtualenv must not
override the backend interpreter. Override enrollment additionally needs protected
read-only lab journal access, matching binding and enabled manual lab controls.
Model diagnostics require operator registry/root/interpreter/hash settings; they
are unconfigured by default and no caller can supply an executable or model path.
Paths require the separate operator image and explicit capture, not the training
image. Exact setup:

- `backend/app/modules/autonomy/README.md`
- `backend/app/modules/autonomy/MODEL_DIAGNOSTICS.md`
- `emulation/ADR018-PROBE-PATHS.md`

## Scope Limits

Measured paths cover selected probes during bounded capture windows, not all active
application flows. Where canonical link IDs are absent the UI keeps ordered hops
rather than inventing3D arrows. Diagnostics currently replay validated historical
observations; continuous live-model observation compatibility is still an autonomy
prerequisite. Requested reward settings require retraining. Return-to-autonomy is
implemented as a guarded workflow, not a bypass for missing calibrated providers.
Production/autonomous readiness is not certified by these operator features.

The shared deployment was not silently configured/migrated and no model was
automatically promoted. Historical AI sources/images/artifacts are preserved.
Owned verification resources were cleaned up; existing databases left running.
