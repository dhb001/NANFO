# AI P2/P3 Shadow Decision Foundation — ADR021

## Delivery and ownership

Implemented an **offline, operator-only, non-actuating review foundation**. P2
provides frozen diagnostic identity checks and matched baseline comparisons; P3
provides typed decision records and three deterministic domain evidence analyzers.
This is not calibrated safety, new model qualification, deployed autonomy, an LLM
agent service, or completion of ADR012 live closed-loop acceptance.

Owned files:

- `ai-engine/scripts/shadow/__init__.py`
- `ai-engine/scripts/shadow/schemas.py`: strict Pydantic operator-file/decision types.
- `ai-engine/scripts/shadow/agents.py`: `DomainAgent` protocol and capacity, failure,
  policy analyzers with evidence references and explicit assumptions.
- `ai-engine/scripts/shadow/evaluate.py`: export adapter, identity/comparability
  checks, seed-paired descriptive comparisons, abstention and decision construction.
- `ai-engine/scripts/shadow/io.py`: bounded, byte-pinned, read-only file imports.
- `ai-engine/scripts/shadow_evaluate.py`: operator entrypoint, JSON on stdout.
- `ai-engine/tests/test_shadow.py`: offline synthetic contract/regression coverage.
- `ai-engine/tests/test_holdout.py`: controlled-clock deadline regression.
- This handoff document.

### Fingerprint and integration design

`nanfo_routing.artifacts.clientSources()` hashes every direct `*.py` under
`src/nanfo_routing`. Adding even a new file there changes the frozen source map.
The shadow implementation therefore lives under `scripts/shadow`, imports neither
`nanfo_routing` nor Torch/Gym/backend modules, and requires only the already-present
Pydantic installation. Existing source, PPO/environment/contracts, checkpoints,
training/holdout scripts, dependency definitions/locks and historical artifacts are
unchanged. There is no model loading, training, transport, subprocess, network,
provider installation, backend composition, migration, endpoint or event addition.

Design authority: ADR021 section 6, ADR018 diagnostic contracts, ADR013/014 matched
and held-out evidence rules, ADR012 qualification/calibration separation, AIOS
rules/skill. ADR021's explicit non-actuation and calibration limits govern this
slice; the generic AIOS confidence bands cannot authorize it.

## Operator usage

From repository root, use the existing AI interpreter without installing packages:

```bash
ai-engine/.venv/bin/python -B ai-engine/scripts/shadow_evaluate.py \
  --plan /operator/shadow/review-plan.json \
  --plan-sha256 "$TRUSTED_REVIEW_PLAN_SHA256" \
  --diagnostic /operator/shadow/diagnostic-export.json \
  --outcomes /operator/shadow/matched-outcomes.json \
  --benchmark /operator/shadow/original-benchmark.json
```

The command writes only stdout/stderr. Save output outside historical campaign
directories if needed. CLI time is actual UTC; there is no caller-controlled
`--now` freshness override. The pure evaluation API takes an explicit aware time
for deterministic tests. Exit codes:

| Code | Meaning |
|---|---|
| 0 | Valid evidence, `status=review`; **no execution or safety authorization** |
| 2 | Valid evidence, `status=abstain`, with explicit reasons |
| 1 | Malformed, tampered, mismatched or incomparable evidence; sanitized rejection on stderr |

Module invocation is also supported **from `ai-engine/`** with the same arguments:

```bash
.venv/bin/python -B -m scripts.shadow_evaluate \
  --plan /operator/shadow/review-plan.json \
  --plan-sha256 "$TRUSTED_REVIEW_PLAN_SHA256" \
  --diagnostic /operator/shadow/diagnostic-export.json \
  --outcomes /operator/shadow/matched-outcomes.json \
  --benchmark /operator/shadow/original-benchmark.json
```

This is a source-checkout namespace-module entrypoint, not an installed wheel
entrypoint: the existing frozen package build configuration is unchanged. Neither
entrypoint requires `PYTHONPATH`, a backend installation, a model registry,
checkpoint files or campaign artifacts. Supplied evidence and Pydantic are required.

Supply a separately trusted review-manifest SHA256; hashing an untrusted manifest
and immediately accepting that hash is not authentication. File reads reject
final-component symlinks/nonregular files, empty/oversize content, digest mismatch,
duplicate JSON keys, nonfinite numbers, excessive nesting and unknown typed fields.
Limits are 1 MiB for the manifest, 8 MiB for each other input, 100 GET diagnostics,
1,000 cases and 5,000 outcome rows. Files are opened/read once and the consumed
bytes are hashed. Operator paths are explicit CLI inputs; JSON never selects a
filesystem path, Python module, checkpoint loader or executable.

### Exact local schemas

The source of truth is `scripts/shadow/schemas.py`. Machine-readable JSON Schema
can be printed without invoking inference:

```bash
PYTHONPATH=ai-engine/scripts ai-engine/.venv/bin/python -B -c \
  'import json; from shadow.schemas import Plan, Outcomes, Decision; print(json.dumps({c.__name__: c.model_json_schema() for c in (Plan, Outcomes, Decision)}, indent=2))'
```

All datetimes must carry a timezone. IDs/hashes, finite numeric bounds, action
integers and booleans are validated without string/boolean numeric coercion.

#### Review manifest (`Plan`, version 1)

| Fields | Binding/meaning |
|---|---|
| `network_id`, `workspace_id` | Exact diagnostic and every-outcome UUID scope |
| `purpose` | Exactly `historical_shadow_review` |
| `frozen_at`, `selected_at`, `selection_split` | Attested original plan/selection times; freeze precedes selection; selection is `validation` |
| `train_seeds`, `validation_seeds`, `cases` | Unique train 1000–1999, validation 2000–2999, test 3000–3999; minimum two test seeds |
| Each case | `seed`, `scenario`, `workload_sha256`, `schedule_sha256` |
| `methods` | Exactly one each of `ppo`, `ospf`, `constant0`, `constant1`, `heuristic`, each with a frozen `policy_sha256` |
| `comparison` | Exact common experiment/measurement contract described below |
| `model` | All twelve existing diagnostic identity fields: model/checkpoint/history IDs and registry/policy/weights/source/history/input/contract/spec/benchmark hashes |
| `diagnostic_id`, `diagnostic_sha256` | One exact recorded diagnostic and SHA256 of the complete supplied export bytes |
| `outcomes_sha256` | SHA256 of the complete normalized outcome file |
| `observation_at` | Actual historical input acquisition time, **not** diagnostic replay/record creation time |
| `action_paths`, `allowed_actions` | Two distinct loop-free action paths and permitted review action IDs; exact selected diagnostic path check |
| `max_age_seconds` | Explicit review age limit, >0 and <= one year; exclusive expiry |
| `utilization_review_threshold`, `loss_review_threshold` | Explicit review thresholds, never safety bounds or learned/calibrated thresholds |

The comparison object contains `spec_hash`, `contract_hash`,
`lab_provenance_sha256`, `topology_sha256`, `addressing_sha256`, `queues_sha256`,
`ospf_costs_sha256`, `measurement_sha256`, `mode="matched"`,
`provenance="historical_measured_v4"`, `latency_metric="icmp_rtt_ms"`,
`window_seconds`, `episode_steps`. Baseline policy hashes bind each baseline's
specific frozen implementation/configuration; common hashes bind shared semantics.

This manifest is a **post-collection review binding** that copies original frozen
criteria and timestamps and adds export hashes. Its own hash does not prove the
original plan existed before collection. Audit original plan, selection and
collection records independently; do not backdate a new experiment or use this
tool to tune after seeing held-out outcomes.

#### Matched outcomes (`Outcomes`, version 1)

The file contains `benchmark_evidence_sha256` and `rows`. The original benchmark
file is separately read and byte-hash checked. Each row contains:

- Exact network/workspace scope, `case`, `method`, `policy_sha256`, `comparison`.
- `split="test"`, `status="completed"`, `measured_start`, `measured_end` and
  `raw_evidence_sha256` identifying the independently auditable seed/method episode.
- Seed-episode `reward`, `goodput_mbps`, `loss_fraction`, `icmp_rtt_ms` (nullable for
  censoring/unavailable latency), and integer `route_changes`.

All five methods must cover exactly the manifest's cases. Duplicates, missing or
extra cases, reused episode evidence identities, mismatched workload/schedule,
queue/cost/topology/provenance/dataplane/window/metric contracts and policy drift
are rejected. Every measured episode starts strictly after model selection and
lasts at least `window_seconds * episode_steps`.

Normalization is an operator integration boundary, not an invented upstream API.
There is no automatic parser for every historical report revision in this slice.
Export one auditable episode aggregate per seed/method from the original validated
report/raw evidence, preserving its metric aggregation definitions and censored
RTT. Pin that normalization and its measurement semantics. A shared session file
hash alone cannot stand in for distinct per-episode evidence identities; use the
audited per-episode representation's digest. Raw episode hashes are retained as
references, **not dereferenced or replayed here**. Original artifact normalization
and provenance authenticity remain independent acceptance work.

## Backend read-only compatibility

Inspected, without modifying:

- `backend/app/api/v1/model_diagnostics.py`
- `backend/app/modules/autonomy/model_diagnostic_schemas.py`
- `backend/app/modules/autonomy/model_diagnostics.py`
- `backend/scripts/frozen_model_diagnostic.py`

The import adapter accepts an existing ADR018 `ModelDiagnosticRecord`, a saved
successful `/autonomy/model/diagnose` response envelope, or a saved successful
`GET /api/v1/autonomy/model?network_id=...` envelope/data object. The tool itself
makes **no HTTP calls**. GET selection requires exactly one configured
`diagnostic_id`, matching envelope scope and registered checkpoint status; it
never chooses the latest record implicitly. Field compatibility retains an AST
check against the current backend `DiagnosticResult` declaration. In addition,
tests now construct and JSON-roundtrip **the actual backend**
`ModelDiagnosticRecord`, `RegisteredModelStatus` and `ModelDiagnosticsResponse`
Pydantic classes before passing their serialized exports into shadow evaluation.
These schema-only imports require just stdlib/Pydantic, not a backend installation
or application startup; the production shadow code still imports no backend code.

The review found that the earlier hand-built GET fixture omitted required
`RegisteredModelStatus.history_references`, `benchmark_status`, `benchmark_scope`
and `benchmark_limitations`. That fixture has been replaced by the real validated
model serialization, including backend defaults and UUID/datetime/evidence-union
serialization. The values remain explicitly synthetic contract fixtures, not
archived measurement or model-registry acceptance. Bare record and saved POST/GET
envelope variants are tested. Envelope metadata contains the canonical fields;
no HTTP server, response middleware or authentication integration is claimed.

The adapter retains all existing result fields, validates normalized deterministic
policy probabilities, matches every model/input/provenance identity against the
operator manifest, and recomputes the diagnostic's existing `input_sha256` from
canonical JSON of the last observation. This mirrors the existing frozen CLI's
meaning: that hash identifies the **last observation**, not the entire encoded
history. The separately pinned full diagnostic bytes and `history_sha256` bind
history evidence identities. This evaluator does not rerun the frozen history
validator, rehash checkpoint/source files, or independently establish raw history
authenticity; those remain ADR018 producer/registry responsibilities.

Bare unscoped `nanfo-routing infer` output is not accepted as a backend diagnostic.
It lacks network/workspace/registry/history bindings; use an already recorded,
operator-verified ADR018 diagnostic export. Historical record creation time cannot
refresh old acquisition time. Backend APIs need no new fields or routes.

## Decision and domain-agent behavior

Every decision records scope/model identity, evidence sources and digests,
diagnostic action/path, alternatives, assumptions, qualification scope/limitations,
freshness, explicit abstention, analyzer findings and baseline comparisons.
`execution="not_applied"`, `safety_authorized=false`,
`production_dispatch=false`, `online_learning=false` and
`probabilities_are_safety_confidence=false` are literal output contracts.
`qualification.calibrated=false` and `safety_confidence=null` always.

- Capacity analyzer reports measured path capacities/utilization and threshold
  crossings; missing values report unavailable. It does not infer causal service
  bounds or predict counterfactual spare capacity.
- Failure analyzer reports loss and ICMP RTT evidence/censoring; it does not invent
  device failure attribution or forecast incidents.
- Policy analyzer checks the diagnostic action against the manifest review set;
  membership is neither runtime authorization nor a safety certificate.
- `DomainAgent.analyze(AgentContext) -> Finding` is an extensible pure-code protocol.
  No dynamic plugins or user-selected executable providers are loaded. Agent
  context excludes held-out outcomes, checkpoint loaders, network clients and
  executors. Future analyzers require reviewed code and domain evidence contracts.

Stale/future evidence, unqualified benchmark, forbidden review action or incomplete
required observations produce abstention. Invalid identities or incomparable
outcomes produce rejection, not a plausible decision. Censored RTT is preserved,
and missing paired RTT seeds are explicitly listed rather than imputed as zero.

All four baseline alternatives are retained, plus hold-and-review. Comparisons
report PPO-minus-baseline mean/min/max and sample standard error across matched
**seed episodes**, with metric direction and pair/missing counts. Standard error
is unavailable below two observed pairs. These are descriptive statistics, not
calibrated risk, confidence intervals, independent-packet replication, significance
claims or evidence that executing the current diagnostic action would help.
Unfavorable outcomes never replace the pinned model or alter analyzer findings.

## Verification (2026-09-19)

Commands run from `ai-engine` with the existing `.venv`:

```bash
.venv/bin/python -m pytest -q --tb=short
.venv/bin/ruff check scripts/shadow scripts/shadow_evaluate.py tests/test_shadow.py tests/test_holdout.py
.venv/bin/ruff format --check scripts/shadow scripts/shadow_evaluate.py tests/test_shadow.py tests/test_holdout.py
```

- Latest full AI suite after compatibility review: **433 passed** (previously 427),
  one existing Gymnasium infinite observation-space bound warning. Includes 97
  shadow cases and six holdout tests. Scoped shadow suite: **97 passed**.
- Scoped Ruff lint/format: passed. Whitespace check: passed.
- Initial targeted run exposed strict JSON datetime parsing with a model-before
  validator; fixed explicit timezone-aware ISO parsing while rejecting epoch input.
- First full run exposed a test import-path collision with the historical
  refinement `campaign` module (3 failures/418 passes). Restored `sys.path` after
  importing the new test subject; the complete rerun passed 427 tests. No frozen
  campaign implementation was changed.
- Holdout constructor inspection confirmed `started + 3600`, then minus 120.
  Controlled `monotonic()=1024.25` preserves exact deadline assertions without
  uptime-dependent floating cancellation; production deadline code is unchanged.
- Coverage includes all identity fields, cross-network/workspace imports,
  overlapping/wrong split seeds, selection ordering, outcome isolation from agents,
  stale/future/exclusive-expiry cases, missing/duplicate baselines, semantic drift,
  tampered files, malformed exports, probability misuse, and prohibited execution.
  Runtime traps reject subprocess/socket use and training/backend imports; an AST
  check enforces import separation; CLI tests verify evidence files stay unchanged.

### Reproducible artifact-free CLI example test

From `ai-engine/`, run:

```bash
.venv/bin/python -m pytest tests/test_shadow.py -k backend_export_cli_clean_checkout -v
```

Six end-to-end cases cover real backend-validated record/POST/GET fixture exports
through both the script and `python -m scripts.shadow_evaluate` entrypoints. Each
case creates an empty checkout layout containing only the new shadow sources,
writes operator-pinned fixture inputs into a temporary directory, and launches a
fresh Python process with a minimal environment (no `PYTHONPATH` or model/provider
configuration). There are no `src/`, checkpoint or artifact directories in that
layout. The script variant runs from an unrelated working directory; the module
variant runs from the copied `ai-engine/` root.

The child parses all pins and backend exports, calculates all 20 baseline metric
comparisons, and returns a validated typed decision. Deliberately expired input
acquisition time yields exit 2 / `abstain` / `evidence_stale`, with all execution
and authorization flags disabled and safety confidence null. The test checks
every temporary file remains byte-identical and no files were added. It then
tampers with the diagnostic export and verifies the same CLI returns exit 1 with
no decision on stdout. Fixture construction needs only checked-in backend schema
source and the existing AI test dependencies; no ignored historical files, live
inference, model registry or backend service is required in CI.

The review also fixed module invocation: the wrapper now uses a relative import
when invoked as `scripts.shadow_evaluate`, retaining the direct-script import path.

All new evidence fixtures are synthetic and test-only. No training, lab operation,
new physical measurement, model promotion or actual backend diagnostic invocation
was performed for this delivery.

## Integration and acceptance limits

| Capability | Delivered / remaining gate |
|---|---|
| Frozen diagnostic import | Implemented/tested for existing ADR018 export shapes; operator must supply authentic scoped export and independent pins |
| Matched baseline review | Implemented/tested for normalized complete V4 seed-level outcomes; actual historical normalization/raw audit remains to integrate |
| Qualification | Preserves reported benchmark scope only; cannot promote or independently requalify a checkpoint |
| Domain agents | Three useful deterministic evidence analyzers; no federated LLM/debate runtime or trained failure predictor |
| Freshness | Checks pinned acquisition and oldest outcome start; historical data never becomes live input |
| Live observer | Explicitly unavailable |
| Safety calibration | Explicitly unavailable; no physical bound/coverage claim |
| Executor and recovery | Explicitly unavailable; no dispatch/cancel/recovery interface |
| Backend installation | None; parent integration may consume operator output after reviewing the local schema; no API addition authorized here |
| Program completion | Remains evidence-gated under ADR021; unit success is not integrated or physical acceptance |

**P3 cannot activate from this foundation.** No trusted runtime model registry is
installed or established by these tests; a hash in a synthetic export is not a
registered model. Activation remains blocked until an independently provisioned,
validated model registry/qualification, compatible runtime observation/history
and frozen model/source contracts, physically calibrated safety bounds, and
receiver-authorized execution/recovery integrations exist and pass their separate
acceptance gates. Even after those gates are met elsewhere, this CLI remains
non-actuating; it has no activation or execution interface.

Next acceptance work is a read-only operator-reviewed normalization of a real
frozen benchmark plus authentic scoped diagnostic export, followed by independent
provenance and comparison audit. Compatible live observation, calibrated safety
bounds, receiver authorization and governed recovery remain separate ADR012 gates.
