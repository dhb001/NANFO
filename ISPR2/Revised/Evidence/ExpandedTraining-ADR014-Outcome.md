# Expanded Measured PPO Outcome

## Result

The selected learned policy passed held-out goodput and ICMP RTT improvement
criteria against actual unchanged nominal-cost OSPF in the balanced stationary
2/20 Mbps capacity-impairment benchmark. This is a scoped experimental result,
not a universal OSPF, route-computation-speed, production-safety or autonomy claim.

## Training and Selection

- Real matched FRR/Linux environment with identical graph, addressing, offered
  schedules, shaping and background routing for every method.
- V4 fixes receiver cutoff bias: senders stop; both receivers remain active while
  all 22 leaf queues verify empty in two sweeps, bounded by three seconds. Invalid
  drainage truncates rather than creating a valid loss measurement.
- One compact PPO actor/value model, seed44, fixed learning rate0.003/gamma0.9.
  384 fresh transitions,24 on-policy updates, unique train seeds1600..1695.
- Validation at128/256/384 transitions demonstrated measured directional adaptation
  in both conditions. Final correct-route probabilities approximately0.973/0.968.
- Original stage stopped conservatively before its512-transition selection target.
  An explicitly authorized test-only continuation selected the best existing
  validation-qualified checkpoint before accessing any test. That exception does
  not rewrite the original plan or claim512 transitions were completed.
- No model updates, tuning, validation collection or selection after test access.

Selected checkpoint:
`ai-engine/artifacts/adr014-001/train-06/checkpoint.ptz`

SHA256: `5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`.
Frozen source/runtime/checkpoint metadata are retained and must remain aligned.

## Held-Out Measurement

Each of five methods used all12 reserved seeds3900..3911, four decisions/seed,
with one predeclared shuffled method order. Zero invalid windows, zero retries.
Both reset and control-transition effects are explicitly recorded; table metrics
exclude reset windows. Test collection completed in25.3 minutes and cleaned up.

| Method | Goodput Mbps | ICMP RTT ms | Mean verified-drain loss | Route changes |
| --- | ---: | ---: | ---: | ---: |
| PPO | 5.921743 | 25.154896 | 1.353850% | 6 |
| Constant0 | 3.933795 | 158.371667 | 34.403610% | 0 |
| Constant1 | 4.163708 | 168.454771 | 30.682101% | 12 |
| Heuristic | 5.152365 | 77.230354 | 14.185030% | 29 |
| OSPF | 3.945954 | 104.090458 | 34.202956% | 0 |

PPO minus OSPF paired seed-mean95% Student-t intervals:

- Goodput +1.975789 Mbps [0.663966,3.287611].
- RTT -78.935563 ms [-139.991071,-17.880054].
- Loss -32.849106 percentage points [-54.649609,-11.048602].

The predeclared criterion goodput lowerCI>0 AND RTT upperCI<0 passed. About50.1%
higher mean goodput and75.8% lower RTT, for this scenario mix only. Improvement
comes from avoiding impaired path0; when path1 is impaired and OSPF already uses
healthy path0, results are effectively equal. OSPF costs deliberately do not track
the exogenous impairment; capacity-aware/reconfigured OSPF was not tested.

## Independent Verification

Read-only audit reconstructed the five method metrics and paired intervals from
endpoint counters/ping evidence, matched300 response windows to lab-output JSON,
verified all48 model actions/probabilities/values from actual tensors, train resume
lineage, source/image hashes and selection-before-test chronology. No actor-rule
substitution, test-training leakage or result-invalidating discrepancy was found.
The audit did not claim externally tamper-proof attestation or repeat training.

Two ordinary fresh-process loads reproduced action/value/probability exactly;
warm inference mean0.216..0.222ms. Live inference p95 was1.261ms, whereas total
observation/control/IPC p50 was4.280s versus OSPF harness4.099s. This is NOT faster
SPF computation or faster control-loop response; the benefit is application delivery
and RTT under congestion. Report those timing dimensions separately.

AI305 tests passed; Ruff lint/format passed. All owned services, containers and
campaign processes stopped. Historical failed campaigns and current evidence are
preserved. Artifact directories are ignored by Git and need durable archival.

## Sources and Remaining Limits

- Training record: `ai-engine/ADR014-RESULTS-001.md`.
- Test protocol: `ai-engine/ADR014-HOLDOUT.md`.
- Full results: `ai-engine/ADR014-HOLDOUT-RESULTS.md`.
- Raw test evidence/locked selection: `ai-engine/artifacts/adr014-holdout-001/`.

One trained initialization, one method-session order, shared host timing and12
workload seeds limit generalization and independence assumptions. OSPF/constant0
same-route RTT differs, exposing session/control-timing noise. Multiple comparisons
are not simultaneous95% coverage. Receiver late-packet counts remain unavailable
despite verified drain; UDP echo RTT is not measured. No hidden data correction.

Model qualification here does not install an autonomy provider. Compatible passive
observation, calibrated causal bounds, server-owned execution/recovery authorization
and live safeguarded closed-loop intervention remain OPEN. Existing backend ADR013
assessments of older rejected models are not automatically replaced or relabeled.
