# ADR025 simulation and measured verification interface

Owner: simulation/verification workstream. Core owns other files in
`backend/app/modules/autonomy/experimental/`. This contract is the integration
handoff; neither module performs I/O, controls a lab, trains, nor grants safety.

## Core integration contract

`simulation.py` exports Pydantic contracts `FrozenMeasuredFrame`,
`SimulationAssumptions`, `ActionProposal`, and
`evaluate_actions(*, frame, assumptions, actions, policy_sha256, now)`.
Inputs may be model instances or dictionaries. `frame.raw` is the **unchanged
frozen response data** (`response.data`, not an encoded observation vector).
The envelope binds network/workspace, runtime SHA256, window timestamps and raw
data SHA256. Core must obtain these from its trusted measured acquisition and
clock attachment, not timestamp historical evidence as fresh.

Assumptions declare exactly two ordered foreground paths (action0/action1), one
background path, directed link/interface mappings, buffers, initial queue bytes,
modeled delays, tick/horizon, freshness and one shared set of `ScenarioLimits`.
Every initial queue, including zero, is explicitly operator configured. Packet
backlogs are never converted to observed bytes. Capacities come from raw HTB
readback or explicit raw linkPlan/spec links, never defaults. Demand comes from
actual sender bytes/duration. Each action has `intent_id`, `action_id`,
`action_index` and `plan_sha256` (the core's exact approved bounded command hash).
HTB parsing accepts authentic JSON or qualified Bullseye text output, checks the
owned `5:1` rate/ceil and capacity label at both ends of the window, and rejects
capacity changes. A shaped egress cannot fall back to nominal linkPlan capacity.

Returns one dictionary per action: canonical `scenario_config`, actual evaluator
`result`, config/result hashes, foreground checks, configured-model `risk_gate`,
explicit assumptions and a binding of frame/action/policy/assumptions hashes.
Model risk pass is admission to this configured experiment only; always
`physical_safety_authorized=false`. Malformed/incompatible inputs raise
`ValueError`; core must block predispatch and retain the failed attempt.

`verification.py` exports `VerificationPolicy`, `verify_post_action` and paired
performance comparison contracts (details below). Core must persist the
complete returned evidence, enforce current authority/STOP/expiry and restore
owned state on anything other than fresh `keep`. A restoration requirement is
not evidence that restoration happened.

## Scope and acceptance

Pure internal Simulation evaluator integration authorized by ADR025. No endpoint,
event or database changes. Analytical/unit verification precedes live collection;
this workstream does not run a lab or modify current SafetyShield.

## Core protocol adapters (ready for integration)

- `ConfiguredSimulator(clock=...).simulate(frame, inference, policy)` implements
  `ports.Simulator` and returns the core `SimulationRecord`. Install
  `evaluator_sha256()` in the policy; it hashes actual evaluator/schema/adapter
  source bytes, including the raw verification dependency. `policy.assumptions` contains `SimulationAssumptions` fields
  **except** `limits` and `max_observation_age_seconds`, taken exclusively from
  `policy.objectives` and `policy.max_observation_age_seconds`. Those duplicated
  fields are rejected. Policy route ordering must be action0 then action1 and
  node sequences must match the configured directed paths exactly.
- Additionally install `policy.assumptions.verification_paths` with
  `foreground_nodes: [fullPath0, fullPath1]` and `background_nodes: fullPath`.
  These are complete kernel readback paths including endpoint hosts. This one
  field is excluded from the numerical model assumptions but remains bound by
  the full policy hash. The simulation paths may be the inter-router subgraph
  when host-link capacity evidence is unavailable; this limitation is explicit.
- `from_core_frame` accepts exactly one successful `snapshot.history.frames`
  record and preserves its raw response. Historical frames cannot be made fresh
  by this adapter.
- Simulation precedes command creation in the core protocol, and that command
  itself contains the simulation hash. Consequently `ConfiguredSimulator` binds
  its plan hash to the **exact registered route + inference hash + whole policy
  hash**, not to a nonexistent future command. Core must retain its command's
  frame/inference/simulation digests and exact route checks before I/O. The lower
  level `evaluate_actions` can bind an already-existing command hash directly.
- `verification_record(before=coreFrame, after=coreFrameOrNone,
  prepared=PreparedAction, policy=ExperimentalPolicy,
  action_completed_at=actualAwareTime, now=awareTime)` returns a core
  `VerificationRecord`. Transport supplies independent fresh readback/traffic
  acquisition; this function does not acquire it. It derives both UDP loss and
  ICMP probe loss, applies their separate installed maxima, and stores all checks
  and source digests in `provenance.verification`. The core `loss_fraction` is
  **UDP loss**, matching the updated `authority.verification_allowed`; probe loss
  uses `max_probe_loss_fraction` and remains separately checked and recorded. Failed/missing verification sets
  `route_verified=false` so it cannot pass the core gate.

## Verification semantics

`verify_post_action(before, after, action, policy, policy_sha256,
action_completed_at, now, purpose="post_action")` is keyword-only. It requires
matching network/workspace, episode, seed, scenario, runtime, source/spec and
image provenance. The new observation window must start after actual action
completion, finish after the old observation, and be fresh at verification.
Raw independent kernel readback covers foreground and background in both
directions, parsed from qualified frozen v4 `route_end.readback.paths` (or later
v5 `routing_health_end.paths`). Route summaries alone cannot pass. Raw UDP sender/receiver counts,
lifetimes, verified drain and probe counts/RTT reconstruct metrics; summary
observation numbers are ignored.

- `keep`: complete, fresh evidence passes every check.
- `fail`: valid evidence violates a threshold or route check; a positive probe
  count with zero replies is an outage (RTT stays null), never safe.
- `missing`: stale, mismatched, malformed or unavailable evidence; zero probe
  count cannot produce a division or a pass.
- `restoration`: only `purpose="restoration"` with fresh passing evidence for
  the requested restored route. An acknowledgement/request is insufficient.

`missing` and `fail` require restoration; they do not claim restoration occurred.
Core still owns expiry, authority, STOP, exact ownership and recovery. The frozen
measurement's goodput denominator is actual sender lifetime, including control;
receiver totals include verified drain. RTT is real ICMP RTT during load. Neither
is relabeled as a pure steady-state or hard convergence guarantee.

## Paired performance

`paired_performance(list[PerformanceTrial])` requires one experimental, fixed0,
fixed1 and heuristic record per `(seed, scenario, window_index)`, same scoped
runtime/spec/source and preregistered workload digest/window configuration.
Different episodes are allowed for paired reruns; different seed sets, missing
comparators and duplicate attempts are rejected rather than silently dropped.
All valid and negative metrics remain per pair. Unavailable metrics/deltas are
null; outages do not acquire invented RTT. Timing accepts only `ObservedTiming`
with recorded monotonic endpoints, clock identity and raw evidence hash for
decision/action/recovery. Unmeasured timing stays null. Service-window duration
comes from actual raw interval endpoints. Differences are experimental minus
comparator; these are observations, not confidence intervals or safety claims.
Core/collector must retain the referenced timing bytes and preregistered workload
record; hashes are integrity bindings, not independent proof of authenticity.

### Comparator contract update (core `policy_kind`)

`ConfiguredSimulator` accepts the core `InferenceRecord` discriminated by
`policy_kind = model | fixed0 | fixed1 | heuristic`. It invokes the owning
`authority.inference_allowed` contract: models retain their actual qualified
`RuntimeResult`; baselines carry `ComparatorResult` + `BaselineProposal`, with
`qualification=None`, no checkpoint, probabilities or value. Selector kind must
match the installed policy and the core recomputes its exact fixed/heuristic rule.
No comparator is promoted to a qualified model to get through simulation.

Every lane runs the **same two numerical scenarios with the same shared limits**.
Admission requires both the evaluator's aggregate objective checks and separate
foreground checks. A passing aggregate cannot mask foreground failure. Results
include `policy_kind`, `predispatch_status`, `admission_policy_sha256`, per-action
configurations, actual output hashes, foreground/aggregate checks and explicit
metric semantics. Changing selector identity changes the bindings, not modeled
flow outputs or objectives for identical frame/assumptions.

`admission_policy_sha256(policy)` hashes assumptions, objectives, verification
thresholds, evaluator identity, exact routes, freshness, dwell, action duration
and budgets. It intentionally excludes selector/per-run identity. The complete
policy hash still binds each action. Campaign must preregister identical admission
semantics across model/fixed0/fixed1/heuristic, retain this shared digest and each
full policy/simulation record, and enforce the same authorization/owner/hold/
verification/restoration gates. Rejected baselines must not be rerun with weaker
thresholds or silently removed from the paired population.

`PerformanceTrial` now requires `admission_policy_sha256`, `simulation_sha256`,
`selected_action_index` and observed `mutation_count`; `outcome` is `measured` or
`predispatch_rejected`. For rejection, `frame` is the **predecision** frame,
mutation count must be zero, and action/recovery timings must be absent.
`paired_performance` retains the rejected lane and its hashes but returns null
metrics/deltas with reason
`predispatch_rejected_zero_mutation_no_postaction_metrics`. It never credits that
predecision traffic to an action that did not run, or calls rejection a rollback.
Actual zero mutation must be established by the controller/owner journal; the
simulator itself only knows admission status. Pairing different admission-policy
digests is rejected. The full campaign still needs its preregistered coverage and
joined controller evidence; this adapter does not fabricate baseline effects.

### Durable frozen raw replay

`backend/tests/unit/test_experimental_simulation_raw.py` reads the unchanged
durable files directly (optional fixture dependency on clean machines):

| Artifact under `ai-engine/artifacts/adr024-qualified-001/model/` | Exact-byte SHA256 |
|---|---|
| `recorded-history-path0.json` | `21529463ae34c83d6f44518b25712d6d935fdece8614628886ae59c0090d19c9` |
| `recorded-history-path1.json` | `253a53d91feff7ca5b31cca54b05c20123bb86e56033509bbae0ab69a0e91a32` |

The test verifies pins before JSON parsing, retains unchanged request/response,
passes real raw HTB text, UDP counters, probe evidence and kernel paths through
the core frame/simulator/verification pipeline, and verifies file bytes afterward.
Its envelope uses a deliberately **synthetic year-2000 offline clock anchor**;
these frames are never published or described as fresh. Current-clock evaluation
explicitly fails. Existing synthetic unit tests remain mandatory without artifacts.

Independent arithmetic reconstructs actual goodput from received bytes / sender
lifetime, UDP packet loss and separate ICMP probe loss. Model demand uses actual
sender rates; offered bytes use that rate times the configured horizon; conserved
fluid counts independently reconstruct modeled throughput/loss/residence latency.
Model residence latency is not measured ICMP RTT, aggregate throughput is not
foreground goodput, and horizon throughput is not the sender-lifetime metric.
The tests deliberately impose no equality between these different quantities.
The raw path0 record's unequal UDP and probe losses prove core
`VerificationRecord.loss_fraction` remains actual **UDP only**, while changing
only the probe maximum independently fails the probe gate.

## Analytical test evidence

`backend/tests/unit/test_experimental_simulation.py` exercises both congestion
directions with one policy, exact bottleneck throughput, per-flow and initial
background byte conservation, reproducibility, explicit queue assumptions,
raw capacity parsing, binding/replay tampering, stale/future inputs, unavailable
metrics, outages, route mismatches, zero denominators and matched comparisons.
Scoped evaluator+adapter+core unit run, including installed durable raw replay:
**76 passed, zero skips**; scoped Ruff and
`git diff --check` clean. Command:

```sh
pytest tests/unit/test_experimental_simulation.py tests/unit/test_experimental_simulation_raw.py tests/unit/test_simulation_evaluator.py tests/unit/test_experimental_lab.py -q --no-cov
```

Run from `backend/`. These are analytical unit
fixtures, not collected lab results or a joined-loop acceptance claim.

Integration ownership note: `ConfiguredSimulator` and `verification_record` are
ready to compose, and the core-shaped simulator/verification bridge is unit-tested.
Transport/controller owners must wire them into their concrete composition;
their files were not edited by this workstream. Preserve the raw verification
classification in campaign records. Analytical thresholds in tests are fixtures,
not automatically installed campaign policy.
