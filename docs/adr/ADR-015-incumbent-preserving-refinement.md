# ADR-015: Incumbent-Preserving Model Refinement

- Status: Accepted for explicit user request to improve the trained model
- Date: 2026-09-10

## Objective

Preserve ADR014 checkpoint `5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`
and its frozen runtime/results unchanged. Improve generalization and unnecessary
switching rather than repeatedly optimizing its already-observed test. No guarantee
of improvement and no automatic deployment. New matched stationary curriculum may
vary demand, background and available path capacities in both methods identically;
OSPF routing/cost policy remains the same declared nominal-cost baseline.

## Compatibility and Evidence

Version expanded lab semantics and validate exact seed-derived schedules. Keep
historical v4 experiments reproducible. Incumbent evaluation under new scenarios
is an explicit transfer/generalization experiment, not silent checkpoint-compatible
deployment. The same 16 measured feature definitions/action map permit tensor-only
transfer after architecture, hashes and finite-value checks. New manifests record
parent checkpoint and source/semantic hashes. No edits to original artifact files,
no implicit reload of incompatible feature definitions and no heuristic actor.

Use low-demand/equal-path, moderate/severe asymmetry and overload cases as well as
the original stationary direction anchor cases. Actions remain real foreground
policy routing, with verification/drain/cleanup. Avoid hidden dynamic workload
changes until the stationary generalization gates work. Reset-state/equal-capacity
behavior must not produce unnecessary switches solely from a preferred route.

## Predeclared Campaign

Freeze an explicit new plan before measurement. Reserve unique training/validation/
test seed and profile combinations; do not use original held-out observations in
training or checkpoint selection. Train from a hash-verified incumbent or fresh
initialization as explicitly declared, with fresh on-policy updates only. Validation
selects candidate, never final test. At most two candidate configurations selected
on training-only justification; at least 256 fresh transitions for the refinement
candidate unless failure/resource limits stop it. No tune-until-test-win cycle.

Each stage has a finite wall deadline and cleanup reserve. Initial overall refinement
campaign cap four hours including collection and final evaluation. Durable background
service is allowed with visible status/stop commands, no automatic restart, pinned
images and exact owned-resource cleanup. If more data is necessary, preserve the
stage and report the next justified experiment rather than creating endless jobs.

## Promotion

Compare locked candidate with incumbent, actual OSPF, constant routes and heuristic
on fresh matched validation and final seeds. Include original-profile anchor
regression checks plus the wider profiles. Require a meaningful validation gain
(mean reward > incumbent +0.02) or predeclared substantial route-change reduction
without material delivery/RTT regression. Final promotion needs paired seed-level
evidence of the selected improvement and non-regression margins on anchor and low-
load groups. Freeze exact margins/sample counts/order before first collection.
Neither confidence probability nor more optimizer updates alone is an improvement.
Report unsupported generalization, variance and failed groups without hiding them.

Preserve incumbent as default unless replacement passes all gates. If candidate
fails qualification or a valid final test, retain it for research, not deployment.
Production control, calibrated stability and autonomous activation remain separate.
