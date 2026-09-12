# ADR013 Measured Campaign 001

## Outcome

Parent-authorized campaign completed within its frozen budget. **No policy qualified.**
Both fresh PPO pilots learned finite changed weights but selected route0 on every
deterministic validation decision. The directional acceptance gate correctly refused
promotion despite positive noisy mean margins over both constants. No tuning,
retries, resumed training, new seed plan or quality-gate relaxation occurred.

Artifacts: `ai-engine/artifacts/adr013-001/`. Historical campaigns are unchanged.
Primary status: `campaign.json`; independent replay: `final-audit.json`; immutable
file digests: `artifact-hashes.json`; exact runtime snapshot: `frozen-client-source/`.
Per-session raw JSONL, summaries, checkpoint bundles, command stdout/stderr and full
container ownership records are preserved.

## Collection

- Frozen 1200-second wall budget, conservatively starting before first lab startup.
- Start Unix `1788986607.5538967`; deadline `1788987807.5538967`.
- Finished in **1010.5125 seconds**, leaving 189.4875 seconds. This was insufficient
  to admit complete pilot43 training plus validation and the frozen cleanup reserve.
- Ten completed sessions: two calibration, two fresh training, six validation.
- **220 real measured windows:** 44 initial observations and 176 decision windows.
- **Zero invalid windows**, no transport/measurement failures, no cleanup failures.
- All ten captured container IDs verified removed; campaign process exited.
- Training total: 64 transitions, four PPO updates across two independent models.
- Calibration seeds1480..1481; pilot41/train1500..1507; pilot42/train1520..1527;
  validation2600..2603. Pilot43/train1540..1547 not accessed.
- Test3800..3803 not accessed because no policy qualified. No selection file created.

Exact executing image:
`sha256:72b267fdcb6f197d0ffe4960389e238ea093fac61b3f95751cf98edfefd098ad`.
Exact shared matched/OSPF spec:
`5ece436bfa8b41fd868dfc87dc5152848d038e25511c6dadee1e64a420b1cbe9`.
All session source/image/spec and client source bindings passed independent replay.
Matched comparison checks actual Linux/FRR background routes, identical exogenous
phases/capacities/demands and frozen nominal OSPF costs. OSPF does not adapt its
configured cost to the stationary 2/20 Mbps impairment.

## Calibration

Mean decision rewards from actual train-only measurements:

| Scenario | Constant0 | Constant1 | Preferred Minus Other |
| --- | ---: | ---: | ---: |
| path0 | -2.064683 | 0.661470 | 2.726153 |
| path1 | 0.864677 | -1.321835 | 2.186512 |

Both exceeded the unchanged strict .02 action-effect gate. These outcomes were
used only to admit training, never supplied as PPO transitions or actor labels.

## Validation

Each row has four balanced reserved validation seeds, four decisions per seed.
Loss is the foreground UDP delivery deficit at the bounded receiver cutoff, not
proven eventual packet loss; queued packets can arrive after that cutoff. Latency is measured concurrent ICMP
RTT, not UDP echo RTT, model inference time or a recovery-time guarantee.

| Method | Mean Reward | Goodput Mbps | UDP Loss % | ICMP RTT ms | Route0 / Route1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Constant0 | -0.406449 | 3.934785 | 35.3587 | 145.9337 | 16 / 0 |
| Constant1 | -0.461987 | 4.047189 | 32.3103 | 160.5111 | 0 / 16 |
| Pressure heuristic | 0.249410 | 5.130782 | 14.6575 | 76.3231 | 4 / 12 |
| Actual OSPF | -0.330326 | 3.941382 | 35.2731 | 127.5459 | 16 / 0 |
| PPO41 | -0.292103 | 3.938793 | 35.3152 | 117.4791 | 16 / 0 |
| PPO42 | -0.351993 | 3.939273 | 35.3074 | 132.6102 | 16 / 0 |

The heuristic had the best observed mean reward/goodput/RTT, though it switched
ten times and was not optimal on both stationary conditions. No heuristic or PPO
statistical superiority claim is established by this small campaign.

| Pilot | Margin Over Constant0 | Margin Over Constant1 | Directional Gate | Qualified |
| --- | ---: | ---: | --- | --- |
| 41 | 0.114345 | 0.169884 | Failed: route0 everywhere | No |
| 42 | 0.054456 | 0.109994 | Failed: route0 everywhere | No |

Both pilots: path0 preferred-route fraction0; path1 fraction1. Pressure-swap
diagnostic fractions1 and0 respectively, also failing the requirement for both
directions. Both `qualify` commands returned exit2, a quality rejection rather than
an execution failure. Exact frozen checkpoint replay reproduced all decisions.

Positive mean margins do not demonstrate adaptation: PPO and constant0 chose the
same route, and their delivery rates were nearly identical. RTT/measurement noise
accounts for much of the reward difference. No gate was weakened to accept this.

## Uncertainty

Paired seed-mean Student-t 95% intervals, four seeds (df3), PPO minus actual OSPF:

| Metric | PPO41 Difference [95% CI] | PPO42 Difference [95% CI] |
| --- | --- | --- |
| Reward | +0.03822 [-0.33176, 0.40820] | -0.02167 [-0.64005, 0.59671] |
| Goodput Mbps | -0.002590 [-0.011646, 0.006466] | -0.002109 [-0.008853, 0.004634] |
| ICMP RTT ms | -10.0669 [-103.2433, 83.1096] | +5.0643 [-150.1258, 160.2543] |

All include zero. Individual paired seed means, loss intervals, constant/heuristic
comparisons and raw RTT aggregates remain in `report-41.stdout.log` and
`report-42.stdout.log`. Windows are not treated as independent experimental seeds.
These intervals assume approximately normal independent seed effects; four seeds
and sequential sessions give weak evidence and do not eliminate time/order effects.

## Timing

| Method | Model Inference p50/p95/p99 ms | Control/Readback p50/p95 ms | Observation+Control+IPC p50/p95 s |
| --- | --- | --- | --- |
| PPO41 | 0.705 / 0.963 / 1.258 | 96.866 / 111.694 | 3.466 / 3.628 |
| PPO42 | 0.780 / 1.047 / 1.061 | 90.579 / 94.801 | 3.408 / 3.611 |
| OSPF | Not applicable | 28.362 / 48.955 | 3.363 / 3.513 |

The generic log field `inference_seconds` for OSPF records only the Python harness
reading the current route (p50 .002871ms), NOT FRR SPF compute time or convergence.
No OSPF convergence benchmark was performed. Small model inference time is not
faster network recovery. UDP echo RTT remains **unimplemented/unmeasured** and was
not replaced with ICMP or used to block the authorized campaign.

Fresh-process diagnostic inference succeeded for both measured checkpoints, with
input/policy hashes, actual measured evidence and timing outputs in `infer-41` and
`infer-42` stdout logs. Both report `qualification_checked:false`, `execution:not_applied`.

## Durable Models

Pilot41 checkpoint SHA256:
`76fa4d62be9b75f659e078ea02562d5c1a2ea5c3a5cf9f1995d1ad168ff8d981`.
Pilot42 checkpoint SHA256:
`754ed77b055687cf41808bb2f33f1c3f25b6323ba4d4141a04c4f1112d943bb5`.
Both bundles contain model, optimizer, RNG, full contracts, provenance, training
seeds and counters. Independent comparison against same-seed initialization found
changes in every actor/critic parameter tensor (maximum changes about .00242),
confirming real optimization rather than an untrained fixture. This does not imply
convergence; only two PPO updates per pilot were predeclared and executed.

## Gates

| Gate | Outcome |
| --- | --- |
| Offline unit tests before collection | 214 passed |
| Frozen budget, seeds, image/spec and client sources | Passed |
| Real matched capacity/route action effect | Passed |
| Measured on-policy training and durable checkpoints | Passed |
| Raw evidence reconstruction and deterministic checkpoint replay | Passed |
| Mean reward > BOTH constants by .02 | Passed for both pilots |
| Directional decision dependence | Failed for both pilots |
| Useful learned policy qualification | OPEN, unqualified |
| OSPF statistical superiority | Not established |
| Reserved fresh test | Not run, untouched |
| Actual UDP echo RTT | Missing, explicitly disclosed |
| Owned container cleanup | Passed, all ten removed |
| Backend assessment/installation | Not invoked; no qualified policy |
| Autonomous dispatch/safety bounds/live closed loop | Disabled and OPEN |

Historical handoff: backend tooling was inspected read-only. Its strict producer schema did not yet
accept `train_only_action_effects`, `calibration_evidence_sha256`, `evidence_paths`;
its strict checkpoint schema lacks `client_source_files`. Do not strip these fields
or forge an older producer artifact to pass it. No backend files were modified and
no autonomous mode was enabled. A future qualified model needs an explicit compatible
backend importer/dossier and independent safety/calibration gates.

## Reproduce Audit

Read existing results without collecting or changing anything:

```bash
ai-engine/.venv/bin/python ai-engine/scripts/campaign_status.py ai-engine/artifacts/adr013-001 --compact
ai-engine/.venv/bin/python -m nanfo_routing inspect --checkpoint ai-engine/artifacts/adr013-001/train-41/checkpoint.ptz
ai-engine/.venv/bin/python -m nanfo_routing infer --checkpoint ai-engine/artifacts/adr013-001/train-41/checkpoint.ptz --history ai-engine/artifacts/adr013-001/validation-41/last-history.json
```

Do not rerun the completed campaign or extend its ledger. Any follow-up needs a
new explicit predeclared budget/plan; this result does not authorize further training.
