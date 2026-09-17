# NANFO: Presentation and Demonstration Guide

**Prepared for the current presentation from the repository's retained experiments.**

## 1. What to present today

Present **the ADR014 trained PPO model**, its measured routing environment, its
held-out comparison, and the application's independently verified network controls.

Your central statement:

> “NANFO uses a trained actor-critic policy to select between two network paths from
> measured conditions. In our balanced, stationary capacity-impairment benchmark,
> the locked PPO model achieved 5.922 Mbps mean goodput versus 3.946 Mbps for actual
> nominal-cost OSPF, and 25.155 ms mean ICMP RTT versus 104.090 ms. We tested 12
> reserved workload seeds per method, retained the raw observations, and replayed
> the saved model. This is evidence for the defined benchmark, not universal
> superiority or a production-autonomy certificate.”

The selected model is:

```text
ai-engine/artifacts/adr014-001/train-06/checkpoint.ptz
SHA-256: 5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5
```

Later research did **not** replace it. ADR015 missed the replacement thresholds;
ADR016 stopped after 384 additional transitions with no validation or promotion.
Some older README/sprint sections still describe campaigns as active or unqualified:
use each campaign's terminal artifacts and the ADR014 held-out outcome for this talk.

## 2. Commands: prepare the presentation

All commands in this section run from the repository root unless stated otherwise.
On this machine:

```bash
cd /home/DHB/Documents/NANFO
python3 scripts/presentation.py --audit --infer
```

This is the recommended preparation command. It:

1. Checks pinned checkpoint, report, plan, selection and raw-evidence SHA-256 hashes.
2. Reconstructs the archived five-method report with the existing AI evidence parser
   and actual checkpoint tensor replay (`--audit`).
3. Extracts the first recorded reset observation for each impairment direction.
4. Runs the saved model **twice in fresh processes per direction** (`--infer`).
5. Writes an offline slide deck, metrics CSVs, evidence copies and a hash manifest.

It prints a new output directory under `docs/presentation/generated/`. Every run
gets a new directory. It does not overwrite the original campaign or start Docker,
training, traffic, database migrations or network control.

For an easy-to-remember output path, use a **new** directory:

```bash
python3 scripts/presentation.py --audit --infer \
  --output /tmp/opencode/nanfo-presentation-today
xdg-open /tmp/opencode/nanfo-presentation-today/slides.html
```

If that output directory already exists, open it or choose another name. The script
refuses to overwrite a previous presentation run. A failed build retains
`verification.json` with `pack_complete=false` and its error.

### Files to take to the presentation

| File | Use |
| --- | --- |
| `slides.html` | Self-contained offline deck; charts, tables and speaker cues |
| `PRESENTATION_GUIDE.md` | This detailed speaking script and technical appendix |
| `metrics.csv` | Five-method measurements for Excel/LibreOffice |
| `paired-seeds.csv` | Per-seed paired values/differences, with metric units in names |
| `learning-curve.csv` | Validation progression; not a synthetic training curve |
| `inference-demo.json` | Actual fresh-process outputs, when `--infer` was requested |
| `history-path0.json`, `history-path1.json` | Original recorded input evidence for the demo |
| `verification.json` | Exactly which checks ran and whether the pack completed |
| `manifest.json` | Byte sizes and SHA-256 hashes of generated/copied files |
| `evidence/` | Checkpoint, raw traces, summaries, original reports and provenance |

**Open the HTML in a browser.** Use Previous/Next or left/right arrows, F11 for
fullscreen, and Speaker notes to hide/show the cues. Use **Print / Save PDF** to
create a PDF backup; landscape is configured in print CSS. Check print preview
before saving because browser scaling can change page breaks. No CDN or internet
connection is needed for the deck.

Copy the **whole generated folder** to a USB drive. The HTML and CSVs work on another
computer without Python. Rerunning inference there needs the compatible AI runtime
and repository; copying the deck alone does not install them.

For automatic PDF export on this machine, where the frontend Playwright/Chromium
dependencies are installed, add `--pdf`:

```bash
python3 scripts/presentation.py --audit --infer --pdf
```

This adds `slides.pdf` (speaker cues hidden) and `slides-preview.png`. If Chromium
is unavailable, build without `--pdf` and use the browser's Print / Save PDF button.

### If you only need slides immediately

```bash
python3 scripts/presentation.py
```

This uses standard Python and checks the pinned evidence bytes. It labels fresh
inference and full raw replay as **not requested**, rather than claiming they ran.
The metric values still come from the retained measured campaign.

### If the AI environment is missing

The current machine has a working `ai-engine/.venv`. On a fresh installation:

```bash
cd /home/DHB/Documents/NANFO/ai-engine
uv sync --locked --dev
cd /home/DHB/Documents/NANFO
python3 scripts/presentation.py --audit --infer
```

This requires dependency downloads on a fresh machine. AI uses Python 3.12 and
CPU PyTorch 2.8.0; do not install it into the backend or Ryu environment.
Checkpoint compatibility failures are meaningful: use the retained matching
runtime/source, rather than editing a hash or weakening the loader.

## 3. Suggested 15-minute talk

| Time | Deck sections | What to do |
| --- | --- | --- |
| 0:00–1:00 | 1 | State the problem and the scoped result |
| 1:00–3:00 | 2–3 | Explain the two paths and distinguish application vs model lab |
| 3:00–5:30 | 4–5 | Explain observation, actor, critic, action and reward |
| 5:30–7:00 | 6–7 | Explain training, selection and held-out protocol |
| 7:00–10:00 | 8–10 | Show measured comparisons, uncertainty and control cost |
| 10:00–12:00 | 11 | Run the short inference demo below |
| 12:00–13:30 | 12 | Show previously verified application/network behavior |
| 13:30–15:00 | 13–14 | Explain failed experiments, limits and conclusion |

For a five-minute presentation: use sections 1, 4, 7, 8, 11 and 14. Keep the
remaining sections for questions.

### Opening script

“Traditional routing follows its configured route costs. If a path loses effective
capacity but those costs stay unchanged, packets can continue taking the congested
path. My project investigates whether a policy trained on measured network state
can choose a more useful path. I first built real telemetry, safe manual actions
and recovery, then trained a small PPO actor-critic. Today I will show the model,
the experimental protocol, the actual results and a reproducible inference demo.”

### Architecture script

“There are two related experimental layers. The application uses an isolated
Mininet/Open vSwitch/Ryu lab, with an independent durable worker and readback-based
verification. For a fairer learning comparison, the model benchmark uses matched
Linux routing and real FRR OSPF namespaces. All methods share the same graph,
capacity impairment, addressing, traffic schedule and background routing. I do not
attribute the application's OpenFlow results to PPO training.”

### Model script

“The selected policy has 16 inputs. Thirteen are scaled operational metrics;
one indicates RTT availability and two encode the previous route. The actor
outputs two route probabilities, and the critic estimates expected return.
During training we sample actions and update both networks using clipped PPO
and generalized advantage estimation. At evaluation we choose the highest-logit
route deterministically. The model does not receive the scenario label or seed.”

### Results script

“The final comparison used 12 previously reserved seeds for each of five methods.
There are four decisions per seed, so 48 decision windows per method. The mean
goodput increased by about 50.1% and the mean ICMP RTT fell by about 75.8% relative
to nominal-cost OSPF. The seed-paired confidence intervals passed the predefined
criterion. The gain comes from avoiding OSPF's impaired preferred path. When
OSPF already selects the healthy path, performance is effectively the same.”

### Closing script

“The contribution is an evidence-backed chain from real network measurements to
trained route selection, measured outcomes and reproducible checkpoints. The
model works for the tested fixed-topology task. The next requirements are broader
repeated evaluation, justified safety bounds and a compatible governed autonomous
deployment. I am not presenting this benchmark as a finished production controller.”

## 4. Two-minute model demonstration

Build the pack with `--infer` before the presentation. Keep two terminals ready:
one with the command below, and one with the generated folder/slide deck open.
If using the named output directory from Section 2:

```bash
cd /home/DHB/Documents/NANFO
ai-engine/.venv/bin/python -m nanfo_routing infer \
  --checkpoint ai-engine/artifacts/adr014-001/train-06/checkpoint.ptz \
  --history /tmp/opencode/nanfo-presentation-today/history-path0.json
```

Say: “This is an actual forward pass of the saved model on a recorded, measured
observation where path 0 was impaired.” Point to:

- `policy_sha256`: the same selected checkpoint.
- `evidence.path_capacity_mbps`: the recorded capacities, expected `[2,20]` here.
- `action`: route 1 is the learned response in this recorded condition.
- `probabilities`: actual neural output, not a hand-coded route explanation.
- `execution: "not_applied"`: this command performs inference only.

Then run the opposite direction:

```bash
ai-engine/.venv/bin/python -m nanfo_routing infer \
  --checkpoint ai-engine/artifacts/adr014-001/train-06/checkpoint.ptz \
  --history /tmp/opencode/nanfo-presentation-today/history-path1.json
```

Explain: “The recorded capacity condition is now reversed. The same weights select
route 0. These are genuine stored measurements; I have not invented a favorable
input. This demo reproduces inference. The original held-out experiment, whose raw
traces are retained, is the evidence that applying the routes changed traffic.”

Rerunning a command should reproduce the action, probabilities and value exactly.
Runtime fields may vary with machine load. If you use the default timestamped
output directory, replace the history paths accordingly.

For a minimal command without generating a pack:

```bash
ai-engine/.venv/bin/python -m nanfo_routing infer \
  --checkpoint ai-engine/artifacts/adr014-001/train-06/checkpoint.ptz \
  --history ai-engine/artifacts/adr014-holdout-001/test-ppo/last-history.json
```

That last historical observation produces action 0 with probabilities approximately
`[0.97227234, 0.02772770]` in the current compatible runtime. It is a different
recorded observation from the original timing study, so its probabilities need
not equal the timing-study values.

### If something fails on stage

Open `inference-demo.json` from your successfully prepared pack and explicitly say
it is the preparation-time output. Show `verification.json` and the checkpoint
identity. Continue with the offline deck. Do not start training or change model
files to make the demo look successful.

## 5. Exact selected model specification

| Item | Actual selected checkpoint |
| --- | --- |
| Algorithm | Categorical PPO actor-critic, CPU PyTorch |
| Architecture | Separate actor and critic: Linear(16,32), Tanh; heads 32→2 and 32→1 |
| Trainable parameters | 1,187 total: actor 610, critic 577 |
| Input history | One stationary observed frame; 16 values, **not** the older V2 147-input model |
| Actions | 0: access1→dist1→access2; 1: access1→dist2→access2, h1→h3 with return path |
| Observed numeric features | Utilization×2, queue×2, RTT, loss, goodput, target offered rate, background rate, time since change, actual offered rate, capacity×2 |
| Additional input values | RTT available; previous route one-hot×2 |
| Scaling | `log1p(value/reference)`; frozen feature-specific reference scales |
| Topology | Fixed campus-small graph and action map in contract; adjacency is metadata, not a learned GNN input |
| Actor output | Two logits, categorical probabilities; deterministic argmax during evaluation |
| Critic output | Expected discounted return estimate, not safety confidence |
| Optimizer | Adam, learning rate 0.003 |
| Discount / GAE lambda | 0.9 / 0.95 |
| PPO clip / entropy coefficient | 0.2 / 0.01 |
| Value loss coefficient / gradient norm cap | 0.5 / 0.5 |
| Epochs / rollout | 4 update epochs / 16 transitions |
| Configured minibatch | 32; actual 16-transition rollout yields a 16-sample batch |
| Initialization seed | 44 |
| Training completed | 384 fresh transitions, 96 episodes, 24 updates, six resume blocks |
| Train seeds | 1600–1695 |
| Validation seeds | 2700–2707, reused at 128/256/384 transitions |
| Final test seeds | 3900–3911, 12 per method |
| Measurement target / horizon | 2 seconds requested per window / 4 decisions per episode |
| Checkpoint contents | Weights, optimizer/RNG, config, features/action map, versions, seeds, spec and source hashes |

The original ADR011/V2 documents describe earlier designs. For this model, the
checkpoint manifest and ADR014 records are authoritative. Do not mix their feature
dimensions, rewards, workloads or test results.

### Reward formula

```text
r = min(delivered_goodput / actual_sent_rate, 1)
    − 0.2 × (ICMP_RTT_ms / 50)
    − 1.0 × loss_fraction
    − 0.1 × max(path_utilization_fraction)
    − 0.1 × (max(path_queue_packets) / 100)
    − 0.05 × actual_route_change
```

Positive delivery reward is balanced against delay, loss, utilization, backlog and
route changes. Reward is dimensionless and per decision. Missing instrumentation
invalidates a transition. A verified zero-reply outage retains null measured RTT
and has a separately labeled censored-delay penalty; it is not fabricated latency.
The final held-out campaign had zero observed service outages.

PPO maximizes a clipped policy-ratio objective, with value mean-square error and
entropy regularization. Clipping limits the update objective; it is not a proof
of stability, convergence or network safety.

## 6. How metrics were actually measured

| Metric | Definition / source | Interpretation |
| --- | --- | --- |
| Goodput, Mbps | Final foreground delivered bytes ×8 / actual sender duration /1e6 | Useful endpoint delivery; not port capacity or requested traffic rate |
| Offered load, Mbps | Actual sender bytes / actual sender duration, with unit conversion | Kept distinct from configured target rate |
| ICMP RTT, ms | Concurrent foreground ping during offered traffic | Round-trip probe latency, not one-way delay, UDP echo RTT or inference time |
| Verified-drain loss | `(sent packets − received packets) / sent packets` after verified drain | Finite experiment endpoint loss; no fabricated late-arrival counts |
| Utilization | Interface counter differences over measured intervals, normalized by actual shaped capacity | Per-path pressure; recorded interval may differ from sender lifetime |
| Queue occupancy | Instrumented Linux leaf netem backlog samples | Sampled peak backlog, not OpenFlow's instantaneous queue-depth statistic |
| Route changes | Verified actual route transitions | Reset starts route 0; first switch to route 1 counts |
| Inference time | Neural-policy computation timing | Separate from load, parsing, control, IPC and observation |
| Control/readback | Apply/verify duration in harness | Does not measure OSPF SPF compute time |

V4 measurement stops senders and keeps receivers alive while **all 22 leaf queues**
are verified empty in two sweeps, within a three-second bound. Incomplete drain
invalidates the measurement. Delivered bytes include service during control/drain;
the denominator is the actual sender duration, not drain time. Raw intervals and
endpoint totals are retained so this definition can be examined.

The model receives actual shaped capacities as features. Therefore the experiment
demonstrates routing given available capacity observations; it does not demonstrate
discovering hidden capacity without instrumentation.

## 7. Final held-out results

**Source:** `ai-engine/artifacts/adr014-holdout-001/outcome.json` and
`ai-engine/ADR014-HOLDOUT-RESULTS.md`.

| Method | Mean goodput Mbps | Mean ICMP RTT ms | Mean window loss | Route changes /48 decisions | Mean reward |
| --- | ---: | ---: | ---: | ---: | ---: |
| PPO | 5.921743 | 25.154896 | 1.353850% | 6 | 0.788925 |
| Actual OSPF | 3.945954 | 104.090458 | 34.202956% | 0 | -0.207409 |
| Heuristic | 5.152365 | 77.230354 | 14.185030% | 29 | 0.266397 |
| Constant route 0 | 3.933795 | 158.371667 | 34.403610% | 0 | -0.429802 |
| Constant route 1 | 4.163708 | 168.454771 | 30.682101% | 12 | -0.447769 |

PPO selected 24 decisions per route, choosing the healthy path in each direction.
The heuristic used utilization plus queue pressure with 0.15 hysteresis. It changed
routes more frequently in this benchmark. OSPF was the actual FRR protocol, using
frozen nominal-bandwidth costs and a single preferred next hop through dist1.

### Statistical result

PPO minus actual OSPF, paired two-sided 95% Student-t intervals across **12 seed means**:

| Metric | Mean delta | 95% interval |
| --- | ---: | --- |
| Goodput | +1.975789 Mbps | [0.663966, 3.287611] |
| ICMP RTT | -78.935563 ms | [-139.991071, -17.880054] |
| Loss | -32.849106 percentage points | [-54.649609, -11.048602] |

Predeclared success required goodput's lower interval bound >0 **and** RTT's upper
bound <0, with all 12 pairs. Both passed. Approximately **50.1% higher goodput** and
**75.8% lower RTT** refer to the aggregate mean across this balanced scenario mix.

Per-window average loss is different from packet-weighted aggregate loss:

- PPO: 79,769 sent /78,413 received; packet-weighted loss **1.699908%**.
- OSPF: 70,843 sent /46,503 received; packet-weighted loss **34.357664%**.

Do not substitute one definition into a table labeled with the other. Average
window PDR is `100% − mean window loss`; pooled PDR uses the pooled packet totals.
Different sender durations/control overhead explain differing sent totals despite
matched target workloads.

### What the two scenario directions show

- **Path 0 impaired:** PPO avoids the nominal OSPF route; mean goodput delta
  +3.951437 Mbps and RTT delta -157.869625 ms.
- **Path 1 impaired:** both methods use healthy route 0; goodput delta about
  +0.000141 Mbps and RTT delta about -0.001500 ms, with intervals crossing zero.

This is not evidence that PPO improves a route OSPF already chooses correctly.
Capacity-aware or reconfigured OSPF was not a comparator.

### Timing and cost

| Timing | Measured result |
| --- | --- |
| Live PPO neural inference p50 /p95 /p99 | 0.956 /1.261 /1.607 ms |
| Warm repeated inference mean | 0.216–0.222 ms |
| Fresh Python process end-to-end | 2.174–2.242 seconds, including imports and validation |
| PPO control/readback p50 /p95 | 173.487 /944.242 ms |
| OSPF harness control/readback p50 /p95 | 48.095 /49.593 ms |
| PPO observation/control/IPC p50 /p95 | 4.280 /5.304 seconds |
| OSPF observation/control/IPC p50 /p95 | 4.099 /4.528 seconds |

Do not say “PPO routes faster than OSPF.” The measured improvement is packet
delivery and RTT under impairment. PPO performed six changes versus OSPF's zero;
the observation/control loop was not faster.

## 8. Previous experiments and development results

Keep this section for questions about how the model developed.

| Stage | What actually happened | Conclusion |
| --- | --- | --- |
| Steps1–2 | Effective TypeScript checks, honest result/provenance labels, tenant/session security; historical 1,112 backend /188 frontend /24 browser tests | Trustworthy foundation, not an AI result |
| Steps3–4 | Mininet/OVS/Ryu, real discovery/counters/queues/probes and API→DB→WebSocket verification; 2,672 unique observations in the earlier campaign | Actual measured network integration |
| Steps5–6 | Manual reroute/multipath/shaping/policing/restore; worker/outbox/restart/cancellation checks | Real control and recovery |
| V2 PPO | 48 transitions, 3 updates; weights changed but deterministic route remained route1 | Pipeline worked; useful adaptive model not established; FRR comparison was not matched |
| ADR013 | Two32-transition pilots, 64 total, 220 measurement windows; both chose route0 throughout validation | No policy qualified; reserved tests untouched; heuristic performed better |
| ADR014 training | 384 transitions, 24 updates, correct measured directionality; initial stage stopped before512 target | Validation-qualified model; selection minimum initially not met |
| ADR014 test-only continuation | Explicit minimum waiver, selected existing checkpoint before test, all12 reserved seeds×5 methods completed | Scoped held-out improvement established |
| ADR015 refinement | 512 additional transitions, 32 updates; reward0.66638→0.67951, changes10→8 | +0.01313 reward and20% switch reduction missed >0.02/25% gates; no replacement/test admission |
| ADR016 refinement | Terminal status:384 additional transitions,12 updates, stopped by conservative remaining-budget rule | No validation, no promoted model; incumbent unchanged |
| Steps13–14 | Real report artifacts/measured alerts; 22 acceptance cases passed,9blocked | Partial acceptance, not complete release certification |

Do not combine transitions from independent/rejected models into the selected
checkpoint's training count. ADR014 used **384**, not the sum of every campaign.

### Selected-model validation progression

| Transitions | PPO updates | Validation reward | P(correct), path0 | P(correct), path1 |
| --- | ---: | ---: | ---: | ---: |
| 128 | 8 | 0.788556 | 0.614849 | 0.590005 |
| 256 | 16 | 0.788710 | 0.916344 | 0.918060 |
| 384 | 24 | 0.792639 | 0.972966 | 0.968469 |

These are reused **validation** results, not independent test replications.
Increases in correct-route probability show policy learning, but a probability is
not calibrated safety confidence. A synthetic pressure-swap diagnostic did not
pass every direction; it was predeclared diagnostic rather than measured reward
evidence. The real measured directional results are the relevant qualification.

### Application/network results to show alongside the model

The Step5–6 authenticated API→independent worker→lab campaign measured:

| Operation | Measured result |
| --- | --- |
| Baseline TCP | 18.805 Mbps |
| Reroute TCP | 18.689 Mbps, actual forward/return counters verified |
| SELECT multipath TCP | 37.798 Mbps, both buckets exercised |
| 5 Mbps shaping | 4.758 Mbps classified /17.713 Mbps unclassified |
| 5 Mbps policing | 4.870 Mbps classified /17.713 Mbps unclassified |
| Restore after shape /police | 17.712 /17.708 Mbps |
| Concurrent duplicate requests | Four requests produced one durable execution |
| Fault recovery | Worker death, missing result, deadline compensation, old-policy cancellation, outbox replay passed |

These are different protocols/workloads from the model's approximately6 Mbps
foreground UDP test. Do not claim the model's5.922 Mbps is a regression against
the manual lab's18.805 Mbps TCP baseline; that would compare different experiments.

Latest documented application gate: **2,028 backend tests passed,89 opt-in skips;
487 frontend tests and41 browser tests passed**. Earlier Step5–6 gate was1,359
backend,241frontend,27browser. These are milestone records, **not freshly rerun
counts for the current uncommitted deployment changes**.

Step14 final acceptance: **22 cases passed,0failed after fixes/retests,9blocked**.
Some cases use modeled or fixture evidence; not all22 are physical experiments.
The initial failures remain preserved. Blocked cases include broader physical
traffic matrices, larger topology, repeated held-out/DRL+safety and power control.

## 9. Recheck commands and optional live network demonstration

### Fast, relevant checks before the talk

```bash
cd /home/DHB/Documents/NANFO
python3 scripts/presentation.py --audit --infer
```

For the AI test suite (offline fixtures/unit/replay tests; no new network trial):

```bash
cd /home/DHB/Documents/NANFO/ai-engine
.venv/bin/python -m pytest tests -q
```

For frontend engineering checks, in a separate terminal:

```bash
cd /home/DHB/Documents/NANFO/frontend
npm run typecheck
npm run lint
npm run test
```

For browser tests, run on their own after the above commands finish:

```bash
npm run test:e2e -- --retries=0
```

For backend regression (separate backend runtime):

```bash
cd /home/DHB/Documents/NANFO/backend
env -u VIRTUAL_ENV -u CONDA_PREFIX poetry run pytest tests -q --no-cov
```

Record the output you actually obtain. Later uncommitted deployment work may affect
the current gate; do not substitute an older pass count for a current failure.

### Optional: regenerate real manual-control evidence

Use this **before** the talk if Docker/the lab are ready and no other experiment
owns the lab. It is substantially longer and more environment-dependent than the
inference replay. It exercises real isolated network mutation and disposable
infrastructure; it is **not** a PPO training/evaluation command:

```bash
cd /home/DHB/Documents/NANFO/backend
env -u VIRTUAL_ENV -u CONDA_PREFIX PYTHONPATH=..:. \
  poetry run python scripts/verify_execution.py --live
```

The verifier writes its result path and returns failure for an unsuccessful check.
Use its new artifact if successful. It needs Docker access, existing backend
dependencies/database credentials, image availability and an available lab slot.
It can refuse occupied resources rather than taking them over. See
`backend/app/modules/intent/README.md` for prerequisites. Do not remove journals,
stop unrelated services or migrate the shared application just to run this demo.

### Why not rerun the old training/holdout command today?

The completed test ledger is intentionally one-shot. The current emulation source
has also evolved. The historical command:

```text
ai-engine/.venv/bin/python ai-engine/scripts/summarize_adr014_holdout.py
```

currently rejects its full release check with `released lab source changed; wait
for new completed handoff`. The presentation script's `--audit` instead calls the
existing archive report parser with the selected checkpoint and compares its
reconstructed fields to the pinned saved report. This checks **archived raw/tensor
consistency**, without asserting that today's lab is the old frozen release or
authorizing new test collection. It does not weaken the historical launch guard.

New live learning experiments need a compatible frozen release and new predeclared
protocol. Reusing the completed test set for model tuning would undermine its
held-out interpretation. Today's recommended demo uses the actual saved model.

## 10. Likely examiner questions

**“Is this really reinforcement learning or a routing rule?”**

The actor/critic are trained PyTorch tensors using sampled on-policy transitions,
GAE and the clipped PPO objective. The report replays actual checkpoint outputs
against raw recorded decisions. Training traces retain losses, weights and update
lineage. The route actions are predefined; their selection is learned. The simple
fixed-topology task could also be approached by stronger hand-designed rules;
this experiment does not prove DRL is necessary.

**“Why PPO?”**

It supports the small categorical action space and separates policy learning from
value estimation. Its clipped objective limits large policy updates, and its
implementation is auditable at this scale. Choice of PPO does not confer formal
network stability or guarantee that it outperforms other algorithms.

**“Why only two actions?”**

To first validate the complete measured-learning loop with interpretable routes.
The broader application has more manual operations, but this checkpoint is trained
only for the fixed two-path choice. Topology/action-space expansion needs new work.

**“Is OSPF genuine, and is the comparison fair?”**

Yes, the baseline runs actual FRR OSPF on matched Linux router namespaces. Methods
share exogenous capacities/demand/background placement. OSPF's costs are fixed at
nominal bandwidth and do not track the introduced impairment. This is a deliberately
scoped comparison, not the best possible capacity-aware OSPF configuration.

**“Did you train on the test data?”**

ADR014 used train1600–1695, validation2700–2707, test3900–3911. Selection preceded
test access and no test-driven updates occurred. The original512-transition
selection minimum was explicitly waived before this test-only continuation; that
exception is recorded rather than hidden. Test results remain single-campaign evidence.

**“How statistically convincing is it?”**

Both predeclared paired confidence-interval conditions passed across12 seed means.
However, there is only one trained initialization and one shuffled method-session
order. Shared-host timing, noisy RTT and strongly different impairment directions
limit the inference. Multiple reported intervals are not simultaneous95% coverage.
Repeated counterbalanced runs and new topologies are still needed.

**“Why does OSPF have a different RTT from constant route0?”**

They selected the same nominal route and had similar goodput/loss, but ran at
different times and with different control/readback overhead. RTT variation shows
why timing noise/session-order effects must be disclosed. We did not replace one
result with the other or retry an unfavorable run.

**“Does the policy act proactively?”**

This experiment selects from observed stationary capacity/pressure. It does not
demonstrate forecasting or intervention before a separately defined congestion
threshold. Proactive behavior requires its own measurable criterion and evaluation.

**“Is the neuro-adaptive stability mechanism proved?”**

This PPO benchmark does not establish a Lyapunov or network-stability guarantee.
Backend safety/readiness mechanisms have explicit assumptions and blocked gates;
the selected benchmark result is not a justification to activate unsupervised control.

**“Can the application actually change a network?”**

Yes, manual authorized isolated-lab actions were exercised through HTTP, a durable
worker and actual switch configuration, with readback, traffic checks and verified
restoration. A queued request is not labeled completion. Ordinary configuration
completion is distinct from independently measured traffic-effect verification.

**“Is everything finished?”**

The prototype has substantial verified functionality, including measured telemetry,
manual control/recovery, trained policy evidence, evaluator/operator workflows,
reports and measured alerts. Full physical acceptance, broadly validated safeguarded
autonomy and the latest packaging/recovery campaign remain incomplete. Plugins are
metadata registry entries and energy outputs are estimates, not executed plugins
or measured power savings.

## 11. Evidence index

| Claim | Repository source |
| --- | --- |
| Selected-model outcome /scope | `docs/project/ExpandedTraining-ADR014-Outcome.md` |
| Full holdout results /intervals /timing | `ai-engine/ADR014-HOLDOUT-RESULTS.md` |
| Original training /selection shortfall | `ai-engine/ADR014-RESULTS-001.md` |
| Test-only protocol /exception | `ai-engine/ADR014-HOLDOUT.md` |
| Raw test /plan /selection /checkpoint identities | `ai-engine/artifacts/adr014-holdout-001/` |
| Original train /validation /checkpoint | `ai-engine/artifacts/adr014-001/` |
| Earlier rejected pilots | `ai-engine/ADR013-RESULTS-001.md` |
| Refinement not promoted | `ai-engine/ADR015-RESULTS-001.md` |
| Later refinement terminal status | `ai-engine/artifacts/adr016-001/status.json` |
| Real manual-control tests | `docs/project/ManualExecution-Step5-Step6.md` |
| Latest recorded acceptance/gates | `docs/project/ModulesAcceptance-Step13-Step14.md` |
| Current work and deployment limits | `docs/project/CurrentSprint.md` |

Campaign artifact directories are Git-ignored. Keep the generated pack and original
raw archive backed up; the documents alone do not preserve the experiment bytes.
Hashes establish consistency with retained local evidence, not external attestation.

## 12. Final rehearsal checklist

- Generate the pack with `--audit --infer`; check `pack_complete=true`.
- Open slides offline, set fullscreen, hide notes, rehearse the15-minute sequence.
- Save a PDF backup and copy the entire folder to a USB drive.
- Run both inference commands once; enlarge terminal font and keep outputs visible.
- Memorize **5.922 vs3.946 Mbps;25.155 vs104.090 ms;12paired seeds;384transitions**.
- State the OSPF cost/impairment scope alongside the percentage gains.
- Keep the failed-campaign history and statistical caveats ready for questions.
- If displaying the application, confirm its execution mode and whether the shown
  telemetry is current measured, historical measured, modeled or synthetic.
- Use the saved inference/PDF fallback if the presentation machine misbehaves.
- Finish with the measurable contribution and next experiment, rather than an
  unqualified “fully autonomous production system” claim.
