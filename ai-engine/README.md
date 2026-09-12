# Measured Routing PPO

## Current ADR013 V3

Post-campaign review corrected seed/workload evidence validation and clarified
receiver-cutoff delivery deficit. See [ADR013-REVIEW-CORRECTIONS.md](ADR013-REVIEW-CORRECTIONS.md)
for the preserved historical gate, pressure-swap flaw and current source-drift
rejection of old checkpoints. Historical results/artifacts are not rewritten.

The first parent-authorized measured v3 campaign has now completed: **both pilots
unqualified**, 1010.5/1200 seconds, 220 valid measured windows, no test access,
all owners cleaned. See [ADR013-RESULTS-001.md](ADR013-RESULTS-001.md) for actual
results, uncertainty, durable checkpoint identities and open acceptance gates.

The active client now uses **v3 matched stationary Linux/FRR semantics**, a compact
16-input policy and separate 32-unit actor/critic. V2 checkpoints cannot load.
See [ADR013-READINESS.md](ADR013-READINESS.md) for the frozen 20-minute plan, exact
pending commands, evidence-gated qualification/selection and subprocess inference.
No live campaign is authorized by this implementation. Lab release and parent
approval remain required. The two-hour supervisor and v1/v2 commands/results below
are historical and must not be launched for this campaign. Artifacts are unchanged.

Standalone operator-only ADR-011 experiment. CPU PyTorch is separate from the
Mininet/Ryu environment. No backend, frontend, production inference endpoint,
autonomous worker, or Step 9 safety filter is installed here.

## Two-Hour Supervisor

See [SUPERVISOR.md](SUPERVISOR.md) for the explicit operator-only two-hour
`python -m nanfo_routing.supervisor run|status|stop|cleanup` CLI, frozen seed plan,
train-only constant-policy calibration, validation early stopping, private
ID/label-owned containers, and parent-owned systemd command. Implementation does
not launch it. Evaluation additionally accepts `constant0`/`constant1` and explicit
`--split train` calibration, which reports never label as held out.

## Contract V2 Review

The current client contract and checkpoint manifest are **version 2**, incompatible
with the earlier 47-input smoke checkpoint. Wire envelopes remain version 1, matching
the producer's documented Environment Spec V2. Earlier artifacts under
`artifacts/measured-20260909T103634Z/` are retained unchanged as historical evidence;
their reported rewards used target-rate normalization and must not be compared to
v2 rewards or loaded as v2 models. Historical commands/results below are labeled
by that campaign date, not proof of this revision's live validation.

The policy receives the last **three observed vectors**, oldest to newest. Each
49-value frame contains adjacency, eleven scaled metrics (including target and
actual foreground rates), availability masks and the observed previous action.
The resulting input is **147 values**. Reset starts a new history and repeats the
earliest observed frame for initial padding. No seed, scenario, phase index,
phase relationship or future workload is encoded. History can reduce ambiguity,
but the workload advances from phase k to k+1 before the next action is measured:
this remains a partially observed reactive problem, not a guaranteed MDP or a
proactive controller. GAE's bootstrap and reset-boundary math is unchanged.

Reward now divides goodput by **actual foreground sent rate**, derived from bytes
and sender duration, not the target. The target remains an absolute demand feature.
A verified zero-reply ping outage retains null observed RTT and its unavailable
RTT mask. Only after complete UDP/counter/queue/interval/readback validation does
it receive a separately labeled **1000ms censored-delay penalty reference**. That
reference is positive and bounded, not a fabricated RTT or a lower-bound claim
about all probes. Missing or inconsistent telemetry still cannot train.

Every reset/step checks the producer spec digest, source-map fingerprint,
measurement completion, phase relationship, exact horizon termination, concurrent
worker/counter intervals, ping counts, UDP counts and derived rates, raw leaf queue
readback and stable route readback. A lab spec change aborts the session. Spec
hashes are provenance identifiers, not remote attestation.

Checkpoints freeze the full lab spec/hash, image/source provenance and training
distribution (SDN mode, window, horizon, scenario-selection rule/families and seed
split), in addition to model/config/optimizer/RNG metadata. A compatibility hash
covers client contract, lab spec/hash and training distribution. Resume always
requires the identical lab spec, window and horizon. PPO evaluation also rejects
window/horizon changes **by default**; `--generalization` explicitly permits only
those evaluation differences and labels the result. It never permits spec drift,
old checkpoints, different feature contracts, or resume overrides. Lab image ID
is recorded separately from semantic/source compatibility, as in the producer.

Inference now requires `--history last-history.json`, containing version 2 plus
one to three consecutive measured request/response frames from one episode. It
validates evidence/spec/order/distribution before encoding only the observations.
Short histories are accepted only at episode start. A bare observation or padded
mid-episode single sample is rejected. Campaign inference uses the same artifact.

PPO logs post-update approximate KL, clipping fraction and explained variance
(null when return variance is zero). Training alone records actual route changes,
readback and before/after goodput/loss/RTT deltas. These deltas are confounded by
advancing workloads and are **not** a causal efficacy or superiority claim.
Reports reconstruct phases, measured rates and rewards from JSONL, cross-check
summary identities/counts, and mark differing SDN/FRR dataplane/background placement
as non-comparable even when offered schedules match.

The parent-authorized V2 campaign below subsequently ran after producer readiness.
Session budgets remain bounded to 30..600 seconds; the small campaign wrapper still
defaults to 24 transitions/300 seconds. No tuning on held-out results was performed.

## Measured V2 Outcome

Executed 2026-09-09 after explicit authorization. Source of truth:
`artifacts/measured-v2-20260909T110645Z/audit-v1/aggregate.json`. All earlier smoke
artifacts remain untouched. The frozen `plan.json` predates training.

Training ran from scratch with model seed 42, seeds **1100..1111**, 12 episodes
of four decisions, five-second targets and rollout 16: **48 actual transitions,
12 resets, three on-policy PPO updates**, in **430.782s** against a 600s budget.
All six scenario families appeared twice. Validation used exact requested seeds
2101/2102; test used 3101/3102. Under the frozen modulo-six mapping these pairs
are **overload/low**, not path0/path1. Seeds were not substituted to favor results.
Validation PPO and test PPO/heuristic/FRR each ran two four-decision episodes with
matching window/horizon, no generalization override and a fresh owner.

Every session completed without retry or invalid windows. Across all five sessions:
**80 valid decisions, 20 measured resets, zero observed service outages**, and
**705.496s summed session time**, excluding owner startup and offline audits.
All closes acknowledged cleanup; final inspection found no remaining experiment
container. The outage branch was not exercised live by this campaign.

Arithmetic means below cover decision windows only. Reward is per decision, not
the CLI mean episode total. RTT is observed, not a substituted timeout. Actions
are `[route0,route1]` counts; route changes are verified actual changes.

| Session | Decisions | Reward | Goodput Mbps | UDP Loss % | RTT ms | Changes | Actions | Seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Train PPO, sampled | 48 | 0.2874 | 8.770 | 18.426 | 45.421 | 26 | [20,28] | 430.782 |
| Validation PPO | 8 | 0.4662 | 11.354 | 11.782 | 45.149 | 2 | [0,8] | 71.261 |
| Test PPO | 8 | 0.4539 | 11.736 | 12.148 | 45.888 | 2 | [0,8] | 70.710 |
| Test heuristic | 8 | 0.4394 | 11.738 | 12.138 | 46.262 | 4 | [1,7] | 71.496 |
| Test FRR OSPF | 8 | 0.1376 | 7.503 | 28.763 | 43.863 | 0 | [8,0] | 61.248 |

**Pipeline passed; Step 8 model quality is not complete.** PPO's slight aggregate
reward advantage over the heuristic is not evidence of learned benefit: goodput
and loss were almost identical, PPO changed route twice versus four times, and
there were only eight decisions per test policy. On overload, PPO delivered
19.328 Mbps with 24.295% loss; heuristic delivered 19.333 Mbps with 24.276% loss.
No constant-policy live baseline was added. Initial and final deterministic PPO
decisions were identical on all **64 audited PPO histories** (48 training, eight
validation, eight test): always route 1. This remains a reactive partially observed
experiment, not demonstrated load-adaptive routing, convergence or superiority.

**FRR is not apples-to-apples.** It carried both flows on OSPF-selected route 0,
whereas SDN pinned competing traffic according to the workload fixture. Its L3
dataplane and placement mismatch remain explicit even though the report verified
identical offered phases. The mixed report correctly marks comparability false.

### V2 Update Audit

The retained audit reconstructs initialization and replays the existing measured
training trace only; it does not collect more traffic or deploy another policy.
All 48 logged sampled actions/value/probability vectors and all three logged
update metrics reproduced exactly. Replayed final weights are **bit-identical**
to the saved live-trained checkpoint. All eight parameter tensors changed from
initialization: L2 delta `0.3410813681`, maximum absolute delta `0.00368003547`.

| Update | Transitions | Rollout Mean Reward | Value Loss | Approx KL | Clip Fraction | Explained Variance | Mean P(route1) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 16 | 0.26104 | 1.42712 | 0.00048675 | 0 | -0.008873 | 0.56331 |
| 2 | 32 | 0.27014 | 1.48301 | 0.00118656 | 0 | -0.002691 | 0.58653 |
| 3 | 48 | 0.33106 | 1.67172 | 0.00028419 | 0 | 0.006997 | 0.59936 |

P(route1) is evaluated offline on the same 48 measured training inputs for each
snapshot. Rollouts contain different scenarios, so rising rollout reward is not
a controlled improvement curve. Every snapshot still chose route 1 by argmax on
all those inputs. Train-only route-efficacy records preserve actual readback and
confounded before/after metric deltas; none establishes causal improvement.

### V2 Artifacts

All paths below are relative to `artifacts/measured-v2-20260909T110645Z/`:

- `train/checkpoint.ptz`: restricted V2 model, optimizer, RNG, spec and distribution.
- `train/`, `validation-ppo/`, `test-ppo/`, `test-heuristic/`, `test-ospf/`:
  raw `evidence.jsonl`, durable `summary.json`, and validated `last-history.json`.
- `audit-v1/aggregate.json`: per-scenario metrics, learning diagnostics, parameter
  deltas, exact replay checks, frozen plan, hashes and cleanup outcome.
- `audit-v1/test-report.json`: phase/rate/reward reconstruction; mixed dataplane
  non-comparable. `test-sdn-report.json`: matched SDN schedule comparison.
- `audit-v1/infer-{train,test-ppo}-{0,1}.json`: two fresh-process CLI inferences
  per saved history, with **bit-identical JSON output** for each pair.
- `audit-v1/initial-reconstruction-not-trained.ptz`: explicitly untrained/offline
  post-hoc initial reference, never represented as a measured baseline policy.
- `audit.py`: retained procedure; exclusive audit directory prevents overwrite.

Checkpoint bundle SHA-256:
`742bf2498ee986c304848ed6617c5460be44ed36718554e48208139eed06004d`.
Weights payload SHA-256:
`b803808813fc615d7e64714d65709a60d9281c1bb406f227158d24e3a247e391`.
Producer spec hash:
`972ff6e8dc3a434db889f53a809ce0309e2d138bb4f16dd2d49dd2e50b7ad127`.
Lab image:
`sha256:a9721d734aac37319794ba4756302c5162c075887cfd297075bf2dd03f324c6f`.
Every measured frame matched the planned spec and image. All PPO evaluations
reloaded the same unchanged checkpoint in fresh processes. No tuning or further
measured training followed validation/test.

### V2 Commands Used

From the repository root, before each session, the operator ran
`python emulation/control.py experiment-start --mode sdn`, or `--mode ospf` for
FRR. The expired handoff container was absent; no competing owner was stopped.
From `ai-engine/`, the actual training command was:

```bash
uv run nanfo-routing train --operator-experiment --seed 1100 --episodes 12 \
  --steps 4 --rollout 16 --model-seed 42 --window 5 --budget-seconds 600 \
  --output artifacts/measured-v2-20260909T110645Z/train
```

Validation used `evaluate --policy ppo --split validation --seed 2101`; test used
`evaluate --split test --seed 3101` separately with `--policy ppo`,
`--policy heuristic`, and `--policy ospf --mode ospf`. Each included
`--operator-experiment --episodes 2 --steps 4 --window 5 --budget-seconds 180`,
its corresponding unique output directory above, and only PPO supplied
`--checkpoint artifacts/measured-v2-20260909T110645Z/train/checkpoint.ptz`.
Existing output directories must never be reused. Read-only inference:

```bash
uv run nanfo-routing infer \
  --checkpoint artifacts/measured-v2-20260909T110645Z/train/checkpoint.ptz \
  --history artifacts/measured-v2-20260909T110645Z/test-ppo/last-history.json
```

## Install And Verify

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first. From
`ai-engine/`:

```bash
uv sync --locked --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run nanfo-routing --help
uv run nanfo-routing train --help
uv run nanfo-routing evaluate --help
uv run nanfo-routing infer --help
uv run python scripts/campaign.py --help
```

`uv` uses the repository's Python 3.12 selection and locked CPU-only PyTorch
index. Do not install torch into the lab container. Tests use explicitly labeled
offline fixtures, including weight updates and fresh-process checkpoint inference;
they are not evidence of measured training or policy quality. Live CLI inference,
resume and PPO evaluation refuse fixture checkpoints.

## Operator Prerequisites

Read `../docs/adr/ADR-011-measured-routing-learning.md` and
`../emulation/EXPERIMENT.md`. Wait for the actual reset/step service to pass its
non-learning repeatability and FRR adjacency/routes/traffic checks before training.
Do not run these commands concurrently with the lab agent or another lab owner.
Never delete a manual journal to unlock the experiment.

The operator starts the disposable service from the repository root:

```bash
python emulation/control.py build
python emulation/control.py experiment-start --mode sdn
python -m emulation.experiment_smoke --mode sdn --episodes 2 --steps 2 --window 5
```

The smoke process closes its owner. Start a fresh owner for **each** subsequent
train/evaluate session. The AI client only invokes the fixed command
`docker exec -i nanfo-experiment python -m emulation.experiment_client`; it does
not build/start/stop Docker containers. It does send protocol `close` and requires
verified cleanup. An uncertain/lost response is never retried. If cleanup fails,
inspect the durable failure summary and use the operator command
`python emulation/control.py experiment-stop` from the repository root.

## Small Campaign

Only after measured baseline verification, start a fresh SDN owner from the root,
then run from `ai-engine/`:

```bash
uv run python scripts/campaign.py --operator-experiment --baseline-verified \
  --output artifacts/campaign-001
```

The default is **24 actual decision transitions**: six scenarios, four decisions
each, plus six measured resets. Each window is five seconds. The 300-second
session budget is checked between requests, not by interrupting a route change;
one in-flight request (client bound 90 seconds) and cleanup can extend it. The
wrapper has a further bounded process timeout. `--steps 3` or `--steps 5` requests
18 or 30 transitions; `--budget-seconds 60..600` changes the budget.

The script requires an already running operator-owned server, trains without a
synthetic fallback, and invokes inference in a separate process using the saved
last measured observation. It writes `campaign.json`, child stdout/stderr, and a
`train/` directory, including failures. Existing output directories are refused.
It does **not** start the lab or run held-out evaluations automatically. It has
not been executed against the live lab as part of package verification.

Equivalent standalone training, from `ai-engine/` with a fresh SDN owner:

```bash
uv run nanfo-routing train --operator-experiment --episodes 6 --steps 4 \
  --rollout 24 --window 5 --seed 1000 --budget-seconds 300 \
  --output artifacts/train-001
uv run nanfo-routing inspect --checkpoint artifacts/train-001/checkpoint.ptz
uv run nanfo-routing infer --checkpoint artifacts/train-001/checkpoint.ptz \
  --history artifacts/train-001/last-history.json
```

Inference is deterministic argmax by default; `--sample --seed 42` requests seeded
categorical sampling. It reports action probabilities, value, observation evidence,
contract and weight hashes, `execution:not_applied`, and `safety_confidence:null`.
Probabilities are **not** safety confidence. Input is validated measured history;
offline inference does not establish its wall-clock freshness.

Resume only between successfully completed sessions, with a fresh SDN owner:

```bash
uv run nanfo-routing train --operator-experiment \
  --resume artifacts/train-001/checkpoint.ptz --seed 1006 --episodes 6 --steps 4 \
  --window 5 --budget-seconds 300 --output artifacts/train-002
```

Resume restores checkpoint hyperparameters, optimizer, torch RNG and counters;
`--rollout`/`--model-seed` do not override checkpoint settings. It refuses reused
training seeds. There is no mid-episode resume or replay after an uncertain step.

## Held-Out Evaluation

Each command below needs its **own fresh SDN owner**, started from the root with
`python emulation/control.py experiment-start --mode sdn`. Run the AI commands
from `ai-engine/`. Each invocation reloads the checkpoint in a fresh process:

```bash
uv run nanfo-routing evaluate --operator-experiment --policy ppo \
  --checkpoint artifacts/train-001/checkpoint.ptz --split validation --seed 2000 \
  --episodes 6 --steps 2 --window 5 --generalization --output artifacts/validation-001
uv run nanfo-routing evaluate --operator-experiment --policy ppo \
  --checkpoint artifacts/train-001/checkpoint.ptz --split test --seed 3000 \
  --episodes 6 --steps 2 --window 5 --generalization --output artifacts/test-ppo-001
uv run nanfo-routing evaluate --operator-experiment --policy heuristic \
  --split test --seed 3000 --episodes 6 --steps 2 --window 5 \
  --output artifacts/test-heuristic-001
```

For real FRR comparison, start a fresh owner with
`python emulation/control.py experiment-start --mode ospf`, then:

```bash
uv run nanfo-routing evaluate --operator-experiment --policy ospf --mode ospf \
  --split test --seed 3000 --episodes 6 --steps 2 --window 5 \
  --output artifacts/test-ospf-001
uv run nanfo-routing report artifacts/test-ppo-001/summary.json \
  artifacts/test-heuristic-001/summary.json artifacts/test-ospf-001/summary.json
```

Validation is for selection, test for final held-out evaluation; do not tune on
test outcomes. Frozen ranges are train 1000..1999, validation 2000..2999, test
3000..3999. Scenario is selected by split-relative seed modulo six: `low`,
`path0`, `path1`, `alternating`, `burst`, `overload`. Splits share scenario families
but never workload seeds. This tests held-out workloads, not unseen topologies.
OSPF follows actual kernel/FRR routes for both flows and cannot pin background
traffic like SDN, so even matched schedules have stated baseline differences.

## State, Learning And Artifacts

- State has 147 dimensions: three 49-value frames, each with 25 fixed adjacency
  entries, eleven statically scaled metrics, eleven availability masks and two
  previous-action one-hot entries.
  Offered load remains absolute; there is no batch-dependent normalization.
- Routes are 0=`access1/dist1/access2`, 1=`access1/dist2/access2` for h1 to h3.
  The contract records graph/link order, capacities, delays, hosts and action map.
- Actor and value critic use a shared two-layer 64-unit tanh body. PPO has a clipped
  categorical objective, value loss, entropy regularization and gradient clipping.
  GAE bootstraps the final measured state at rollout/time limits but stops recursion
  across episode boundaries; true absorbing termination does not bootstrap.
- Reward records delivered/actual-sent ratio (capped at one), RTT/50ms, UDP loss,
  maximum utilization, queue/100 packets, and actual route changes. Weights are
  respectively 1, -0.2, -1, -0.1, -0.1, -0.05; scales/weights are hashed metadata.
- Missing/incomplete/failed windows abort the session, never yield a fabricated
  zero reward, and never enter PPO. Pending rollout rows are discarded on failure.
  One leftover valid row is reported but not used for an update.
- JSONL includes raw request/response measurements, action probabilities, values,
  reward components and PPO losses. Summaries include action counts, route changes,
  capacity exceedance diagnostics, elapsed time, invalid windows and cleanup errors.
  These counters are not a safety filter or a QoS guarantee.
- Checkpoints atomically bundle versioned JSON metadata and restricted tensor data:
  model, Adam state, torch RNG, initialization seed, training seeds/counters,
  feature/reward/topology contract and exact runtime versions. Loading checks
  archive bounds, SHA-256, contract equality, keys, shapes, dtypes and finite values;
  `weights_only=True` has no unrestricted pickle fallback. Identical snapshots
  produce byte-stable bundles. Runtime/contract mismatches require explicit retraining
  or a separately reviewed migration, not silent compatibility shims.
- Raw evidence is bounded, flushed and fsynced; summaries/checkpoints use atomic
  replace and directory fsync. Failures retain evidence and do not publish a new
  checkpoint. Hashes detect corruption, not authenticity: use only trusted operator
  artifacts; restricted torch loading is not a sandbox for hostile files.

A short run proves pipeline functionality only. No convergence, statistical
superiority, beneficial routing effect, unseen-topology generalization, final
trained model, or production safety is claimed. Measured training and held-out
comparisons remain pending the lab handoff and explicit measured campaign.

## Measured Results: 2026-09-09

This section supersedes the earlier pending-live statements. After the released
Step 7 SDN/FRR baseline handoff, the authorized campaign ran on the actual isolated
lab. No runtime changes, synthetic replacement measurements, test-driven tuning,
or backend/production changes were made during this campaign.

All evidence is under `artifacts/measured-20260909T103634Z/` (ignored runtime
artifacts, preserved locally). The pre-training `plan.json` froze training seeds
1000..1005 across all six scenarios, validation seeds 2001/2002, and test seeds
3001/3002. Both held-out pairs map to congested `path0`/`path1`; each policy used
two episodes of two decisions, five-second windows, and a fresh owner. The audit
verified identical offered phases across PPO, heuristic and FRR within each split.

Training collected **24 valid decisions plus six measured resets**, in 221.413s
against the requested 300s between-request budget. Its sole PPO update happened
after all 24 samples, using four optimizer steps. Thus the training rollout is
initial-policy exploration, not a learning curve. The six evaluation sessions
added 24 decisions plus 12 resets. Total: **48 valid decisions, 18 resets, zero
invalid windows**, and 475.542s summed session time, excluding owner startup and
offline audits. All seven sessions verified protocol cleanup; final Docker
inspection found no remaining `nanfo-experiment` container.

The table uses arithmetic means over decision windows, excluding reset windows.
Reward is **per decision**, not the CLI's mean episode reward. Actions are counts
`[route0,route1]`; route changes count actual read-back changes.

| Session | Decisions | Reward | Goodput Mbps | UDP Loss % | RTT ms | Changes | Actions | Seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Train PPO, sampled | 24 | 0.4193 | 9.490 | 13.692 | 40.063 | 13 | [13,11] | 221.413 |
| Validation PPO | 4 | 0.2910 | 8.965 | 17.784 | 46.221 | 2 | [0,4] | 45.491 |
| Validation heuristic | 4 | 0.7889 | 10.955 | 0.443 | 24.528 | 1 | [2,2] | 44.724 |
| Validation FRR OSPF | 4 | -0.1253 | 7.279 | 33.556 | 65.830 | 0 | [4,0] | 37.386 |
| Test PPO | 4 | 0.4278 | 8.888 | 11.564 | 44.496 | 2 | [0,4] | 45.028 |
| Test heuristic | 4 | 0.7984 | 10.031 | 0.333 | 24.877 | 1 | [2,2] | 44.284 |
| Test FRR OSPF | 4 | 0.0603 | 7.619 | 24.337 | 65.507 | 0 | [4,0] | 37.216 |

**Outcome: pipeline success, poor learned-policy behavior.** PPO always selected
route 1 in held-out evaluation, including when background traffic congested path1.
On test path1 it delivered 7.891 Mbps with 22.472% loss and 64.922ms RTT; the
heuristic delivered 10.177 Mbps with 0% measured loss and 24.060ms RTT. No policy
or hyperparameter was changed after observing these outcomes. Four decisions per
held-out policy are smoke-scale evidence, not statistical superiority or convergence.

**FRR is not apples-to-apples:** its real L3 kernel/OSPF routes placed both flows
on route 0 and ignored requested actions. SDN used OVS L2 forwarding with
scenario-selected competing-flow placement. The `path1` scenario name does not
mean FRR pinned its background flow onto path1. Matched offered phases do not
remove this placement/dataplane mismatch.

### Checkpoint And Reproducibility

- Checkpoint: `campaign/train/checkpoint.ptz` below the artifact root.
- Bundle SHA-256: `d1eeb8f870c582da71d4e39c847646135105bd406a6a453b2b35a482cbb55887`.
- Weight payload SHA-256: `aea6829ac67d80430dcb8dec975ffafa3a9c49cb205afe3e1c17735b1fdd460f`.
- All 8/8 tensors changed from seeded initialization: L2 delta `0.0966032141`,
  maximum absolute delta `0.00120351464`. The checkpoint records 24 transitions,
  one PPO update, six training seeds and the pinned runtime/contract.
- The audit reconstructed the initial seed-42 model after the campaign, explicitly
  labeled `offline-fixture-not-trained-model`, and verified exact equality with
  **all 24 logged pre-update action probability vectors** on their measured inputs.
  This establishes the initial-weight reference without claiming it was saved
  before training or measured as a separate baseline policy.
- Initial and trained argmax actions were identical on all 32 audited training,
  validation-PPO and test-PPO input states: route 1 in every case. Probability/value
  and weight changes therefore did not demonstrate useful decision adaptation.
  This is an offline same-state comparison, not counterfactual network rewards.
- The campaign loaded its saved checkpoint in a fresh inference process. The
  final audit repeated fresh-process CLI inference twice on both the last training
  and test observations, requiring exact output equality. Training inference also
  exactly matched the campaign's original output. Every PPO evaluation reloaded
  the same unchanged checkpoint in a separate process.

Authoritative aggregate: `audit-v2/aggregate.json`. It includes per-scenario raw
metric aggregates, timings, evidence hashes, frozen phases, weight deltas and
same-state policy comparisons. `audit-v2/validation-report.json` and
`audit-v2/test-report.json` verify matching held-out schedules and evidence hashes.
`audit-v1/` retains the first audit; v2 adds exact initial-model reconstruction
verification. Session directories `campaign/train`, `validation-{ppo,heuristic,ospf}`
and `test-{ppo,heuristic,ospf}` each retain raw `evidence.jsonl`, `summary.json`,
and the last measured observation. `audit.py` is the retained audit procedure;
its exclusive output directory intentionally prevents accidental rerun overwrite.

### Commands Used

From `ai-engine/`, against the fresh SDN owner released by the lab agent:

```bash
uv run python scripts/campaign.py --operator-experiment --baseline-verified \
  --steps 4 --budget-seconds 300 \
  --output artifacts/measured-20260909T103634Z/campaign
```

For each evaluation, the operator first ran
`python emulation/control.py experiment-start --mode sdn` (PPO/heuristic) or
`--mode ospf` (FRR) from the repository root. The command pattern from `ai-engine/`
was as follows; use a **new** output directory for any future run:

```bash
uv run nanfo-routing evaluate --operator-experiment --policy ppo \
  --checkpoint artifacts/measured-20260909T103634Z/campaign/train/checkpoint.ptz \
  --split validation --seed 2001 --episodes 2 --steps 2 --window 5 \
  --budget-seconds 120 --output artifacts/measured-20260909T103634Z/validation-ppo
```

Validation heuristic used `--policy heuristic` without `--checkpoint`; FRR used
`--policy ospf --mode ospf` without `--checkpoint`. Their output suffixes were
`validation-heuristic` and `validation-ospf`. Test repeated these three commands
with `--split test --seed 3001` and the corresponding `test-*` directories. No
training followed validation or test. Reproducible read-only inference remains:

```bash
uv run nanfo-routing infer \
  --checkpoint artifacts/measured-20260909T103634Z/campaign/train/checkpoint.ptz \
  --observation artifacts/measured-20260909T103634Z/test-ppo/last-observation.json
```
