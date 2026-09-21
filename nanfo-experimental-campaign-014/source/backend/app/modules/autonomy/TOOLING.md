# ADR-013 Operator Assessment

## Completed Campaign 001

The completed `adr013-001` producer still reports `version:3`, but its final shape
added required `train_only_action_effects`, `calibration_evidence_sha256` and
`evidence_paths`; checkpoint manifests added required `client_source_files`.
The backend now consumes that exact shape with `extra=forbid`, rather than
stripping fields or accepting arbitrary extensions. Output identifies this revision
as `adr013-001-evidence-paths-client-sources`. The earlier V3 parser below was a
pre-campaign snapshot and is superseded by this section for actual producer files.

`campaign_evidence.py` independently reconstructs UDP byte/packet goodput/loss,
measured RTT, per-interface utilization and netem backlog bytes, reward components,
input hashes, action continuity, heuristic actions, matched scenarios/background,
paired seed metrics and the frozen four-seed Student-t intervals. It verifies
checkpoint bytes/metadata, training/validation/action-effect raw JSONL hashes,
predeclared plan bindings and frozen client-source hashes without importing AI code.
The entire operator-pinned campaign inventory (122 files, 8,269,065 bytes) is checked,
including empty stderr logs; empty qualification/JSON/checkpoint files still refuse.
Absolute producer paths are constrained under the environment-owned artifact root,
then traversed with the existing no-symlink descriptor reader.

Measured assessment results:

| Pilot | Validation Actions [0,1] | Mean Reward | PPO Minus Heuristic | Result |
| --- | --- | --- | --- | --- |
| 41 | [16,0] | -0.2921034355 | -0.5415134124 | useful_model_unqualified |
| 42 | [16,0] | -0.3519930303 | -0.6014030071 | useful_model_unqualified |

Both have measured `path0` desired-route fraction 0 and `path1` fraction 1.
The producer's pressure-swap diagnostic fails on path1. The backend independently
reconstructs measured actions, but does NOT rerun tensor pressure-swap inference;
`frozen_policy_replay_not_independently_validated` remains explicit. Mean margins
over constants are positive, but paired uncertainty crosses zero, and directionality
fails regardless of those means or the producer's `qualified` flag. No selected model
exists; the hash-verified collection ledger contains zero test attempts. Each pilot
has 32 transitions/2 updates, not the separate ADR012 144-transition minimum.

For actual dossiers, `--calibration qualification-41.json` reads only the training
and train-only action-effect measurements for queue/counter diagnostics. These are
sampled queue peaks (up to 124,200 bytes), not synchronized q-before/q-after endpoints.
Interface RX is not attributed egress arrivals; TX averages are not guaranteed
available service. No fit/holdout was predeclared for endpoint safety calibration.
The honest output is `fit_performed:false`, `holdout_coverage:null`,
`trusted_calibration:null`, with explicit missing-endpoint/attribution/holdout reasons.
No arbitrary normalized q values are substituted and no positive certificate is inferred.

Executed read-only command from `backend` (use a NEW output name when rerunning):

```bash
export NANFO_AUTONOMY_ARTIFACT_ROOT=/home/DHB/Documents/NANFO/ai-engine/artifacts/adr013-001
export NANFO_AUTONOMY_CAMPAIGN_INDEX_SHA256=1703525bafd956fbfc81e60e15d872769135f9d4da1d2b23ea22ad3d20ea2213
export NANFO_AUTONOMY_QUALIFICATION_SHA256=b9672394a64e2a0a43a59d521abda3510da50ef41d3c8ffcef29b9f647b469af
PYTHONPATH=. poetry run python scripts/assess_autonomy_readiness.py \
  --qualification qualification-41.json --calibration qualification-41.json \
  --output /tmp/opencode/adr013-backend-assessment-41.json
```

Pilot42 uses qualification hash
`486f12598a51550e07e17bc1e177170763f3936108a8862b6d91d11195438fea`,
`qualification-42.json` for both inputs, and output
`/tmp/opencode/adr013-backend-assessment-42.json`. Both commands exited 2 as expected.
Output creation is exclusive, cannot overwrite an existing file, and must be outside
the input root. Assessment otherwise remains read-only. Existing providers unchanged.

Verification: 21 new campaign regressions including sanitized actual-shaped fixtures,
modified raw queue/counter/metric/ownership refusals and both real dossier tests.
Full backend with `NANFO_TEST_ADR013_CAMPAIGN_ROOT` set: 1,706 passed, 14 infrastructure
skips. No AI/emulation modifications, lab start, deployment, selection or test collection.

These backend-owned, read-only commands implement the user-requested ADR-013
qualification/calibration inspection boundary. No API, event, database migration,
runtime provider installation, model training, experiment step, or lab lifecycle
operation is added. Existing `installed_providers()` is unchanged and fail-closed.

## Commands

Run from `backend`. Paths passed to the CLI are relative to the environment-owned
allowlist root, never arbitrary caller-controlled absolute paths:

```bash
export NANFO_AUTONOMY_ARTIFACT_ROOT=/absolute/operator/reviewed/evidence
export NANFO_AUTONOMY_QUALIFICATION_SHA256=EXACT_DOSSIER_SHA256
PYTHONPATH=. poetry run python scripts/assess_autonomy_readiness.py \
  --qualification qualification.json --calibration calibration-input.json
PYTHONPATH=. poetry run python scripts/calibrate_autonomy.py \
  --calibration calibration-input.json
PYTHONPATH=. poetry run python scripts/calibrate_autonomy.py \
  --universal-arrival-mbps 20 --queue-bytes 0 --dt-seconds 2 --error-bytes 0
```

Assessment/diagnostics return JSON on stdout and exit **2** for blocked/unqualified.
They never overwrite input artifacts. An explicit `--output` creates a new assessment
outside the artifact root without overwriting existing files. Schema inspection
returns **0** and prints the exact Pydantic schema, including required fields:

```bash
PYTHONPATH=. poetry run python scripts/assess_autonomy_readiness.py --schema producer
PYTHONPATH=. poetry run python scripts/assess_autonomy_readiness.py --schema qualification
PYTHONPATH=. poetry run python scripts/assess_autonomy_readiness.py --schema evaluation-plan
PYTHONPATH=. poetry run python scripts/assess_autonomy_readiness.py --schema episode
PYTHONPATH=. poetry run python scripts/calibrate_autonomy.py --schema input
PYTHONPATH=. poetry run python scripts/calibrate_autonomy.py --schema plan
PYTHONPATH=. poetry run python scripts/calibrate_autonomy.py --schema traces
```

The root and dossier pin must be protected operator configuration. This is local
operator-selected evidence, **not cryptographic signing or remote attestation**.
No signing key is accepted from an artifact, and no signature support is claimed.
Deploy on a read-only mount with appropriate ownership; the tool itself only opens
read descriptors. Child symlinks, traversal, FIFO/device files, oversize artifacts,
duplicate JSON keys, nonfinite numbers, unknown schema fields, and hash/size changes
are refused. Component-wise `openat`/`O_NOFOLLOW` and same-descriptor hashing avoid
path-swap attacks. JSON documents are bounded to 4 MiB, checkpoint bundles to
16 MiB, and aggregate evaluation/source evidence to 64 MiB.

## Qualification

Direct input supports the actual AI `nanfo_routing.qualification.qualify()`
version-3 result inspected on 2026-09-09. This independent parser checks exact
outer schema, strict booleans/counts, both constant margins, paired seed counts,
recomputed mean differences, complete baseline/metric maps, directional-dependence
fractions, validation-only scope, blocked dispatch, and false safety guarantee.
The producer's `qualified` flag is reported separately and never auto-promoted.
Its interval is checked for ordering but is not independently statistically
certified; raw measured derivation and checkpoint tensor inference remain gates.

Direct producer output is not a deployment dossier: it contains hashes but no
operator-bounded references to all necessary evidence and explicitly has no test
assessment. Reasons include `operator_dossier_missing`,
`producer_raw_evidence_binding_unverified`, and `heldout_test_not_assessed`.
A `best.json` or historical supervisor status is rejected as
`qualification_schema_missing_not_best_pointer`, not treated as a manifest.

`nanfo.operator-qualification.v1` is the **backend operator inspection dossier**,
not a claim that the AI exporter already emits it. It binds checkpoint, producer
output, training evidence, predeclared evaluation plan, and normalized measured
episodes by exact byte SHA-256 and size. Checkpoint ZIP metadata and weights bytes
are hash-validated without unpickling/loading tensors. The input has a separate
operator pin, not a pin supplied inside the dossier being authenticated.

The independent comparison checks reserved disjoint seed ranges, completed
validation before selection, test after selection, balanced stationary path-pressure
scenarios, identical per-seed schedules/spec/contracts, all five methods, complete
decision windows, action continuity, model hashes, measured inference timing and
both constant advantages. Reward is recomputed from byte/packet/RTT/queue metrics
using the current V3 reward formula. Heuristic and OSPF remain visible comparisons,
not quietly omitted if better. Reported normal-approximation paired intervals are
exploratory diagnostics, not small-sample safety confidence or proof of superiority.

**Normalized metric derivation is not yet independently reconstructed from the
producer's raw namespace evidence.** Every source must exist and hash-match, but
that is not physical measurement validation. Even a complete dossier therefore
retains `normalized_measurement_derivation_unverified` and stays unqualified. Do
not hand-author normalized rows to manufacture qualification. This importer is
useful for finding bad/missing artifacts and comparison failures; it is not an
activation workaround. No qualified inference runtime or tensor loader is installed.

## Calibration

`nanfo.calibration-input.v1` contains `{schema_version, plan, traces}`. Each reference
contains `{path, sha256, size_bytes}`. The traces bind the exact plan bytes too.
The plan declares fit and holdout seeds within the training range **1000..1999**,
before measurement, with disjoint complete scope, positive common horizon, queue
threshold, actions, egresses and minimum samples per group. Validation/test seeds
are rejected, not used to fit safety bounds.

`nanfo.matched-queue-traces.v1` requires actual before/after queue **bytes** and
monotonic arrival/service counters over identical intervals, complete attribution,
stationarity, no reset, and source references. Episode/seed mixing, duplicate or
overlapping windows, missing action/egress groups and horizon differences refuse.
The tool will not convert sampled path queue peaks or port utilization into queue
endpoints or counterfactual service. The current AI/lab artifact format does not
automatically supply this calibration export. A collector-reviewed export and
independent raw derivation checks remain necessary; no such data was fabricated.

For each action/egress group the tool fits maximum interval arrival, minimum
interval delivered service, and maximum nonnegative endpoint residual on the fit
subset only. The frozen values are evaluated against the untouched holdout subset:
arrival/service/queue coverage, violating sample IDs, endpoint envelope, and zero
drift budget. Holdout failures never widen fitted bounds. Positive drift, envelope
failure and coverage failure have distinct reasons. Coverage is descriptive, not
a statistical or physical guarantee. Every result remains `qualified:false` and
`trusted_calibration:null`, even with 100% coverage and negative empirical drift.

This implementation never constructs `TrustedCalibration`. Fitted maxima/minima
do not establish causal burst/service/transition guarantees, unobserved cross-traffic,
arbitrary outages, or observation-to-actuation latency. Average transmitted service
may have been unused before late arrivals; subtracting it is not a universal fluid
bound. Per-egress diagnostics do not claim synchronized whole-network Lyapunov proof.

## Universal Bound

Conditional on a justified arrival cap A and additive error E, without any
positive service guarantee:

```text
g = A * dt + E
U = q + g
D_upper = q*g + g*g/2
```

For q>=0, dt>0, A>=0, E>=0, any positive g yields positive drift. An assumed 20 Mbps
cap is 2,500,000 bytes/s. At q=0, dt=2, E=0, U=5,000,000 bytes and
D_upper=12,500,000,000,000 bytes squared. A zero-budget certificate cannot pass.
For multiple egresses the nonnegative terms sum; adding queues does not solve this.
The configured link line rate does not by itself justify an aggregate arrival cap
covering bursts, headers and all incoming traffic.

Known stationary flows may support a tighter conditional service analysis, but
only if continuous service availability and within-interval dynamics are guaranteed.
If service may become unavailable, a positive fitted minimum is not a lower bound.
Do not raise the drift budget or substitute fitted service just to obtain acceptance.

## Runtime Blockers

The CLI records `runtime_control_incompatible`: matched Linux/FRR source-specific
host routing is not the existing ADR-010 manual OVS/OpenFlow runtime action.
No executor/recovery adapter is installed, no manual approval is synthesized, and
no ownership token is borrowed from an experiment. Existing worker recovery and
authorization semantics are untouched.

Version-3 inference history is an experiment `reset`/`step` history, not a fresh
passive network observer. Producer monotonic timing/episode identity is not a
trusted backend wall-clock freshness or workspace/network ownership binding.
No passive observer is installed or a generic telemetry vector substituted.
The assessment flags `experiment_ownership_not_runtime_authority` and
`passive_observation_provider_unavailable`; it cannot automatically step the lab.

Steps 9/10 remain open pending raw measured qualification, physically justified
bounds, exact fresh passive runtime evidence, a distinct receiver-fenced durable
action/recovery implementation, and a live verified intervention. This work starts
no live lab and does not compete with other agents' measurement campaigns.
