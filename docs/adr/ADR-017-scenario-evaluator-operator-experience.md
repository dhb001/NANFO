# ADR-017: Scenario Evaluator and Operator Experience

- Status: Accepted for user-requested completion-plan Steps 11 and 12
- Date: 2026-09-10

## Boundaries

Preserve running ADR016 training, frozen AI/lab sources, images and datasets.
No competing Mininet environment, training changes, model promotion or autonomous
provider installation. Implement a pure bounded deterministic finite-buffer fluid
network evaluator under Simulation ownership and expose its results honestly as
configured model predictions, never measured traffic or calibrated safety bounds.
Production remains fail-closed. No new public REST route or websocket channel.

## Scenario Contract

Extend existing start/branch requests with optional `scenario_config`, strictly
validated version1: `{version:1,seed:int,tick_ms:int,duration_ticks:int,
links:[{link_id,source,target,capacity_mbps,buffer_bytes,delay_ms,initial_queue_bytes}],
flows:[{flow_id,source,target,path:[link_id,...],demand_mbps:[number,...]}],
action_binding:null|{intent_id:UUID,plan_sha256:sha256,network_state_sha256:sha256},
limits:{max_loss_pct,max_latency_ms,min_throughput_mbps}}`.
Bound nodes/links/flows/ticks/total work and finite values. Each flow path is a
directed connected acyclic path, demand schedule either constant singleton or exact
duration. Reject impossible/duplicate IDs and invalid queues. Seed recorded for
reproducibility; v1 has no random hidden demand. Capacities/input topology are
explicit operator configuration, not guessed from graph metadata.

Use byte-conserving per-flow queues per directed egress, deterministic shared
service allocation, explicit finite buffers and propagation/tick ordering.
Offered=delivered+dropped+queued+inflight (within defined numeric tolerance).
Output includes model/version/input/checkpoint/output hashes, elapsed modeled
time, per-link/flow histories, loss, delivery ratio, goodput and latency definition.
Document queue delay approximation and coarse tick limitations. The pure evaluator
supports bounded checkpoint advancement and analytic conservation regression tests.

## Lifecycle and Persistence

Simulation owns new input/checkpoint/revision/lease fields and scoped outbox in
migration0014 (after0013). A dedicated bounded I/O/evaluator worker is approved as
an exception to generic Celery guidance; it processes small bounded tick batches
outside HTTP/shared websocket consumers, with durable CAS state and outbox.
Start with supplied configuration persists queued; omitted configuration retains
legacy unavailable behavior, never fabricates a configured topology. Resume through
existing start simulation_id preserves inputs/checkpoint. Branch copies checkpoint
and compatible inputs; input modifications explicitly restart from tick0. Pause
commits safely between batches, resume produces equivalent deterministic output.
Legacy completed records remain unverified unless positively versioned model output.

Completion means model computation finished, separate from gate pass/fail. Compare
compatible modeled runs only (common workload/time basis); no zero-fill for absent
or incompatible metrics. Evidence binds exact configured action/network-state hashes,
expires under server policy, and never grants physical production authorization.
If execution references a simulation, service-owned validation checks tenant,
completed status, modeled risk pass, input/plan/network digest match and expiry.
Failed/stale/mismatched references block execution; model pass alone cannot bypass
existing manual approval or missing calibrated production/autonomy prerequisites.
Extend execute request with optional `simulation_id` for this explicit check.

## Operator Improvements

- Existing telemetry page gains accessible time-series charts with units, port/
  peer/run isolation, stale/unavailable gaps, bounded pagination and table fallback.
- Simulation page accepts configured scenarios, controls real lifecycle, shows
  model assumptions, comparison curves and action-bound evidence/expiry.
- Intent detail adds `execution_provenance.approved_plan` from persisted command,
  retaining actual hashes and readback scope. Display configuration-verified paths
  only; observed packet traversal remains unavailable without matching live proof.
  Hostname paths must not be guessed into canonical device IDs when ambiguous.
- Authenticated websocket subscribed acknowledgments and backpressure trigger
  bounded scoped REST reconciliation. Apply timestamps/run identity, tombstones,
  stale-data indicators and per-simulation scene IDs; do not lose auth/revocation
  protections or invent full-snapshot websocket events.
- Device-group save defaults non-destructive upsert. Model reload validates bytes/
  hash/size/mapping via existing API and revokes Blob URLs on scope/unmount. Do not
  overwrite unsaved local imports without explicit operator action.
- Preserve existing manual action/restore and Autonomy stop/mode controls. No UI
  option may claim a model/safety/provider is ready when unavailable. Reward/model
  parameters cannot be edited as if live trained-model updates are supported.

## Closure

Require deterministic replay, finite-buffer conservation, bottleneck/route effects,
pause/resume equivalence, branch/input semantics, outbox/recovery and concurrent
pause tests, simulation-bound execution rejection, tenant denial, chart identity/
gaps, reconnect deletion and lifecycle reconciliation, safe group/model persistence,
mobile/keyboard usability and full frontend/backend gates. Use isolated disposable
database tests without restarting shared services or disturbing active training.
Document remaining measured-path/model calibration/full operator scope honestly.
