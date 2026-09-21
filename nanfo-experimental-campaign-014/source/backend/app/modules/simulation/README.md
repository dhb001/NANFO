# Configured Simulation (ADR-017 Step 11)

Simulation owns the pure `finite-buffer-fluid.v1` evaluator, persisted inputs,
checkpoints, lease/revision fencing and lifecycle outbox. These are operator-configured
model predictions, not observations, calibrated bounds, packet simulation, RTT,
physical safety certification or autonomy authorization. ADR016 training, AI sources,
lab runtime/images/artifacts and shared services are not involved.

## Operation

Apply `0014_modeled_simulation` after `0013` to the intended deployment database:

```bash
poetry run alembic -c alembic/alembic.ini upgrade 0014
PYTHONPATH=. poetry run python scripts/run_simulation_worker.py --batch-ticks 8
```

The worker is independent of the API and Redis event consumers. It claims one job
at a time with a 30-second PostgreSQL lease, computes 1..32 ticks (default 8) outside
the transaction, and commits with state/revision/token/unexpired-lease CAS. Pause
locks the row and revokes the lease. A losing computed batch is discarded, not
partially applied. A crashed claim becomes reclaimable after expiry. Deterministic
output excludes wall-clock completion/lease timestamps.

Lifecycle transitions and their existing `simulation.started`, `.paused`,
`.branch_created`, `.completed`, `.cancelled` envelopes are committed atomically to
`simulation_outbox`. Publication retries the identical event ID, timestamp,
correlation ID and payload. Per-simulation revision ordering is preserved, including
with multiple publishers. Delivery is at least once: a lost Redis acknowledgement
can duplicate an envelope. No exactly-once claim. Redis failure does not block
numerical evaluation. HTTP `queue_status=outbox_pending` describes durable enqueue,
not Redis delivery or a successful risk gate; this field is not a delivery receipt.

The existing started-event consumer ignores positively configured records. Legacy
starts/resumes without configuration keep unavailable/cancelled/blocked behavior;
historical unversioned completion metrics remain null and unverified.

## Exact Request

No routes were added. Existing `POST /api/v1/simulations/start` accepts:

```json
{
  "network_id": "00000000-0000-4000-8000-000000000001",
  "scenario_name": "Finite buffer bottleneck",
  "scenario_config": {
    "version": 1,
    "seed": 7,
    "tick_ms": 100,
    "duration_ticks": 10,
    "links": [{
      "link_id": "ab", "source": "a", "target": "b",
      "capacity_mbps": 1, "buffer_bytes": 25000,
      "delay_ms": 0, "initial_queue_bytes": 0
    }],
    "flows": [{
      "flow_id": "f", "source": "a", "target": "b",
      "path": ["ab"], "demand_mbps": [2]
    }],
    "action_binding": null,
    "limits": {"max_loss_pct": 100, "max_latency_ms": 10000, "min_throughput_mbps": 0.1}
  }
}
```

Replace the network UUID with an active network accessible to the current actor.
All configuration fields shown are required; unknown fields are rejected. Optional
`action_binding` value is null or `{intent_id:UUID,plan_sha256:64-lowercase-hex,
network_state_sha256:64-lowercase-hex}`. The field itself is required in configuration.

IDs are configured graph strings matching `[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}`,
**not required inventory UUIDs**, discovered topology or asserted inventory ownership.
Network/parent tenant authorization remains mandatory. Every path references declared
links, is directed/connected, has distinct visited nodes and ends at its declared target.

Bounds: 128 nodes, 128 links, 64 flows, 1..1000 ticks, 1..1000 ms/tick;
`duration_ticks * (links + flows + sum(path lengths)) <= 16384`.
Seed is integer 0..2^63-1, recorded without hidden random demand. Rates are finite
0..1,000,000 Mbps (capacity strictly positive); buffers/initial queues 0..10^12 bytes;
initial queue cannot exceed buffer; delay 0..60,000 ms. Demand is singleton or exactly
duration length. Limits: loss 0..100 percent, latency 0..10^9 ms, throughput 0..10^6 Mbps.
These structural work bounds also bound retained histories/pipeline entries; they are
not a CPU-instruction count or throughput/SLA guarantee.

Resume: the existing start request includes `simulation_id`, original `network_id`
and a scenario name. Draft/paused/queued modeled records resume from the checkpoint.
Omit `scenario_config` or supply the identical canonical configuration; changing it
returns 409. Existing pause takes `{simulation_id}`.

Branch: `{parent_simulation_id,scenario_name,scenario_config?}` creates draft.
Omitted/identical configuration deep-copies compatible checkpoint/input, including
completed checkpoints. Completed-checkpoint copies retain the original completion/expiry
when finalized; branching cannot renew stale evidence without recomputation from tick 0.
An override restarts at tick 0 and rebinds the full input hash, including
objective/action-binding changes. It does not claim to replay a changed
model from an old checkpoint. Audit fields explain `checkpoint_copied` and
`input_override_restarted`. Use existing start to queue the draft.

## Frontend Interface

Responses retain `success/data/meta/errors` and existing status codes. The API's
OpenAPI schema is the machine-readable source; scenario errors use the existing
validation-error envelope. No new websocket channels/events.

`GET /simulations/{id}` adds these `data` fields:

| Field | Type / Meaning |
| --- | --- |
| `scenario_config` | Exact canonical input object or null for legacy |
| `input_sha256`, `checkpoint_sha256` | Digest string or null |
| `revision` | Persisted integer lifecycle/batch revision |
| `progress` | `{tick,duration_ticks}` or null |
| `completed_at`, `evidence_expires_at` | UTC ISO string or null |
| `scene_object_id` | `simulation:<simulation_id>` for modeled runs |
| `validation.evaluator_status` | `configured_model`, not a measured-provider assertion |
| `risk_gate` | `required` while awaiting evaluation; completed `passed` or `blocked` |

`run_output` is populated after a worker batch; before that, legacy-compatible
`latency_ms/loss_pct/throughput_mbps` are null. Modeled output contains:

- `model_version`, `source="operator_configured_model"`, `physical_safety_authorized=false`.
- `input_sha256`, `workload_sha256`, `checkpoint_sha256`, `output_sha256`.
- `tick`, `duration_ticks`, `elapsed_ms`, `latency_definition`.
- `offered_bytes`, `delivered_bytes`, `dropped_bytes`, `queued_bytes`, `inflight_bytes`.
- `delivered_residence_byte_ms`, `loss_pct`, `delivery_ratio`, `throughput_mbps`, `latency_ms`.
- `objective_checks={max_loss_pct:boolean,max_latency_ms:boolean,min_throughput_mbps:boolean}`, `risk_gate`.
- `flows:Record<flow_id,metrics>` with the same byte/latency/loss/delivery/goodput metrics.
- `initial_background:Record<link_id,{initial_bytes,queued_bytes,inflight_bytes,delivered_bytes}>`.
- `trace:Array<{tick,elapsed_ms,links,flows}>`, one entry per committed modeled tick.
- `trace[].links[link_id]={served_bytes,queued_bytes,utilization,background_queued_bytes,background_served_bytes,flows}`.
- `trace[].links[link_id].flows[flow_id]={arrived_bytes,dropped_bytes,served_bytes,queued_bytes}`.
- `trace[].flows[flow_id]` contains cumulative flow metrics at that tick boundary.

`GET /simulations/{id}/compare/{baseline}` adds `compatible:boolean`,
`comparison_reason:string|null`, `simulation_trace:trace|null`, `baseline_trace:trace|null`.
Comparison requires two verified completed outputs in the same network with identical
workload hash and elapsed horizon. Workload covers seed, tick/horizon, flow IDs/endpoints
and expanded demand schedules, but not routes, capacities, objectives or action binding.
Delta is candidate minus baseline. Absent/incompatible metrics and traces are null,
never zero-filled; compatible loss/throughput can legitimately be zero.

Completion and pass are independent. Use `state=completed` to show finished computation,
and separately show objective pass/failure. Stale evidence may still be displayed as
historical model output, but cannot be used for execution. Reconcile lifecycle deltas
with scoped REST detail; existing WS projection does not expose every REST field.

## Execution Binding

Existing `POST /intents/execute` accepts optional `simulation_id`. Omission preserves
existing manual/executor behavior. A supplied reference is checked **before idempotent
execution replay**, against the Simulation owning service, never cross-module SQL.
Reference validation requires active actor/workspace/network authorization, matching
network, completed positively versioned/hash-verified output, all objectives passing,
and exact intent UUID/normalized-plan/current-network digests. Evidence expires at
completion + 300 seconds; the server also enforces maximum age independently of the
stored expiry. Invalid/missing/stale/mismatched references return 403/409, not a fallback.

The accepted `IntentExecution.simulation_evidence` is an optional immutable JSONB
column in unreleased migration0014. PostgreSQL rejects subsequent changes, including
clearing a bound reference or adding one to an already accepted unbound execution.
It stores simulation/intent/workspace/network IDs, plan/current-network/input/checkpoint/
output SHA256 digests, original completion/expiry, source, false physical-safety flag,
and `validation_scope="configured_model_admission_only"`. Replays compare this exact
evidence as well as request identity; changing or dropping the optional reference
does not bypass idempotency checks.

Before first publication the Intent worker obtains a fresh `prepare_plan` snapshot,
revalidates the reference through the Simulation service with the Simulation row locked,
and compares every returned evidence field against the accepted immutable record.
Changed sequence/state/output, expiry, tenant/authority or plan blocks publication.
The existing dispatch expiry is capped by evidence expiry and the independent
300-second maximum age; the filesystem publication callback rechecks this bound along
with lease authority after scheduling delays. Lab command fields are unchanged.
Cancellation ignores the optional reference and its expiry, retaining existing
independent cancellation authorization and recovery. Previously dispatched recovery
does not issue a second execute, even after model evidence expires.

Plan hash is `intent.lab.digest(plan.model_dump(mode="json"))` after `prepare_plan`
normalizes and validates the actual intended plan. Network hash is computed by the
single owning helper `simulation.modeled.current_network_state_hash(binding,snapshot)`:

1. Obtain **the current actual** binding/snapshot returned by `prepare_plan`, which
   verifies configured authority, trusted inventory/topology and snapshot freshness.
2. Serialize snapshot in JSON mode; remove **only top-level `observed_at`**. Keep
   `sequence`, `run_id`, all nested observation timestamps, counters, durations,
   queues, probes and graph attributes. Advancing measured samples normally changes
   this exact hash. No stale client-supplied hash substitutes for this snapshot.
3. Sort top-level arrays of objects by their canonical SHA256; do not sort path arrays
   or recursively discard timestamps. Serialize the binding unchanged in JSON mode.
4. Hash `{version:1,binding:<binding>,snapshot:<snapshot>}` using sorted JSON object
   keys, separators `(',',':')`, UTF-8, `allow_nan=False` and SHA256.

Evidence producers must use the same helper with the same approved actual snapshot;
there is no new preparation endpoint in this slice. The verifier's direct service
binding checks use declared test hashes, not fabricated live observations. Unit tests
separately prove acceptance hashes its current `prepare_plan` result. No live lab
acceptance or physical verification is claimed by this non-actuating gate.

An action-binding hash declares what the operator configured for analysis; it does
not prove that the configured graph implements that action or equals actual inventory.
Model pass cannot bypass manual approval, production prerequisites, calibrated bounds,
provider qualification or autonomy. Production/demo execute requests carrying a
reference return 409 when a current prepared plan cannot be established. Cancellation
does not depend on establishing a new model/plan approval.

## Typed Response Additions

Start and branch `validation` now retain `source` (literal `operator_configured_model`
or `unavailable`) and `physical_safety_authorized` (literal false). Existing field names
and envelopes are unchanged. `run_output` is an explicit `ModeledOutput | UnavailableOutput`
schema, not a free-form dict; trace/link/flow/background/objective fields are typed,
finite and reject unknown fields. Malformed versioned output cannot fall through as
legacy. Missing legacy metrics serialize to null, never invented zero values. Compare
traces use the same `SimulationTrace` schema. OpenAPI exposes the exact nested types.

Intent `execution_provenance.approved_plan` is a deep copy of the persisted command's
`plan` only when its canonical digest equals `command.plan_hash`; otherwise it is null.
Editable intent payload is never substituted. Corrupt commands fail before dispatch,
or remain uncertain on already-dispatched recovery, rather than claiming approval.
This plan is configuration intent, not evidence of observed packet traversal.

## Verification

```bash
poetry run pytest tests/unit/test_simulation_evaluator.py tests/unit/test_simulation_modeled.py tests/unit/test_simulation_execution_gate.py -q --no-cov
PYTHONPATH=. poetry run python scripts/verify_modeled_simulation.py --live
```

The live verifier creates memory/CPU-limited PostgreSQL/Redis/Neo4j containers on
private loopback ports, migrates only its disposable DB, starts authenticated API and
independent simulation worker, and cleans up exact owned IDs. It does not start a lab,
dispatch a command, or restart/migrate shared services. Detailed artifact:
`/tmp/opencode/simulation-verification-zz36fz_b/result.json` (review-fix passed run,
19 Simulation/dispatch PostgreSQL tests, four existing Intent PostgreSQL/Redis tests,
HTTP/worker checks and cleanup passed). Final full backend regression:
**1,757 passed, 35 opt-in skipped**; the 23 PostgreSQL/Redis tests above were separately
exercised by this verifier. Scoped Ruff and whitespace gates passed.
The first attempt exposed a verifier startup race with Neo4j readiness; explicit
readiness waiting fixed it without changing application/shared-service startup.

Coverage: analytic finite-buffer loss, shared proportional service/background,
multi-hop propagation/residence, fractional-byte conservation, replay/batch equivalence,
input corruption, branch reset/copy, failed-objective completion, current state/plan
binding, manual/production non-bypass, tenant denial, real PostgreSQL claim competition,
lease expiry, paused-worker CAS races, terminal atomicity and stable outbox retries.
The dispatch regressions exercise real acceptance, immutable DB evidence and worker
reconciliation with controlled trusted-observation/auth test doubles. Advancing snapshot
sequence, expiring/mutating model evidence, losing the worker lease or corrupting the
approved command prevents first publication. A delayed callback refuses publication
after expiry. A positive test reaches a mocked mailbox, not an actual lab. Cancellation
after evidence expiry and existing post-dispatch recovery remain independent.

Remaining scope: packet/protocol/RF dynamics, actual packet traversal, calibrated
physical bounds, autonomous provider installation and frontend Step 12 acceptance.
