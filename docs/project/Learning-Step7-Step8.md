# Steps 7-8: Measured Learning Environment and PPO

## Status

Step 7 is implemented and exercised with real SDN/FRR episodes. Step 8's actor-critic,
training, checkpoint and inference implementation is complete and live-tested, but
the acceptance criterion of a usefully trained adaptive routing policy remains OPEN.
Do not equate changed weights with improved decision-making. No Step 9 stability
filter or Step 10 application autonomy is enabled.

## Delivered

- Operator-only bounded reset/step/close transport, explicit isolated experiment
  mode mutually exclusive with manual mailbox control, workload cleanup/watchdogs.
- Actual concurrent UDP competing flows, RTT probes, port-duration counters and
  sampled leaf queues. Missing instrumentation invalidates transitions; measured
  outage is separately represented with null RTT and a labeled censoring penalty.
- Fixed two-route action mapping, held-route no-op, real readback and compensation.
- Seeded low/path0/path1/alternating/burst/overload schedules; real FRR zebra/ospfd
  baseline and measured pressure/hysteresis heuristic.
- Separate Python 3.12 CPU PyTorch/Gymnasium package; categorical PPO, GAE,
  entropy regularization, clipping, optimizer, resumable validated checkpoints.
- V2 three-frame observation history, capacity/reference scaling, raw reward
  contributions, actual sender-rate normalization, semantic/source hashes,
  disjoint seed splits and restricted checkpoint deserialization.
- Fresh-process train/evaluate/infer/report commands with evidence logs, failure
  artifacts and compatibility validation. No backend API or production changes.

## Measured V2 Campaign

Artifacts: `ai-engine/artifacts/measured-v2-20260909T110645Z/`.
Checkpoint: `train/checkpoint.ptz`.
SHA256: `742bf2498ee986c304848ed6617c5460be44ed36718554e48208139eed06004d`.
Summary/replay audit: `audit-v1/aggregate.json`.

The plan was frozen before execution: 12 training episodes, 4 decisions each,
5-second windows, rollout 16, model seed 42, training seeds 1100..1111 and a
600-second budget. Actual: 48 valid transitions, 12 reset windows, 3 on-policy
updates, 430.8 seconds. Every model tensor changed; parameter L2 delta 0.3410813681.
Exact replay reproduced all training decisions/update metrics and final weights.

Validation seeds 2101/2102 and test 3101/3102 map to overload/low under the frozen
modulo-six mapping. They do NOT cover held-out path0/path1 in this V2 campaign.
No model/reward changes followed evaluation. Each session reloaded the checkpoint
in a fresh process and owned a fresh lab; all cleanup checks passed.

| Split/policy | Reward/decision | Goodput Mbps | UDP loss | RTT ms | Changes | Actions 0/1 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Validation PPO | 0.4662 | 11.354 | 11.782% | 45.149 | 2 | 0/8 |
| Test PPO | 0.4539 | 11.736 | 12.148% | 45.888 | 2 | 0/8 |
| Test heuristic | 0.4394 | 11.738 | 12.138% | 46.262 | 4 | 1/7 |
| Test FRR | 0.1376 | 7.503 | 28.763% | 43.863 | 0 | 8/0 |

Total campaign: 80 decisions and 20 measured resets, no invalid windows/outages.
Fresh-process inference repeated bit-identical JSON on saved training/test histories.
Initial/final argmax remained route 1 for all 64 audited PPO histories. Therefore
the small reward difference is not evidence of learned adaptation or superiority.

## Baseline and Reproducibility Limits

FRR is actual OSPF with 14 Full adjacencies, captured protocol-89 packets, 36/36
host-pair replies and real link-failure convergence. It uses Linux L3, separate
subnets, explicit unequal tie costs and one next hop. SDN uses OVS L2 with the
scenario's pinned background route; FRR background follows its own routing. Report
these as distinct systems, not an apples-to-apples PPO/OSPF superiority experiment.

Dynamic workload phase is latent: history does not establish a fully observed MDP
or proactive prediction. Generator tolerance, unequal measurement windows, sampled
queue peaks and host/socket contributions to UDP loss remain explicit. Seeded
schedules are repeatable inputs, not bit-identical kernel observations. A short
smoke training budget cannot establish convergence or campus-scale generalization.

Runtime artifacts are retained locally and ignored by Git; hash references here
do not replace durable research artifact archival. Earlier V1 smoke model/results
remain retained and incompatible with the current contract.

## Verification and Operation

- AI package: 116 tests passed; Ruff and formatting passed. Gym warns about the
  intentionally unbounded observation-space maximum; raw inputs remain validated.
- Lab image: 64 tests passed, two opt-in gates skipped in build; live SDN/FRR
  baseline gates separately executed. Host: 60 passed, 6 runtime/opt-in skips.
- Existing backend regression: 1,359 passed, 8 opt-in infrastructure skips; Ruff
  passed. No backend or frontend source was modified by this Step 7-8 increment.
- No experiment container remains running. Existing database services are untouched.

Use `emulation/EXPERIMENT.md` for lifecycle and `ai-engine/README.md` for locked
installation, train/resume/evaluate/infer commands. Start a fresh owner for each
session; lost step responses are not replay-safe and require stop/restart.

## Remaining Acceptance Work

Before calling Step 8 fully achieved, predeclare a larger train-only experiment,
verify learnability on stationary path0/path1 conditions, collect additional fresh
on-policy transitions, and select checkpoints using validation only. Keep the
observed test results as historical evidence and reserve new final test cases.
Require a demonstrable policy response to measured path pressure, not merely
parameter movement. Do not proceed to production or advertise autonomous
optimization based on this smoke checkpoint.
