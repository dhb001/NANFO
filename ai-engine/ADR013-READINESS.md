# ADR013 Offline Readiness

Implementation only. No live collection or model qualification has been performed
by this change. Parent approval and lab release are prerequisites, not implied by
the presence of commands below. All historical artifacts are preserved. Do not
use the old two-hour supervisor or historical campaign script with v3.

## Frozen Design

- Observation/checkpoint/client contract v3 rejects v2. One 16-value frame: 13
  log1p-scaled measured metrics (including verified path capacities), RTT availability,
  previous-route one-hot. No adjacency, seed, scenario, future phase or hidden schedule
  enters the actor. Monotone scaling preserves pressure order and does not clip overload.
- Separate actor and critic: one 32-unit tanh body each. Orthogonal body initialization,
  actor head gain .01, critic gain 1, zero biases. Balanced initial categorical logits.
  Existing clipped PPO/GAE math retained, including time-limit bootstrapping and
  stopping recursion at episode boundaries. No imitation labels or fabricated rewards.
- Explicit balanced `--scenarios path0,path1`, 4 steps, 2-second measurement windows,
  rollout16. Generic stationary experiments allow 4..8 steps and rollout16/32, but
  qualification uses the frozen plan, not post-hoc hyperparameter changes.
- Exact full producer spec and source map/hash are stored in checkpoint/evidence;
  readback validates actual HTB capacity and source-specific foreground policy routes.
  Actual FRR background forwarding must match OSPF. This is nominal-cost OSPF under
  identical exogenous capacity impairment, not adaptive-capacity-aware OSPF.
- First train-only calibration must show preferred-route effect greater than .02
  in each pressure direction. Qualification requires parsed/recomputed measured rewards,
  exact checkpoint replay, balanced validation, greater than .02 over BOTH constants,
  majority directional choices in both scenarios and opposite choices when only paired
  pressure/capacity inputs are swapped. The swap is a diagnostic, not a measured reward.
- Serious heuristic and OSPF baselines remain in reports even when they win. Paired
  seed-mean Student-t 95% intervals report raw seed means and effect; windows are not
  counted as independent seeds. Four validation seeds are weak statistical evidence.
- No safety confidence output, production authorization, bounds guarantee or automatic
  deployment. A qualification is local evidence consistency, not remote attestation.

## Budget and Seeds

`plan` exclusively creates the exact predeclared plan. Collection with `--plan`
requires `--parent-approved --lab-released`. A locked ledger beside the plan records
every attempted session before contact, refuses duplicate attempts and has a fixed
1200-second wall deadline beginning with first collection. Startup/gaps consume that
deadline; 180 seconds are reserved for an in-flight request and cleanup. Do not create
a second plan to extend the budget. Keep the plan directory operator-owned/private.

Calibration: train1480..1481, constants0/1. Pilots: model41/train1500..1507 first;
model42/train1520..1527 then model43/train1540..1547 only if parent admits them within
the same deadline. Each pilot is fresh (32 transitions), not resumed. Validation:
2600..2603. Reserved fresh test:3800..3803. No old test results enter selection.
Insufficient time/quality means **unqualified**, not an extended campaign or relaxed gate.

## Pending Commands

All commands below run from repository root. First run offline tests:

```bash
uv run --project ai-engine --no-sync pytest ai-engine/tests -q
uv run --project ai-engine --no-sync ruff check ai-engine/src ai-engine/tests
uv run --project ai-engine --no-sync ruff format --check ai-engine/src ai-engine/tests
```

Prepare a new private directory and freeze the plan BEFORE collection:

```bash
mkdir -m 700 ai-engine/artifacts/adr013-001
uv run --project ai-engine --no-sync nanfo-routing plan --output ai-engine/artifacts/adr013-001/plan.json
```

After parent approval AND lab release only, use this shell helper. It starts a fresh
lab owner for each session; successful session close ends that owner. Stop on any
failure; never replay an ambiguous request or erase the ledger. Build/release the
lab image through the lab owner first, outside these commands.

```bash
R=ai-engine/artifacts/adr013-001
session() {
  mode="$1"; name="$2"; shift 2
  python emulation/control.py experiment-start --mode "$mode" || return
  uv run --project ai-engine --no-sync nanfo-routing "$@" --operator-experiment --parent-approved --lab-released --plan "$R/plan.json" --mode "$mode" --scenarios path0,path1 --steps 4 --window 2 --rollout 16 --budget-seconds 300 --output "$R/$name"
}
session matched calibration-constant0 evaluate --policy constant0 --split train --seed 1480 --episodes 2
session matched calibration-constant1 evaluate --policy constant1 --split train --seed 1480 --episodes 2
session matched train-41 train --model-seed 41 --seed 1500 --episodes 8 --calibration "$R/calibration-constant0/summary.json" "$R/calibration-constant1/summary.json"
session matched validation-constant0 evaluate --policy constant0 --split validation --seed 2600 --episodes 4
session matched validation-constant1 evaluate --policy constant1 --split validation --seed 2600 --episodes 4
session matched validation-heuristic evaluate --policy heuristic --split validation --seed 2600 --episodes 4
session ospf validation-ospf evaluate --policy ospf --split validation --seed 2600 --episodes 4
session matched validation-41 evaluate --policy ppo --checkpoint "$R/train-41/checkpoint.ptz" --model-seed 41 --split validation --seed 2600 --episodes 4
```

Each line is a separate operator step; inspect its exit status before continuing.
Optional pilots42/43 repeat only train and PPO validation with their declared model
seed/train start and new output names. Reuse the fixed validation baselines. No
hyperparameter changes, no training on calibration or validation, no tuning on test.

```bash
session matched train-42 train --model-seed 42 --seed 1520 --episodes 8 --calibration "$R/calibration-constant0/summary.json" "$R/calibration-constant1/summary.json"
session matched validation-42 evaluate --policy ppo --checkpoint "$R/train-42/checkpoint.ptz" --model-seed 42 --split validation --seed 2600 --episodes 4
session matched train-43 train --model-seed 43 --seed 1540 --episodes 8 --calibration "$R/calibration-constant0/summary.json" "$R/calibration-constant1/summary.json"
session matched validation-43 evaluate --policy ppo --checkpoint "$R/train-43/checkpoint.ptz" --model-seed 43 --split validation --seed 2600 --episodes 4
```

Offline qualification and selection (exit2 means a measured quality rejection):

```bash
uv run --project ai-engine --no-sync nanfo-routing qualify --plan "$R/plan.json" --checkpoint "$R/train-41/checkpoint.ptz" --training "$R/train-41/summary.json" --calibration "$R/calibration-constant0/summary.json" "$R/calibration-constant1/summary.json" --validation "$R/validation-41/summary.json" "$R/validation-constant0/summary.json" "$R/validation-constant1/summary.json" "$R/validation-heuristic/summary.json" "$R/validation-ospf/summary.json" --output "$R/qualification-41.json"
uv run --project ai-engine --no-sync nanfo-routing select --candidates "$R/qualification-41.json" --output "$R/selection.json"
```

Include every admitted pilot's qualification in `--candidates`; select uses the
highest eligible validation mean, then lower model seed. Both `select` and qualified
inference reparse/recompute the referenced evidence, never trust `qualified:true` or
an old `best.json`. Selection files are exclusive-create and bind checkpoint hashes.

Only after selection, and only if the original deadline has time remaining, test
all five methods with `--split test --seed 3800 --episodes 4 --selection "$R/selection.json"`.
Use `test-constant0`, `test-constant1`, `test-heuristic`, `test-ospf`, `test-ppo` outputs;
the PPO checkpoint MUST be the selected checkpoint. First test admission permanently
blocks further training/validation in that plan. If no time remains, report test
not run and request a separately predeclared follow-up, never extend this campaign.

Exact test commands if pilot41 is selected (otherwise replace only the selected
checkpoint path and its model seed with the selection's values):

```bash
session matched test-constant0 evaluate --policy constant0 --split test --seed 3800 --episodes 4 --selection "$R/selection.json"
session matched test-constant1 evaluate --policy constant1 --split test --seed 3800 --episodes 4 --selection "$R/selection.json"
session matched test-heuristic evaluate --policy heuristic --split test --seed 3800 --episodes 4 --selection "$R/selection.json"
session ospf test-ospf evaluate --policy ospf --split test --seed 3800 --episodes 4 --selection "$R/selection.json"
session matched test-ppo evaluate --policy ppo --checkpoint "$R/train-41/checkpoint.ptz" --model-seed 41 --split test --seed 3800 --episodes 4 --selection "$R/selection.json"
```

Report example:

```bash
uv run --project ai-engine --no-sync nanfo-routing report "$R/validation-41/summary.json" "$R/validation-constant0/summary.json" "$R/validation-constant1/summary.json" "$R/validation-heuristic/summary.json" "$R/validation-ospf/summary.json"
```

## Subprocess Inference

No Docker dependency or lab contact for inference. Use the pinned Python runtime,
send one bounded JSON object to stdin, close stdin, read one JSON result, check exit
status. `--history -` accepts `{version:3,frames:[{request:...,response:...}]}` with
exactly one measured v3 frame. Paths can instead be supplied directly:

```bash
uv run --project ai-engine --no-sync nanfo-routing infer --checkpoint "$R/train-41/checkpoint.ptz" --selection "$R/selection.json" --history "$R/validation-41/last-history.json"
```

Outputs include action, probabilities (NOT confidence), value, canonical observation
`input_sha256`, full artifact `policy_sha256`, weights/spec/client hashes, measured
input evidence, model inference seconds and artifact-validation-plus-inference
seconds. No execution occurs. Without `--selection`, inference is explicitly only a
measured-checkpoint diagnostic, not qualification. The backend must independently
enforce observation freshness, authorization, approved safety bounds and dispatch.

Reports separate model p50/p95/p99, control/readback p50/p95/p99, total observation+
control+IPC duration and ICMP RTT. Actual application UDP RTT is separate and must
come from the lab's real echo evidence; absence is null, never an ICMP substitution.
At initial implementation the lab had not yet published UDP RTT evidence. Completion
of that metric and all live evidence remain lab-release gates, not assumed results.

## Verification Handoff

Final offline verification: **214 tests passed**, Ruff lint/format passed, and
`git diff --check -- ai-engine` passed. Gym's checker emits one existing-style
warning for the deliberately unbounded nonnegative observation-space maximum.
Tests include PPO math, compact-policy learnability (synthetic unit data only),
v2/source/checkpoint rejection, matched evidence tampering, checkpoint decision
replay, strict both-constant/directional qualification gates, budget/approval
admission and fresh-process CLI/inference checks. No test fixture is admissible
as real model qualification.

Lab subsequently published `emulation/MATCHED-VALIDATION.md`, reporting owner
release and its own live action-effect checks. The AI client read-only audit
validated all **18 stored matrix windows** against v3, with no Docker contact,
training, validation/test collection or policy qualification:

```bash
uv run --project ai-engine --no-sync python ai-engine/scripts/audit_v3_lab.py emulation/output/experiment-matched-matrix.json
```

Observed shared spec hash:
`5ece436bfa8b41fd868dfc87dc5152848d038e25511c6dadee1e64a420b1cbe9`.
This compatibility check does not consume the reserved calibration/validation/test
seeds or replace frozen calibration. Parent measurement approval is still pending.
The released lab contract still contains only ICMP RTT and UDP delivery/rate, not
UDP echo RTT; actual UDP RTT reporting remains explicitly incomplete. Do not claim
that metric, faster service recovery, or full ADR013 campaign completion.
