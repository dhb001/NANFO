# Matched Routing Completion Attempt

## Outcome

Implemented the matched benchmark, stationary curriculum, compact PPO and strict
evidence tooling; executed the predeclared measured campaign. BOTH models failed
useful-policy qualification. No selected model, reserved test collection, safety
calibration installation or autonomous execution was produced. These are actual
failed acceptance gates, not merely deferred documentation.

## Engineering Changes

Both matched policy and OSPF now use actual FRR/Linux router namespaces, identical
graph/addresses/traffic/queues and stationary seeded capacity impairments. Only the
foreground policy routes change for the learned method; background follows FRR
in both. Nominal OSPF costs remain deliberately fixed despite impairment, explicitly
not a capacity-aware OSPF comparison. Route/capacity readback and cleanup are verified.

V3 policy has 16 measured inputs and separate small actor/value networks with
balanced initialization. Static monotone scaling preserves pressure. Plan/seed/
spec/checkpoint/evidence hashes and qualification are strict. A later read-only
review hardened exact seeded-demand reconstruction without editing old artifacts;
old checkpoints cannot silently load under changed client sources.

Backend assessment independently reconstructs actual campaign measurements and
refuses both models. Calibration tooling refuses to fit guaranteed queue bounds
from peak samples lacking synchronized endpoints, attributed arrivals and heldout
calibration design. Empirical extrema are not promoted into TrustedCalibration.

## Measured Campaign

Artifacts: `ai-engine/artifacts/adr013-001/`, preserved locally with 122 indexed
file hashes and a frozen executing-source copy. Details in
`ai-engine/ADR013-RESULTS-001.md` and `ADR013-REVIEW-CORRECTIONS.md`.

- 1,010.5 seconds of the 1,200-second wall budget; no extension or tune-until-pass.
- Ten real sessions, 220 measured windows, zero invalid windows, cleanup passed.
- Two PPO initializations, 32 transitions and two updates each.
- Both constant-route action-effect checks passed, but each PPO selected route0
  on all 16 balanced validation decisions. Stochastic logits remained near-tied;
  this is not proof of exploration collapse or an incorrect PPO implementation.
- Reserved final test seeds 3800..3803 untouched. Third pilot not admitted because
  insufficient budget remained for its complete training/validation/cleanup.

| Method | Reward | Goodput Mbps | Cutoff delivery deficit | ICMP RTT ms |
| --- | ---: | ---: | ---: | ---: |
| Constant0 | -0.4064 | 3.9348 | 35.36% | 145.93 |
| Constant1 | -0.4620 | 4.0472 | 32.31% | 160.51 |
| Heuristic | 0.2494 | 5.1308 | 14.66% | 76.32 |
| OSPF | -0.3303 | 3.9414 | 35.27% | 127.55 |
| PPO41 | -0.2921 | 3.9388 | 35.32% | 117.48 |
| PPO42 | -0.3520 | 3.9393 | 35.31% | 132.61 |

PPO41 reward difference versus OSPF: +0.0382, paired four-seed Student-t 95%
interval [-0.3318,+0.4082]. PPO42: -0.0217, [-0.6400,+0.5967]. Neither establishes
superiority. PPO inference p95 about 0.96/1.05 ms, but total observation/control/IPC
p50 about 3.47/3.41 seconds. OSPF harness readback is not SPF computation latency.
No claim of faster network response is supported. UDP echo RTT is unavailable;
latency above is ICMP RTT. Receiver cutoff250ms can censor packets still queued
on2Mbps links; do not reinterpret these historical totals as eventual packet loss.

## Qualification and Safety

Independent backend assessments saved at:
`/tmp/opencode/adr013-backend-assessment-41.json` and `...-42.json`.
Both report useful_model_unqualified, failed measured directionality and heuristic
outperformance. No raw fields were stripped to bypass schema validation.
Calibration: fit_performed=false, holdout_coverage=null, trusted_calibration=null.
Current matched Linux route execution is also incompatible with the existing
manual OVS executor; it was not silently reused as autonomous authorization.

Pressure-swap synthetic inputs are a known overly restrictive diagnostic in this
frozen plan, but neither model passes real measured directionality either. Any
future revised qualification should make such inconsistent synthetic probes
non-gating under a new predeclared contract, not retroactively approve these models.

## Verification and Remaining Work

AI: 275 tests passed; Ruff/format passed. Backend: 1,704 passed,16 opt-in skips;
with actual campaign fixtures enabled,1,706 passed,14 infrastructure skips. Ruff
app/tests/scripts passed. Lab host66 passed/6 skips, image70 passed/2 opt-in skips;
live matched/OSPF action checks passed. No experiment owner left running.

Still required: larger predeclared fresh on-policy training after diagnosing train
learning curves, selected useful model, untouched final tests, verified-drain or
late-delivery accounting, physical safety calibration and compatible governed
receiver/recovery. No background training was launched. Do not treat this attempt
as completion of Steps8-10 or enable production/autonomous changes.
