# Steps 11-12: Configured Evaluation and Operator Experience

## Delivered Scope

ADR-017 replaces the no-evaluator path for explicitly configured scenarios with
a deterministic finite-buffer fluid model. No active training source/image or
dataset was modified, and no competing lab or model training was started.

- Strict versioned scenario input: directed links, capacities, buffers, delay,
  flows/routes, explicit demand schedule, timestep/horizon and objective limits.
- Per-flow proportional queues, propagation and residence-weighted model latency;
  each checkpoint verifies offered=delivered+dropped+queued+inflight. Initial
  background is separately accounted. Predictions are not measured RTT/traffic.
- Independent bounded simulation worker, checkpoint leases/CAS, pause/resume
  equivalence, branch copy/reset semantics, and stable lifecycle outbox events.
- Completed calculation can fail its objectives. Historical unavailable outputs
  stay unavailable. Compatible completed scenarios compare actual modeled deltas.
- Action-bound evidence stores exact plan/network/input/output/checkpoint identity
  and expiry, persists with an execution and is revalidated before first dispatch.
  Model-only provenance survives response serialization as literal physical false.
- Simulation scenario editor, lifecycle controls, modeled charts, comparisons,
  evidence hashes/expiry and optional explicit execution simulation reference.
- Accessible telemetry charts/table fallbacks with units, scope/port/peer/run
  identity, gaps, freshness and bounded pagination. Raw flow counters are explicitly
  snapshot-local, not stitched into a false continuous flow series.
- Approved path panel reads the hash-matching persisted execution command only,
  labels configuration readback/reachability and does not claim packet traversal.
- Authenticated reconnect/backpressure triggers bounded scoped REST reconciliation,
  including up to20 known lifecycle overlays without active detail queries; epoch/
  timestamp/revision guards prevent stale resurrection and cross-context writes.
- Non-destructive device-group upserts, validated explicit persisted model restore,
  unsaved-import confirmation and URL cleanup on replacement/scope/unmount.
- Mobile/keyboard regressions and CSS motion preserving entry/exit and reduced-
  motion support; removed redundant animation dependency to retain bundle budgets.

## Verification

- Full backend:1,757 passed,35 opt-in skips; Ruff app/tests/scripts passed.
- Disposable real database tests:19 Simulation/dispatch tests and4 Intent tests
  separately passed. Authenticated HTTP plus independent worker verified deterministic
  replay, failed-objective completion, comparisons, scope/expiry/binding and cleanup.
  Artifact:`/tmp/opencode/simulation-verification-zz36fz_b/result.json`.
- Example analytic bottleneck:2Mbps offered to1Mbps capacity over1 modeled second
  delivered125000 bytes, dropped112500, retained12500 queued; model latency180.0195ms.
  This is a model result with declared tick/buffer assumptions, not live network data.
- Frontend:369 unit/component tests, strict typecheck/lint passed;37 browser tests
  without retries passed on development and separately on minified production.
- Build/performance:395.25KiB total JS gzip versus unchanged410.16KiB limit; all
  bounds passed. Existing Three.js chunk/session-import warnings remain.
- Final read-only review found no new high-confidence serious bugs in corrected
  scope; tests are not proof of continuous physical safety or all extreme workloads.

## Running

Apply migration0014 to the intended application deployment after review. Verification
upgraded disposable databases only; shared database/schema was not migrated here.
From backend:

```bash
poetry run alembic -c alembic/alembic.ini upgrade head
PYTHONPATH=. poetry run python scripts/run_simulation_worker.py --batch-ticks 8
```

Open Simulation in the operator UI and use the explicitly configured example or
provide validated inputs. Resume uses the same simulation ID. An unchanged branch
copies its checkpoint; changing inputs restarts at tick0. Existing completed evidence
does not gain a fresh expiry merely by being branched.

## Honest Remaining Step 12 Limits

Actual live packet-path visualization, end-to-end model inference diagnostics and
live policy/reward tuning are not implemented by presenting configured paths or
model parameters. The current Autonomy mode/gate UI and manual restore/cancel
remain authoritative; automatic return to autonomy cannot be enabled while providers
are unqualified. Dedicated time-limited manual-override lifecycle and authoritative
model-provider integration remain open. No fake confidence, automatic model update
or calibrated safety assertion was added. Step12 is therefore improved substantially,
not certified complete across every originally listed feature.

Model evidence binds a recently checked exact snapshot, not unchanged physical
state forever. Its configured graph/action correspondence is operator-declared.
Finite-buffer mixed-fluid/coarse ticks do not simulate packets, TCP/RF dynamics,
controller convergence or calibrated production risk. Simulation pass does not
authorize production/autonomy or bypass manual approval. Invalid action evidence
provided to execution fails closed; omission preserves existing approved manual-lab
semantics rather than making this uncalibrated model a universal production gate.

## Training Status (Separate Workstream)

During final verification ADR016 was observed inactive/success:384 fresh transitions,
12 updates, no cleanup error. It stopped because modeled remaining work plus final
reserve exceeded the remaining cap; no validation/promotion is claimed from that
checkpoint. The frozen training files and artifacts were not changed or restarted.
Status remains `ai-engine/artifacts/adr016-001/status.json`.
