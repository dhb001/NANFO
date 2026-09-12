# ADR015 Refinement Result

**Completed, not qualified for replacement. Incumbent retained unchanged.**

The fixed lower-LR PPO warm-start completed512 fresh measured transitions across
128 episodes (seeds1808..1935), with32 on-policy updates. All four checkpoints
were evaluated on the predeclared16 validation seeds2800..2815, each profile twice.
Incumbent, actual OSPF, heuristic and both constant-route controls also completed
matched validation. No configuration was changed in response to validation.

## Measured Outcome

| Validation Metric | Incumbent on V5 | Candidate512 on V5 |
| --- | ---: | ---: |
| Mean reward | 0.666380318 | 0.679507798 |
| Route changes per decision | 0.15625 | 0.12500 |
| Foreground delivery fraction | 0.951737239 | 0.955025370 |
| Foreground ICMP RTT, ms | 38.815672 | 36.931469 |

Candidate512 improved validation reward by **0.013127480**, below the required
strict gain **>0.02**. Route changes fell from10 to8 across64 decisions, a **20%**
reduction, below the required **25%**. All aggregate, original-anchor and balanced
low-load nonregression groups passed their validation margins, with no low-load
switch increase. Thus the failure was insufficient improvement, not a hidden
anchor/delivery/RTT regression.

| Fresh Transitions | Updates | Validation Reward | Reward Delta | Eligible |
| --- | ---: | ---: | ---: | --- |
| 128 | 8 | 0.668398985 | +0.002018667 | No; below minimum and quality |
| 256 | 16 | 0.675865681 | +0.009485364 | No |
| 384 | 24 | 0.679261384 | +0.012881066 | No |
| 512 | 32 | 0.679507798 | +0.013127480 | No |

Candidate512's diagnostic validation paired16-seed reward bootstrap95% interval
is `[0.002808636, 0.025889989]`; this is model-selection data, **not final-test
evidence**. Route-reduction interval per decision is `[0, 0.09375]`. The frozen
meaningful-effect threshold was not relaxed because an interval looked favorable.

**Final test was not admitted.** All3600..3623 final seeds remain unopened; zero
final policy attempts. No repeated test cycle, promotion, deployment or change to
the incumbent default occurred. Candidate checkpoints are research artifacts.

## Execution And Integrity

- Recovery campaign: `artifacts/adr015-002/`, campaign ID
  `ad9cf07a41f346888c8f20cb4ddd5fd4`.
- Completed13 measured sessions: four128-transition training blocks, five control
  validation sessions and four candidate validation sessions. Every session has
  raw JSONL, reconstructed metrics, hashes and acknowledged cleanup.
- Approximately107.8 minutes from the original attempt's start through final
  collection, including recovery; below the shared four-hour deadline.
- `status.json.elapsed_seconds` was reset by the separate ExecStopPost cleanup
  process and is not an end-to-end duration. Duration above is independently
  calculated from frozen `plan.json.started_unix` and the last ledger finish time:
  **6465.308431s**. The absolute hard deadline remained unchanged.
- Failed `adr015-001` retained: seed1800 reset and one actual decision; strict JSON
  tuple serialization stopped collection before any PPO update. Corrected once,
  excluded that seed, started again from original tensors, and retained original
  wall deadline. No failed observations were used for training or selection.
- Incumbent checkpoint remains
  `5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`.
  All **1,437** inventoried ADR014 files rehashed unchanged after completion.
- User service inactive; exact recovery campaign-label Docker query returned no
  containers. Cleanup error null. No broad cleanup was used.
- Full AI suite **324 passed**, one existing Gym infinite observation-box warning;
  scoped lint/format and whitespace checks passed.

## Evidence Paths

- `artifacts/adr015-002/plan.json`: preregistration, recovery provenance and hashes.
- `artifacts/adr015-002/ledger.json`: all admissions and timestamps, zero tests.
- `artifacts/adr015-002/validation.json`: every checkpoint and group gate.
- `artifacts/adr015-002/outcome.json`: terminal no-quality disposition/preservation.
- `artifacts/adr015-002/candidate-512.ptz`: final research checkpoint, not a winner.
- `artifacts/adr015-002/*/evidence.jsonl` and `audit.json`: raw and reconstructed sessions.
- `artifacts/adr015-release.json`: pinned completed lab release and independent48-window
  campaign-profile instrumentation replay; lab separately validated54 windows.

The experiment supports a modest validation improvement only. It does not establish
held-out generalization, robust convergence, production safety or autonomous control.
Any further experiment needs a separately justified, newly preregistered campaign;
the existing validation must not be presented as untouched evidence.
