# ADR023 Continuous AI provider handoff

## ADR024 actual fresh service acceptance — PASS (2026-09-20)

**Exclusive lab slot released.** Actual fresh feed → passive bridge → configured
LiveObserver/FrozenModelProvider → authenticated Autonomy controls → durable worker
recommendations passed. Final protected evidence:
`/tmp/opencode/nanfo-live-acceptance-7ngrbdgv/`.

Preregistration SHA256 `621f51b35e1baf5cc7bcd0d4be1dfdd1bd491238706f004e9d94ebf21025784c`:
fresh unused operational train-split seeds1010(path0),1011(path1), evaluation-only,
fixed acquisition action0, three measured reset/step frames each,2s windows/4step
contract. Six actual frames; no training or recommendation dispatch. Unchanged frozen
source/transport/env, derived checkpoint77dae44…, actual rebuilt v4image954462….
Campaign002 independent PASS and confined qualification revalidated before acquisition.

| Impairment | Durable recommendation IDs | Route | Age at persistence |
|---|---|---|---|
| path0 |8ebfeec2-9277-4c02-8610-c1f6d7ac45c3;4cb79b97-815c-484c-b243-c80cf766d825 |route1 both |14.155s;10.188s |
| path1 |44c4c681-ef91-47d4-8b08-2e8b4344cba5;6dce961d-2793-4e66-91ea-a5e9b701a6c8 |route0 both |13.370s;9.737s |

All four persist `recommended`, `recommendation_only`, `not_authorized_for_actuation`,
null safety/authorization/execution IDs. Two monitor observations also persisted.
Real password login/JWT, current Admin role and org membership enforce authorization;
unauthenticated access401, unrelated network404, subsequent Viewer membership write403.
Only DB/Redis transport dependencies used private stores; no auth/provider mocks.
Private PostgreSQL migrated through0027 and separate password-protected Redis.
Safety/executor unavailable. Credentials/tokens are absent from evidence exports.

Producer fsynced real session headers, then waited before reset until bridge's
actual EOF/clock-anchor acknowledgment. No measurement timestamps or response fields
were rewritten. The prepared fresh-provider helper passed both directions, requiring
observations newer than helper startup and exact acquisition receipts.

Real elapsed-time failure cases passed both directions: pause until original
observation exceeds30s → stale denial and durable blocked decisions; close → bridge
`passive_feed_closed` and unavailable marker; expired admission → explicit denial.
Freshness limit remains30s. Model inference did not drive the producer's fixed route.

Live integration fixes: Docker gives distinct time namespace IDs despite identical
kernel offsets; bridge now compares actual monotonic/boottime offsets when IDs
differ, retaining PID/start/boot/namespace fences and rejecting unequal/missing
offsets. Optional `NANFO_PASSIVE_PROC_SUDO=1` permits fixed read-only proc metadata
commands for the root-owned lab server; frozen inference does not inherit it.
Admission records actual Python measurement-server PID, not tini. New attachment
receipt allows an explicit before-reset barrier.

Earlier attempts preserved (no measurements): `nanfo-live-acceptance-4cwqu2gs`
rejected namespace identity before reset then hit harness timeout; exact resources
stopped/copied/removed and failure receipt retained. `nanfo-live-acceptance-0uvk90lb`
hit PostgreSQL temporary socket-ready startup race; fixed to wait for actual TCP
readiness; cleanup completed before any lab launch. All earlier preregistered seeds
were excluded from the successful attempt.

Exact cleanup: both owned lab containers stopped, raw outputs copied, IDs removed
and absence checked; private PG/Redis removed. Shared service IDs preserved.
No lab remains running. Raw JSONL/lab output, snapshots/admissions/receipts,
qualification/helper outputs, source manifest and durable decision exports retained.
`backend/scripts/audit_live_acceptance.py` reread these artifacts and verified raw
frame equality, clock-derived timestamps, correct fresh decisions, no actuation and
cleanup. `evidence-audit.json` inventories every retained file/hash/size.

Reproducible owned tools: `scripts/live_feed_evaluate.py`,
`backend/scripts/accept_continuous_feed.py --authorize-serialized-lab`, and read-only
`backend/scripts/audit_live_acceptance.py`. Final tests92passed/1opt-in skipped;
namespace offset regressions, scoped lint and whitespace pass. Historical support
still covered. This completes actual monitor/recommend service acceptance in the
qualified isolated domain, **not** causal safety, governed actuation or physicalRF.

## Interfaces / ownership (implemented)

Continuous-AI workstream owns new `autonomy/live_observer.py`,
`model_provider.py`, `registry.py`, private `live_schemas.py`, and standalone
settings; `providers.py` changes only `installed_providers` composition. No migration.
Execution workstream owns service/worker/execution models and migration0027 if needed.
Parent owns main/config/deployment.

Existing interfaces remain exact:
- `Observer.observe(network_id: UUID, workspace_id: UUID) -> Observation`.
- `ModelProvider.qualify(checkpoint_sha256: str | None) -> Qualification`.
- `ModelProvider.infer(observation: Observation, qualification: Qualification) -> Proposal`.
- Concrete `LiveObserver(registry)` and `FrozenModelProvider(registry, redis)`;
  shared `LiveRegistry.from_environment()`; configured providers selected by
  `installed_providers(sessions, redis)` without any API startup change.
- Private complete passive snapshot stays in protected operator files. Public
  `Observation.evidence` carries an immutable snapshot digest; inference reopens
  and verifies the exact snapshot, scope and freshness (no hidden mutable vector
  cache and no required public schema expansion). Proposal evidence includes model,
  source, registry, qualification and input hashes and deterministic action/path.

**Execution-agent integration requirement:** current `readiness(require_executor=False)`
still requires calibrated safety; current worker runs safety before recommendation.
ADR023 explicitly separates non-actuating continuous shadow recommendations from
actuation readiness. Please implement monitor/recommend readiness and worker branch
accordingly in your owned service/worker: recommend requires observer + authentic
qualification + inference, persists `recommended` with explicit non-actuating reasons;
autonomous retains all safety/executor gates. No model probability is safety confidence.
This agent will add worker-level provider tests against that branch once available.

Qualification timing: existing readiness has a5s budget. Raw five-policy replay is
longer, so `qualify()` starts one bounded background confined reconstruction and
returns `qualified=False, reasons=["live_qualification_pending"]`. Later worker
polls consume a backend-owned Redis receipt (300s TTL, registry+evaluator hash key),
revalidating checkpoint/source/benchmark files each time. No producer JSON can assert
qualification. Pending/failure never blocks the loop or grants inference. Runtime
shares the diagnostic CPU lock (130s qualification lease/120s wall/90s CPU; inference
retains40s lease/30s wall/25s CPU). Parent should keep the existing worker polling;
no new worker/main setting is necessary.

## Design and trust boundary

New private versioned registry binds exact checkpoint, full frozen source map,
independently checked qualification evidence, feature contract, network/workspace,
runtime, action IDs and expiry. Protected operator installation is separate from
producer evidence, never a `qualified: true` input. Inference reuses ADR018 Linux
Landlock/seccomp confinement and independent AI interpreter. Full historical
checkpoint compatibility is inspected before implementation; missing live features
are rejected, never padded. Frozen source/artifacts are read-only. Protected passive
input is explicitly operator-attested measured data, not automatic physical validation.

Tests use private synthetic fixtures and do not establish qualified live operation.
Actual available model replay and remaining artifact/measurement blockers will be
recorded here with exact commands/results at completion.

## Execution/safety bridge status

The existing ADR014 measured feature contract does **not** supply the causal queue
arrival/service bounds or wall-clock-bound `SafetyObservation` required by the
execution agent's `ProviderStateRepository.record_observation`. This provider does
not synthesize them from utilization/packet queues. Monitor/recommend need no0027
rows. Autonomous calibrated observation registration remains an explicit separate
producer/installation prerequisite; see `AutonomousExecution.md`. The public
observation digest is `contract_digest(observation)` and passive snapshot reference
is exactly `passive_snapshot:<sha256>` for a future authentic bridge. Model action
IDs are explicit registry `action_ids[0/1]`, paths are exact manifest action_map.

## Operator installation contract

Standalone settings (`live_settings.py`), all absolute paths:

| Environment | Meaning |
|---|---|
| `NANFO_LIVE_MODEL_REGISTRY` | Protected registry JSON outside artifact and observation roots |
| `NANFO_LIVE_MODEL_REGISTRY_SHA256` | Independently provisioned exact registry byte digest |
| `NANFO_MODEL_ROOT` | Read-only artifact/source/evidence root, shared ADR018 semantics |
| `NANFO_MODEL_PYTHON` | Exact independent AI interpreter; tested `ai-engine/.venv/bin/python` |
| `NANFO_LIVE_OBSERVATION_ROOT` | Protected operator-owned passive snapshot directory |

No live settings means prior default providers. Partial/invalid settings select the
concrete provider and report a specific blocked qualification/observation rather
than silently falling back. Existing worker/API factory selects the same providers.
No main/config/deploy/schema/migration changes in this workstream.

`LiveInstallation` in `live_schemas.py` is the private registry source of truth:
version1, model_id, checkpoint `{path,sha256,size_bytes}`, source_directory, exact
complete source_sha256 map, contract/spec hashes, exact runtime_versions,
observation_contract=`nanfo.passive-measured-v4.v1`,
runtime_action=`linux-frr-host-route`, two unique action_ids, scopes
`[{network_id,workspace_id,snapshot_path}]`, installed_at/expires_at,
max_observation_age_seconds1..30, plan/selection/report artifact references and
five `sessions:[{summary:ArtifactRef,evidence:ArtifactRef}]` in preregistered order.
Unknown fields (including `qualified`) fail. Root-owned or service-owned files and
ancestors must not be group/world writable; symlink/traversal/nonregular/oversized
files fail. Operator registry is not inside either producer root.

`PassiveSnapshot` fields: version=`nanfo.passive-measured-v4.v1`, exact network/
workspace UUIDs, unique snapshot_id, measured run_id (same as frame episode_id),
window_started_at/observed_at/published_at aware timestamps, source literal
`operator-attested-measured-lab`, contract/spec hashes, original complete
`history:{version:3,frames:[{request,response}]}`, and canonical history_sha256.
Publish complete immutable measurements via atomic file replacement at the installed
snapshot_path; do not change a snapshot during an inference attempt. The observer
reads and hashes bounded bytes, then inference reopens that exact digest before and
after offload. A newer publication during inference causes rejection/retry on the
next worker cycle, never silent use of mismatched evidence.

All13 features are mandatory: two capacities, two utilizations, two queue counts,
RTT, loss, goodput, offered rate, measured actual offered rate, background rate and
seconds since route change (13 total), plus explicit previous action. Missing/null
values are rejected except RTT's original verified-outage semantics. Encoder adds
RTT availability and previous-action one-hot to produce16 values. Numeric
normalization uses the original float schema, not missing-value substitution.
Frozen CLI additionally verifies all raw measurement derivation, complete drain
queues/counters, exact environment spec/image provenance and trained distribution.
Only stationary path0/path1, matched Linux-FRR,2s windows/4-step scope is supported.
An ADR009 generic history or vector-only JSON cannot be installed as this observer.

Wall-clock freshness is explicitly operator-attested: original experiment timestamps
are monotonic and cannot prove current wall time. Re-timestamping old history would
be a false operator attestation, not measured live acceptance. No producer/reset/
step/control call is made by these providers. Current live collector output must
actually satisfy this contract before live readiness can be claimed.

## Authentic qualification / confinement

The legacy `qualification.py` importer supports older validation-only v3/normalized
dossiers and correctly leaves them unqualified; it cannot ingest ADR014 holdout as
if it were that older format. New runtime explicitly supports
`adr014-test-only-v1` preregistration/selection: exact selected checkpoint/source/
runtime, original training-plan linkage,12 reserved seeds3900..3911, five complete
matched policies, full raw logs and frozen deterministic PPO replay. It reconstructs
all report fields and computes both constant-baseline reward margins/positive paired
intervals, both directional responses, and the preregistered OSPF goodput-lower>0 /
ICMP-RTT-upper<0 criterion. Producer report/qualification booleans confer nothing.
Qualification means this exact scoped benchmark only, not physical safety or general
superiority. No training, mutable best.json lookup, source rewriting or relaxed
checkpoint loader is used.

New fixed entrypoint `backend/scripts/frozen_live_inference.py` runs under the same
AI interpreter with `-I -B`, stripped environment, private HOME/TMPDIR/cwd, unchanged
staged source, original weights-only loader, Linux x86_64 Landlock ABI>=5 + seccomp,
no network/control/exec/fork access. Source/model/evidence remain read-only; only
scratch is writable. Parent bounds stdout/stderr to64KiB each and kills/reaps on
timeout/cancellation. Runtime versions and all returned hashes/action path/input are
validated. Qualification receipts are generated only by backend runtime code, never
by input registry flags; Redis must remain backend-owned/protected.

## Verification and blockers (2026-09-20)

-28 provider tests passed: explicit installation, partial config, scope, protection,
  symlink, feature omissions/nulls, timestamp/hash tampering, self-asserted
  qualification denial, actual confined benchmark, exact historical inference,
  qualification pending/cache lifecycle, changed snapshot and postoffload fences,
  child timeout/cancellation/output overflow kill-and-reap.
-99 existing autonomy/diagnostic/confinement regression tests passed.
-Disposable PostgreSQL16 + real Redis7 worker lane passed: new worker instances
  consumed installed providers and persisted `observed` and `recommended` with
  unavailable safety/executor; recommendation has no authorization or execution.
  Private safety/executor fixtures then verified actual committed `accepted` decision,
  authorization and proposal were visible from a separate DB session before verify;
  pending verification retained ownership as `uncertain`. Containers were removed.
  This tests durable acceptance glue, not device dispatch or calibrated live safety.
-The raw model artifact exists and qualified **only for the scoped historical
  benchmark**. Checkpoint SHA256
  `5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`,
  report SHA256 `f323186fee013a3c55acac9e061500c2245c36976db01495a86f48a83c57392b`.
  Real historical replay action0, probabilities
  `[0.9718289375305176,0.028171034529805183]`, value3.2172513008117676,
  input SHA256 `ea3a62d0a12bbc608b75b49b10a294bbcaeb2ec9ce276f07965d490352c5729a`.
  Historical replay results explicitly use operation=`replay`, no live snapshot hash.
-Live blockers: no authentic current full passive snapshot producer/installation,
  no independent causal safety bounds registered with execution provider, no physical
  qualification. Protected installation must be provisioned explicitly. Test fixtures
  are never an install recipe for relabeling historical measurements as current.

Commands from `backend/` (explicit backend interpreter used):
```sh
PY=/home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python
$PY -m pytest tests/unit/test_live_providers.py -q --no-cov
$PY -m pytest tests/unit/test_autonomy_service.py tests/unit/test_model_diagnostics.py tests/unit/test_model_diagnostic_confinement.py -q --no-cov
NANFO_LIVE_PROVIDER_POSTGRES=1 $PY -m pytest tests/integration/test_live_provider_worker.py -q --no-cov
```

Execution agent's worker/service recommendation branch is integrated and verified;
provider files preserve public Observation/Proposal schemas. The optional autonomous
safety-state bridge remains blocked on actual missing measurement semantics rather
than writing invented0027 provider frames.

Runtime compatibility blocker confirmed with execution agent: this checkpoint's
qualification binds **Linux/FRR host-route** actions. The new isolated execution
driver is **OVS** (`isolated-ovs-autonomous/v1`). Even a complete future causal safety
frame would not establish runtime/action equivalence. Do not install these together
for autonomous dispatch without separate authentic matching-runtime qualification.
Scoped continuous recommendations and the existing durable decision APIs work now.

## Passive producer follow-up (2026-09-20)

Implemented new `emulation/passive_observer.py` operator bridge and
`emulation/PASSIVE-OBSERVER.md`. It consumes **newly appended actual** frozen
LoggedTransport IPC records from an admitted evaluation evidence.jsonl; no experiment
socket/control/traffic/training calls and no frozen source edits. EOF attachment,
process/boot/time-namespace binding, wall-monotonic anchor, measurement-time conversion,
protected admission/session hashes, full confined original validation before atomic
publish, immutable acquisition receipts and unavailable markers on cleanup are
implemented. Existing protected provider snapshot contract is consumed unchanged.

Complete passive polling cannot supply the frozen contract: reset/step owns real
traffic, route configuration and sender/drain lifecycle. The bridge only observes
an independently authorized active instrument feed and preserves its actual request
and response. Current emulation source isv5; selected checkpoint isv4 with exact
source/image binding. Parent must admit preserved matching runtime, not relabelv5.

28 private producer tests cover EOF/partial records, append/truncate/rotation/symlink/
permission/size, evaluation-only admission, original frame preservation, stale/replay/
future/foreign-runtime/terminal frames, PID/boot/namespace/wall-clock changes, protected
publication, actual confined frozen measurement compatibility/tamper rejection and
validate-before-publish/receipt/disconnect lifecycle. Tests are not live acquisition.
No lab launch or active collection was performed. Parent's serialized acquisition
acceptance remains pending. The precise minimal Linux/FRR governed-driver plan and
OVS alternative are in `emulation/PASSIVE-OBSERVER.md`; neither claims OVS qualification.
Concurrent execution workstream now supplies `autonomous_frr.LinuxFRRDriver` under
`isolated-linux-frr-host-route/v1`; integrate that owned adapter rather than duplicating
it. Actual action/runtime-binding acceptance, exclusive experiment handoff and causal
calibration are still required; its existence does not qualify the driver.

## ADR024 rebuilt registry coordination (implementation in progress)

Backend owns only live schemas/registry/confined validator/provider and its own new
integration runner/tests. Recovery/runtime agent owns derived writer, preregistration,
campaign, image and capture. No privileged launch by this workstream.

Exact proposed additive installation fields for recovery writer coordination:
`qualification_protocol: "adr024-rebuilt-evaluation-v1"` and
`parent_checkpoint: ArtifactRef` (required for rebuilt, forbidden for historical).
Historical default remains `adr014-test-only-v1`. Actual parent and derived bundles
are consumed independently and must differ **only** in lab_provenance.lab_image_id;
weights_sha256 and original tensor payload bytes must be identical. External source
map/operator registry remain pinned. New evaluation must pass original five-policy,
12-seed raw replay and all constant/directionality/OSPF gates. Never transfer old
qualification to the new image. We will match the generated plan/selection/session
fields in RuntimeQualification.md before finalizing new protocol validation.

Provider validator needs these preregistration facts from the campaign writer:
plan protocol/version, actual checkpoint identity and parent identity, exact AI
source/runtime, actual image;12 fresh seeds and reserved-seed inventory binding;
policy order,2s/4step/path0,path1; declared wall+monotonic+boot/time-namespace identity;
capture start/end per policy (raw measurements must follow declaration), original
frozen training-plan canonical hash used in summary.plan_sha256 (distinct from new
operational plan byte hash). Original frozen CLI does not emit wall capture stamps,
so the new writer must provide an authenticated capture ledger/receipt ArtifactRef;
timestamps cannot be inferred from file mtime or added after outcomes. Ledger binds
each actual raw/summary hash and runtime before/after capture. Backend cannot infer
missing fields or accept a passing report without these bindings. Please publish
exact generated fields in RuntimeQualification.md so validators match writer exactly.

Read new `scripts/adr024_campaign.py`: plan uses `created_unix`, summary plan_sha256
is new plan byte digest, seed-audit/lineage are separate JSON refs. Existing
`feed-attachment.json` has wall+monotonic pair before reset (session_sha256 includes
the newline); backend can enforce plan.created_unix < attached_unix and all raw
measurement intervals > attached_monotonic. **Please add those five feed-attachment
ArtifactRefs to deployment-registry sessions**, plus copy parent checkpoint into
output as parent-checkpoint.ptz and provide its ArtifactRef. Backend will use optional
`BenchmarkSession.attachment`, and installation `lineage`, `seed_audit` refs required
only for rebuilt. Source/runtime/raw image equality plus these externally pinned
attachments retain honest chronology. No mutation of frozen CLI needed.

### ADR024 provider support implemented; qualification awaits actual result

Exact fields implemented: installation `qualification_protocol`, `parent_checkpoint`,
`lineage`, `seed_audit`; each of five `sessions` adds `attachment`. Evidence refs are
required only for rebuilt protocol, bounded and hash/size checked. Campaign
`deployment-registry.json` is an evidence index, **not** a directly installable
LiveInstallation: parent constructs a protected scoped registry, removes producer
status/qualified fields, includes original parent bytes and five attachment refs,
then pins registry bytes outside both producer roots. No campaign source or evidence
mutation is needed for that installation.

Validator matches actual `adr024_campaign.py` fields. Summary.plan_sha256 is the
**new plan byte hash**, superseding the earlier provisional original-plan suggestion.
Attachment session_sha256 includes the header newline; feed_offset must match its
actual byte length. Attachment wall time follows plan.created_unix, and all60 raw
reset/step windows per policy follow attachment monotonically. Each raw/summary
image/spec must match the derived artifact. Both bundles pass the unchanged original
reader/loader; original cli.report reconstructs five policies and deterministic PPO.
Both protocols share original strict gates. Software-attested clock chronology and
externally pinned seed audit do not claim cryptographic timestamp/physical proof.

Prepared parent-stage runner (no lab start or snapshot generation), from backend:
```sh
PYTHONPATH=. /path/to/backend/python scripts/verify_fresh_live_provider.py \
  --network-id <installed-network> --workspace-id <installed-workspace> \
  --timeout-seconds 180
```
Use protected model settings and private REDIS_URL. It waits for independently
reconstructed qualification, then accepts only observations newer than runner
startup with matching acquisition receipts. It emits concrete provider qualification,
observation/proposal hashes and receipt. Failed campaign returns blocked before
inference. It does not select a mode or fabricate durable decisions: parent runs the
existing worker with authentic scoped control and separately verifies its recommended
row. No private timestamped test fixture is used by this runner.

Active campaign002 uses derived77dae44… with unchanged tensor payload3e7e38… and
plan b9e084a… seeds3003..3014. It is still collecting at this handoff. This support
grants **no qualified availability** until the actual five-policy campaign completes
and independently passes. No privileged action, writer/campaign edit, training or
original-image impersonation was performed by this workstream.

ADR024 scoped verification: **34 tests passed**, including read-only validation of
the actual `/tmp/opencode/nanfo-adr024-evaluation-002/checkpoint.ptz` against the
untouched parent and private rejection fixtures for lineage/seed/gate/chronology/
runtime/failed-campaign/fresh-feed boundaries. Existing live-provider28 tests also
passed with original historical confined replay. Scoped Ruff and git diff --check
passed. Actual derived lineage validation is not a fresh campaign qualification;
no complete new report exists yet at this checkpoint.
