# ADR014 Holdout Results

**Completed all five methods once on all12 originally reserved seeds.** The locked
PPO checkpoint passed the predeclared paired-seed goodput and ICMP RTT improvement
criterion against actual unchanged OSPF, within the stated impaired-capacity scope.
No additional training, validation collection, hyperparameter changes or selection
after test access occurred. No production safety or autonomy authorization follows.

## Selection And Provenance

- Selected existing384-transition/24-update model, highest reconstructed qualified
  validation reward among128/256/384; lower transitions was the frozen tie-breaker.
- Checkpoint: `artifacts/adr014-001/train-06/checkpoint.ptz`.
- Checkpoint SHA256: `5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`.
- Tensor payload SHA256: `3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967`.
- Test plan SHA256: `0763dd582933da18e20b7bf879a37c96bb6414faf8ab66cade8bc2b02a855b28`.
- Selection SHA256: `654a411f16b7607c9ddd40d6a4d0c8dcdb9ec8b2c6b1f20eac5a5070808ca180`.
- Recorded image: `sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff`.
- Original source snapshot, runtime, plan, checkpoints and evidence hashes checked
  before launch, each policy and after collection. Original test attempts: zero.
- The new parent-authorized selection explicitly waived the original512 minimum
  for this test-only stage. Original training outcome and plan were not rewritten.

## Actual Test

Seeds3900..3911, six per stationary direction, four decisions/episode, requested
two-second windows. Exactly48 decision windows/method;240 decisions plus60 resets.
Reset windows are excluded from the metrics below. No invalid measurement or
retry; no service outage in any method. All returned V4 drain evidence passed.

Order frozen using random seed9142026: PPO, constant1, constant0, heuristic, OSPF.
Collection elapsed1509.34 seconds; terminal stage elapsed1520.68 seconds, including
audits/cleanup, under3600-second cap. Service inactive/dead, successful result;
exact campaign-label container inventory empty. No leftover campaign process.

| Method | Mean Goodput Mbps | Mean ICMP RTT ms | Mean Verified-Drain Loss | Route Changes | Mean Reward |
| --- | ---: | ---: | ---: | ---: | ---: |
| PPO | 5.921743 | 25.154896 | 1.353850% | 6 | 0.788925 |
| Constant0 | 3.933795 | 158.371667 | 34.403610% | 0 | -0.429802 |
| Constant1 | 4.163708 | 168.454771 | 30.682101% | 12 | -0.447769 |
| Heuristic | 5.152365 | 77.230354 | 14.185030% | 29 | 0.266397 |
| Actual OSPF | 3.945954 | 104.090458 | 34.202956% | 0 | -0.207409 |

PPO chose24 decisions per route: route1 when path0 was impaired, route0 when path1
was impaired. Its six changes were the first decision in each path0 episode from
reset's route0. OSPF remained route0 throughout. Transition losses remain included.

Foreground endpoint totals (decision windows): PPO79769 sent/78413 received;
OSPF70843 sent/46503 received. Packet-weighted loss is1.699908% versus34.357664%,
distinct from the mean per-window loss in the table. Sender duration includes
control, which explains unequal sent totals despite matched offered schedules.
Goodput divides final delivered bytes by actual sender duration, not drain time.
Late-delivered packet counts remain unavailable/null, never inferred from queues.

## Paired Findings

Deltas are PPO minus comparator. Two-sided95% Student-t intervals use12 paired
seed means, each formed from four decisions. No packet/window pseudo-replication.

| Comparator | Goodput Delta Mbps [95% CI] | ICMP RTT Delta ms [95% CI] | Loss Delta Percentage Points [95% CI] |
| --- | --- | --- | --- |
| OSPF | +1.975789 [0.663966, 3.287611] | -78.935563 [-139.991071, -17.880054] | -32.849106 [-54.649609, -11.048602] |
| Constant0 | +1.987948 [0.668060, 3.307836] | -133.216771 [-226.624095, -39.809447] | -33.049760 [-54.984082, -11.115438] |
| Constant1 | +1.758035 [0.588921, 2.927149] | -143.299875 [-237.080621, -49.519129] | -29.328252 [-48.807901, -9.848602] |
| Heuristic | +0.769377 [0.257290, 1.281465] | -52.075458 [-86.468163, -17.682753] | -12.831180 [-21.360363, -4.301998] |

The predeclared OSPF criterion passed: goodput lower CI>0 and RTT upper CI<0,
with all12 pairs available. Approximate mean changes:50.1% higher goodput and75.8%
lower RTT versus OSPF. Reward delta+0.996334,95% CI[0.323951,1.668717].
Route-change rate increased by0.125/decision,95% CI[0.042047,0.207953]. This is
an explicit control-cost tradeoff, not a claim of free improvement.

### Scenario Scope

On six **path0-impaired** seeds, PPO switches away from the nominal OSPF route:
goodput delta+3.951437 Mbps,95% CI[3.844220,4.058654]; RTT delta-157.869625 ms,
95% CI[-234.711791,-81.027459].

On six **path1-impaired** seeds, both use unaffected route0: goodput delta+0.000141
Mbps,95% CI[-0.000257,0.000539]; RTT delta-0.001500 ms,
95% CI[-0.010225,0.007225]. No detectable advantage in that direction; both had
zero measured loss. The overall gain comes from avoiding the degraded OSPF route,
not beating OSPF when its route is already suitable.

This is a balanced stationary2/20Mbps impairment experiment against **frozen nominal
bandwidth OSPF costs that do not track the impairment**. It does not demonstrate
superiority over capacity-aware/reconfigured OSPF or across arbitrary networks.

### Uncertainty

One shuffled session order is not a counterbalanced repeated experiment. RTT is
noisy: constant0 and OSPF had similar goodput/loss and the same route but different
mean RTT, with distinct control timings and session times. Random order does not
remove wall-time drift or instrumentation/control-overhead confounding. The small
seed-level intervals assume approximately normal independent seed deltas; the
balanced mixture also has strong scenario heterogeneity. Multiple reported95%
intervals do not imply simultaneous95% coverage. No unfavorable result was retried.

## Inference And Timing

Two independent fresh processes loaded the exact checkpoint and existing measured
history; action0, value3.2172513008117676 and probabilities
`[0.9718289375305176, 0.028171034529805183]` matched exactly across both processes,
all100 warm repeats/process and the original frozen CLI. Raw holdout reconstruction
also reproduced all48 actual PPO actions and probabilities exactly.

- Fresh process wall time:2.24246s /2.17448s (Python/import/verification included).
- Model load:7.950ms /7.397ms.
- First inference:0.904ms /0.980ms.
- Warm mean over100 repeats:0.216ms /0.222ms.
- Live PPO inference p50/p95/p99:0.956ms /1.261ms /1.607ms.
- PPO control/readback p50/p95:173.487ms /944.242ms.
- OSPF control/readback p50/p95:48.095ms /49.593ms.
- PPO observation/control/IPC p50/p95:4.280s /5.304s.
- OSPF observation/control/IPC p50/p95:4.099s /4.528s.

These timings distinguish neural computation from lab control/measurement overhead;
they are not an end-to-end production forwarding latency claim. RTT is ICMP only.

## Evidence And Verification

Directory: `artifacts/adr014-holdout-001/` retains immutable plan/selection/runner,
test ledger, all five raw JSONL traces/summaries, exact container ownership records,
command logs, `inference-reproducibility.json`, `test-report.json` and `outcome.json`.
Original `artifacts/adr014-001/` was not modified by this continuation.

Raw evidence SHA256:

| Method | SHA256 |
| --- | --- |
| PPO | `107077a6f206895acb5c26017167f86ce6985a102834f783ad7b7d472d72a8ed` |
| Constant0 | `5d9fd8757c966b7204190c6679b38780cc30373520c81ab496b4810a4567b739` |
| Constant1 | `ae5e0c10bf1603b1217315061e6f9368b13698f3a7159b6348f6b745819886f0` |
| Heuristic | `b81c1aa8b1faa8c3ee1cda9db26592b43b7f9db047b8f4d40aa9cd0ebd439ef4` |
| OSPF | `e3a380871d8a5be697bec6864981867bdf2438ecdb32462bd8e3c9fd5b157683` |

305 tests passed before launch; lint/format passed. Post-run independent report
reconstruction matched every saved field and original artifact/model/source hashes.
Read-only reproducible analysis, no new measurements:

```bash
.venv/bin/python scripts/summarize_adr014_holdout.py
```

Exact launch/status/stop/cleanup commands: [ADR014-HOLDOUT.md](ADR014-HOLDOUT.md).
All manual changes are under `ai-engine/**`, outside the frozen model package.
