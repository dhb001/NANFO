# ADR-014: Expanded Measured PPO Training

- Status: Accepted for explicit user request for further training and refinement
- Date: 2026-09-09

## Objective and Boundaries

Pursue useful learned routing and a matched OSPF improvement using real measured
experience. No guarantee of victory, no altered historical results, no weaker
OSPF configuration chosen after seeing test outcomes, no synthetic reward fallback.
Continue isolated matched Linux/FRR experiments only. Autonomous production safety
and receiver authorization are separate gates and remain disabled.

## Measurement Revision

Version the receiver-drain contract: stop senders, retain receivers while checking
actual relevant queues empty with a finite maximum drain interval, record endpoint
counts and late delivery, and truncate if drainage cannot be established. Preserve
service outcomes during reconfiguration; do not hide transition losses. Latency
remains explicitly ICMP RTT unless separately measured UDP echo is implemented.
Old v3 cutoff totals are retained as historical delivery-deficit data, not corrected.

## Learning and Selection

The previous two-update pilots were insufficient learning budgets. Use fresh PPO
rollouts, stationary balanced path0/path1 conditions and a predeclared extended
training plan. Diagnose training-only gradient/action-effect behavior first. Permit
learning rate, rollout and value-horizon refinements justified on train-only
diagnostics; freeze them before validation. Model selection uses validation only.
No data from reserved final test influences model, weights, stopping or OSPF costs.

Replace the inconsistent synthetic pressure-swap veto with measured directional
dependence in the newly versioned acceptance plan. Require advantage over BOTH
constant baselines plus measured action dependence in both congested directions;
keep heuristic comparison even if it wins. Baseline repeatability/timing order and
paired seed-level uncertainty are reported. No treating individual packets/windows
as independent experimental replications. If improvement is limited to degraded
nominal-cost OSPF scenarios, name that exact scope.

Freeze seeds, model candidates, checkpoint schedule, stage resource/time limits
and qualification before collection. Initial stage may run up to two hours of
measured collection; additional authorized stages require a saved plan and clean
checkpoint, never endless tune-until-test-pass. Background work must have a service
cap, status/stop commands and exact owned-container cleanup. No test retries after
valid unfavorable results. Invalid/incomplete runs are preserved and investigated.

## Acceptance

Save selected checkpoint with complete environment/runtime/feature/reward metadata,
train/validation traces and exact model identity. Fresh-process deterministic
inference and raw replay must match. Evaluate the locked selected model and
unchanged OSPF/constants/heuristic on reserved seeds with effect sizes, uncertainty,
delivery/loss, RTT, route changes and controller/inference/observation timings.
Claim success only for measured metrics/scenario scope supported by those results.
If qualification fails or budget expires, retain artifacts and explicitly state
the remaining gate; no automatic promotion or confidence fabrication.
