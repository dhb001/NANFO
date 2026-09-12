# ADR-011: Measured Routing Environment and Actor-Critic Training

- Status: Accepted for user-requested completion-plan Steps 7 and 8
- Date: 2026-09-09

## Boundary

Add a standalone `ai-engine/` Python package with Gymnasium/PyTorch CPU PPO and a
trusted operator-only local experiment transport in `emulation/`. No public API,
websocket, production inference, or autonomous backend worker is added. This is a
bounded single DRL routing experiment, not the full multi-agent AIOS. Step 9
stability filtering and Step 10 governed autonomy remain separate. Operators
explicitly opt into the isolated experiment; it cannot run with manual mailbox
control or another lab owner. Never remove a live journal to enable training.

PyTorch uses a modern separate environment, not the Ryu Python environment. Local
IPC accepts versioned bounded JSON requests, no shell strings/paths/arbitrary
executables. Docker lifecycle remains operator-side, never web backend authority.

## Environment Contract

An operator experiment server owns the Mininet instance. A fixed client command
`python -m emulation.experiment_client` accepts one JSON request on stdin and emits
one JSON response on stdout via the container-local Unix socket. Logs use stderr.
Requests: `{version:1,command:"reset"|"step"|"close",episode_id:string|null,
step_index:int|null,seed:int|null,scenario:string|null,action:int|null,
mode:"sdn"|"ospf",window_seconds:number,episode_steps:int}`. Reject unknown fields,
invalid identities, repeated/out-of-order steps and excessive duration/count.
Response: `{version:1,ok:bool,error:string|null,data:object|null}`.

Reset returns measured initial observation; step applies a selected route then
measures a complete workload window. Data fields: `episode_id`, `step_index`,
`mode`, `seed`, `scenario`, `terminated`, `truncated`, `observation` and `evidence`.
Observation fields: `path_utilization:[float|null,float|null]` (fraction, busiest
port direction), `path_queue_packets:[float|null,float|null]` (peak leaf backlog),
`latency_ms:float|null` (foreground ping RTT), `loss_fraction:float|null` (foreground
UDP receiver loss), `goodput_mbps:float|null`, `offered_mbps:float`,
`background_mbps:float`, `previous_action:int`, `seconds_since_change:float`.
Environment-spec V2 additionally requires `actual_offered_mbps:float|null`,
measured from sender bytes/duration. Evidence includes a versioned environment
specification and source/image hashes, complete measurement/phase/window proofs,
and explicit service-outage/censored-latency indicators. Outer transport remains
version 1; V2 model contracts reject previous feature/spec checkpoints.
Evidence records source counters/duration windows, probe counts, UDP receiver
counts, real path/readback, workload phase, desired/measured interval and control
overhead. Null is unavailable, never zero; incomplete windows truncate and cannot
be used as valid training transitions. Response bounds and cleanup/watchdog apply.

Actions are two fixed complete routes: 0=access1/dist1/access2,
1=access1/dist2/access2, foreground h1->h3. Holding a route does not reinstall it.
Route changes use the existing lab Actions driver with verified cleanup/readback;
uncertain state aborts. Background h2->h4 competes on a fixture-selected path in
SDN. Scoped fixture forwarding must not bypass or conflict with driver ownership.
OSPF uses actual FRR router namespaces on the same capacity/delay/queue graph,
separate per-link L3 subnets and explicit cost/ECMP policy. It cannot secretly
pin background routes contrary to OSPF; resulting baseline differences are stated.

Decision target is a five-second measurement window by default, bounded 2..10;
transition/reconfiguration overhead is recorded separately and included in episode
wall time. Episodes 2..64 decisions, fixed seeded schedules: low, path0, path1,
alternating, burst, overload. Seed controls offered workload, not measurement output.
Training/validation/test seed ranges are disjoint (1000+, 2000+, 3000+), with split
metadata frozen into artifacts. The non-learning heuristic selects lower measured
path pressure with hysteresis; OSPF is not described as a controller heuristic.

## PPO and Artifacts

Use a small categorical actor and value critic, clipped PPO objective, GAE,
entropy regularization, gradient clipping, bounded rollout/minibatch configuration
and seeded initialization. Static capacity/reference scaling preserves absolute
load. Fixed topology adjacency and previous action are part of the state; missing
features have explicit masks but invalid measurement windows are not rewarded.
Reward components: delivered/actual-sent goodput, RTT, UDP loss, maximum utilization,
queue pressure and actual route-change penalty. All weights/scales/dimensions and
raw component values are versioned. No Lyapunov or convergence claim is inferred.

The workload advances between decisions and includes latent phase context, so this
is explicitly a sampled partially observed task, not a proven fully observed MDP.
V2 stacks three measured frames (147 inputs), with reset-local history and no
future phase, scenario label or PRNG seed entering the actor. History mitigates
partial observation but does not prove Markov sufficiency. The objective is per
decision; varying transition overhead is logged, not equated to fixed wall time.
Verified zero-reply service failures retain null observed RTT and use a separately
labeled 1000 ms censored-delay penalty; missing instrumentation stays invalid.

Checkpoint stores weights, optimizer state when resuming, normalization/features,
topology/action map, hyperparameters, seeds, training counters and runtime versions.
Load weights with restricted tensor loading, validate shapes/finite values/contract
hash, reject incompatible checkpoints and never load arbitrary pickle objects.
Separate train/evaluate/infer commands. Inference emits probabilities/value/evidence
without claiming those probabilities are safety confidence. Actual live evaluation
must reload the checkpoint in a fresh process with held-out workload seeds.

## Acceptance and Limits

First run non-learning reset/step episodes, real FRR adjacency/routes/traffic and
repeatability checks. Then train on real measured transitions, save/reload and run
held-out episodes compared with heuristic/OSPF. Preserve raw JSONL traces, summaries,
checkpoint hashes and failure outcomes. A short training run demonstrates pipeline
functionality, not statistical superiority, generalization or a final trained model.
Document measured limitations, environment capacity and elapsed training budget.
