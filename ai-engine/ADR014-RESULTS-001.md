# ADR014-001 Measured Outcome

Executed after the completed drainV4 lab release. **The requested512-transition
target and reserved final test were not completed.** The measured model did learn
directional adaptation; this was not another fixed-route two-update pilot.

## Actual Collection

- Campaign: `artifacts/adr014-001`, systemd unit `nanfo-adr014-001.service`.
- One model, seed44, learning rate0.003/gamma0.9 fixed throughout. Fresh train
  seeds1600..1695: **384 transitions,24 on-policy updates**, six exact resume blocks.
- Fifteen completed sessions: two calibrations, six training blocks, four validation
  baselines and three PPO validations. **624 decisions plus156 reset windows**.
- Actual first-start to last collection completion: **4125.43 seconds (68.76min)**.
  Collection ledger, not post-stop status elapsed_seconds, is the timing source.
- No invalid windows or session retries. Reserved test attempts: **zero**.
- Final service state independently checked: inactive/dead. Exact campaign-label
  Docker inventory was empty. No campaign subprocess/container was left running.
- No selected checkpoint, test report, OSPF test victory or autonomy promotion.

## Validation Curves

Eight fixed validation seeds2700..2707,32 decisions/checkpoint, balanced directions.
Every checkpoint chose the correct actual path on all16 decisions in each direction.

| Fresh transitions | PPO updates | Mean reward | P(correct), path0 | P(correct), path1 | Margin over constant0 | Margin over constant1 |
| --- | --- | --- | --- | --- | --- | --- |
| 128 | 8 | 0.788556 | 0.614849 | 0.590005 | 1.190724 | 1.270455 |
| 256 | 16 | 0.788710 | 0.916344 | 0.918060 | 1.190877 | 1.270608 |
| 384 | 24 | 0.792639 | 0.972966 | 0.968469 | 1.194806 | 1.274537 |

All three passed the V4 measured adaptation gate. Synthetic pressure-swap failed
one direction at256/384 while actual measured directionality remained correct;
as predeclared, that inconsistent synthetic input was diagnostic only. Heuristic
and unchanged OSPF comparisons, paired seed intervals and full raw curves remain
in each qualification artifact; these reused validation seeds are selection data,
not an untouched final test. Probabilities are not safety confidence.

Latest checkpoint: `artifacts/adr014-001/train-06/checkpoint.ptz`. Loading requires
the frozen AI source and runtime, retained in `artifacts/adr014-001/source/`.
No source changes were made during collection or after it to these frozen modules.
Independent post-run qualification reconstruction matched all three saved results.

## Budgeting Shortfall

The frozen supervisor required1200 seconds for a complete next128-transition pair
plus1800 reserved for five final-test policies, in addition to120 cleanup seconds.
After the384 validation and audits, remaining work time fell just below3000 seconds.
The supervisor therefore stopped at its admission cap rather than beginning the
last pair. Last collection ended with3074.50 seconds left on the total budget;
cleanup/audit costs and the separate work cutoff explain the admission refusal.

The separate predeclared selection rule required at least512 transitions. Thus
the384 model passed validation qualification but was **not selection-eligible**.
The status text `not_run_no_qualified_policy` is misleading shorthand for this
selection restriction; `outcome.json` explicitly distinguishes the two.

This was an implementation/planning shortfall, not a low-quality stop, budget
exhaustion, or lack of learning. The frozen admission rule was not changed after
seeing validation outcomes. No new campaign was launched to bypass its bounds.
Completing another128 fresh transitions and the12-seed final test requires a new
explicitly authorized saved continuation plan, preserving this original outcome.

The fallback cleanup also overwrote status `elapsed_seconds` with its own short
cleanup duration. The original immutable collection ledger gives the real timing;
it was not overwritten or relabeled. This display defect remains documented rather
than changing checkpoint-bound source and invalidating the completed campaign.

## Verification

Before live:299 tests passed, Ruff lint/format passed. Six released raw smoke
windows independently validated against actual V4 drain, endpoint counts and
sender-denominator goodput. Prior train seed metadata proved new seeds unused.

Read-only post-run reconstruction, already executed once (refuses outcome overwrite):

```bash
.venv/bin/python scripts/summarize_adr014.py
```

Machine outcome: `artifacts/adr014-001/outcome.json`. Exact launch/status/stop and
cleanup commands: [ADR014-TRAINING.md](ADR014-TRAINING.md). All changes in this task
were under `ai-engine/**`; lab/backend work remained with their owning agents.
