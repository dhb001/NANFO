# ADR-013: Matched Routing and Evidence-Gated Completion

- Status: Accepted for user-requested coordinated completion effort
- Date: 2026-09-09

## Decision

Preserve historical campaigns/results. Training has stopped; version new learning
semantics instead of loading incompatible checkpoints. Complete a matched routed
benchmark using actual FRR/Linux forwarding for both baseline and learned policy,
with identical graph, addressing, queues, demands and exogenous impairments.
Baseline forwarding uses FRR OSPF routes. Learned routing overrides only the
foreground destination/source host routes over explicitly permitted paths; FRR
continues control-plane operation and background routing in both modes. Overrides
must be read-back verified and safely removed; no change to production or manual
ADR-010 execution authorization. New mode is operator-only isolated experiment.

Begin stationary episodes with balanced path-pressure conditions and complete
causally relevant observations; impairments/demand remain fixed through the action
measurement. Costs/ECMP/demand/impairment policy are frozen and identical across
methods, including any deliberate capacity mismatch with configured OSPF costs.
Do not secretly pin only one method's background traffic or label a different
dataplane comparison fair. Dynamic schedules remain explicitly partial-observation
research until a separate causal observation contract is implemented.

## Acceptance Plan

Version/hash complete lab semantics and feature/action/reward contracts. Separate
actual model inference latency, observation acquisition, control/readback latency,
application RTT and delivered throughput. Faster inference is not faster recovery.
Use train-only action-effect checks and fresh on-policy PPO, balanced stationary
curriculum before dynamic additions. Predeclare budgets and seed ranges before
collection; select using validation only and run reserved test after selection.
No tune-until-pass loop, generated rewards or training on held-out outcomes.

Require action dependence and improvement over both constant routes on balanced
held-out scenarios before qualifying the model. Report the heuristic as a serious
baseline even if it wins. Matched OSPF superiority requires measured effect and
uncertainty, not a guaranteed outcome. Bound this interactive implementation's
initial measured campaign to 20 minutes of collection; if insufficient, retain
artifacts and report remaining training rather than launching indefinite work.

## Safety and Autonomy

Implement compatible inference/calibration tooling only against exact versioned
evidence. Calibrated model bounds need causal service/arrival guarantees, not fitted
maxima silently relabeled guarantees. If empirical bounds fail coverage, keep
autonomous dispatch blocked. Server-owned approval/certificate/recovery must use
existing Autonomy/Intent ownership and receiver checks, never set manual approval
on behalf of a user. Tests may exercise injected adapters but cannot qualify them.
Production and online learning remain disabled. Do not mark Step 9/10 complete
without qualified policy, valid bounds and a live verified closed-loop intervention.
