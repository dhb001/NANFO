# ADR023 autonomous execution handoff

## ADR024 native manual-driver live evidence

User-authorized, exclusively owned disconnected campaign now completed:
42/42 native cases,480 actual policy mutations,10,120 sealed endpoint readbacks,
both actions actual6/6 ping after unseal, exact restart/STOP/foreign/idempotent
compensation and owned cleanup. Full source/image/protocol identities, failed
attempts and claim limits: `NativeDriverAcceptance.md`; raw evidence
`/tmp/opencode/native-driver-02z3yisx`. This is `native-driver-verified`, not an
autonomous calibrated installation or full receiver/API acceptance. Independent
review of this actual campaign remains pending. All prior calibration/model/runtime
activation gates remain enforced.149 scoped tests including retained raw replay pass.

## Health-review9–11 correction

Health secret admission now requires exact0600, root/service ownership, single-link
regular file, protected no-symlink ancestry and same-descriptor bounded hash/read.
Config/evidence pins remain nonsecret. GET+TTL are bounded to2s; authenticated age
is evaluated only after their final await. Expired old bodies reject even if another
publisher renewed the key. Client reload binds the full canonical config plus
pathname and configured byte hash; any change requires client/process recreation,
never silent retention of an older freshness/resource policy.

Pure FRR runtime constants moved to `emulation/autonomous_contract.py`; journal
client/settings/providers schema imports no privileged emulation driver. Source
fingerprints acknowledge this new file and `health_secret.py`; deployment was not
edited.309 scoped tests pass including36 actual PostgreSQL cases. Reviewer safe
cases10/10 pass; their three defect assertions and import-defect audit now fail in
the expected safe direction. Details/remaining independent sign-off are in
`ADR023Review.md`. No authentic calibration or live activation implied.

## Concrete API/client/receiver composition (implemented)

`installed_providers(sessions,redis)` now uses
`execution_client.installed_execution_clients` when either of the following is set:

* `NANFO_AUTONOMOUS_PROVIDER_CONFIG=/secure/autonomous-provider.json`
* `NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256=<exact config byte hash>`

Both must be complete and valid; application `EXECUTION_MODE` must be `emulation`.
Unconfigured defaults remain unavailable. Invalid/partial/production configuration
reports `autonomous_installation_invalid_or_incompatible`; it never silently installs
trusted providers. The existing live model registry settings remain separate.

The config executable schema is `execution_settings.ExecutionClientConfig`, version
`nanfo.autonomous-provider-installation/v1`: execution_mode, evidence_root,
source_root, calibration_path/sha256, provider_path/sha256, expected_scope,
trusted_preregistrations, trusted_attesters, accepted_guarantee_sha256,
accepted_runtime_sha256, accepted_equivalence_sha256, resource_id, health_key
ArtifactRef and health_max_age_seconds(default10, bounded1..30). Paths are protected
and bytes hash-checked; the existing independent calibration/runtime loader runs.
The health key is a separately provisioned random secret of at least32bytes, never
derived from evidence hashes. Restrict config/evidence/key access to trusted backend
API/worker/receiver identities and protected Redis ACLs; it is not a public endpoint.

### Process ownership

* API and AutonomyWorker receive concrete `CalibratedSafetyProvider` and
  `JournalExecutionClient.accept/verify/cancel`. The client enlists without commit,
  revalidates authority after lock waits, checks receiver health before and after
  staging, and has **no driver, namespace object or run method**. Existing worker
  code therefore does not start a privileged receiver in those processes.
* Manual cancellation remains `IntentCancellation`. Autonomous recovery is only an
  exact persisted cancel request; it remains callable if receiver health or the
  current installation becomes unavailable. Invalid config cannot grant new work.
* The standalone FRR receiver `serve` loads its separate `--config/--config-sha256`
  AND the two client environment variables above. Both installations/resource must
  match. It owns namespace attachment and physical mutation; it does not run model
  collection/training or stage caller jobs. Existing APIs/mode approval and worker
  decision cycle now provide the actual source path to durable acceptance.
* `recover --execution-id` uses filtered claim(execution_id,recovery_only=True),
  requires persisted cancellation and matching installation, forces operation=recover
  and never falls back to another row. Missing, leased, released or uncancelled
  targets cause no other dispatch. Recovery does not publish actuation readiness.

### Liveness/readiness

`readiness()` awaits the journal client's `refresh_status` before taking statuses.
Missing/invalid/stale/wrong-key/wrong-scope/nonexpiring receipts report unavailable;
status cache expires by monotonic time within the authenticated remaining lifetime.
Acceptance independently checks health again after durable staging waits.

Receiver emits HMAC-SHA256 receipts only after a real PostgreSQL poll/completed
non-uncertain journal iteration and successful read-only FRR namespace/path/inventory
probe. Idle polling can publish after its probe; there is no independent timer or
startup-ready assertion. Hung polling/probes cease renewal and TTL expires. Receipts
bind provider/runtime installation, resource, network/workspace/run, process UUID,
iteration and completed-at. These receipts prove recent trusted receiver progress,
not future availability or qualified physical bounds. No migration beyond0027 is
needed. Redis is transient readiness; journals/fences remain PostgreSQL durable.

### Deployment consequence

The **source composition gap is closed**: configured existing API readiness → worker
calibrated decision → journal-only accepted transaction → separate receiver checkpoint/
driver → persisted verification → exact cancellation request/recovery. No real
calibration has been supplied; mode activation still requires genuine independent
evidence, matching model/runtime, causal frames/history, current actor and receiver.
The existing LinuxFRR/old model fingerprint blockers remain, not bypassed by config.

Parent must rebuild/repackage from this updated source and rerun source-matched
deployment acceptance. New client/settings/health/providers source bytes are included
in the runtime fingerprint; regenerate/review pins rather than reuse the earlier
package's receipts. No privileged lab launch, shared migration, training or commit.

### Composition verification

**284 passed**, including **36 actual PostgreSQL cases**, scoped Ruff/whitespace
clean and receiver CLI import/help successful. New integration tests exercise the
actual configured factory, calibrated provider, worker and API service readiness;
separate database sessions see committed `accepted` before any fake-device write,
then a distinct receiver instance persists verified readback and exact recovery.
Missing health denies acceptance; staged acceptance is invisible until commit and
rolls back cleanly. Wrong-ID/uncancelled recovery cannot claim other jobs. Failed
device health probe publishes no receipt. Unit cases reject partial/default/
production config, missing/stale/wrong-MAC/foreign-scope/non-TTL progress.

Tests inject only the authentic-installation loading seam and observation/model/
authorization fixtures; no synthetic evidence is offered to the real independent
loader as calibration. Redis in this new composition lane is fakeredis; database
transactions are real PostgreSQL16 in an owned disposable container. Existing
Identity-revocation/lock races remain in the36 cases. This is source integration
verification, not deployed privileged device or full HTTP acceptance. Two initial
test-fixture failures (unreleased initial worker lease; missing API authorization
fixture) were corrected before the full passing rerun. Container removed afterward.

```bash
AUTONOMY_TEST_DSN=postgresql+asyncpg://postgres@127.0.0.1:55427/postgres poetry run pytest \
  tests/integration/test_autonomous_execution_postgres.py tests/unit/test_execution_client.py \
  tests/unit/test_autonomous_execution.py tests/unit/test_autonomous_frr.py \
  tests/unit/test_autonomous_frr_startup.py tests/unit/test_autonomous_frr_final_checkpoint.py \
  tests/unit/test_adr023_review_autonomy.py tests/unit/test_autonomy_service.py --no-cov -q
```

## Parent composition closure — contract before implementation

API/AutonomyWorker will install a **journal-only** executor and recovery-request
client from protected `NANFO_AUTONOMOUS_PROVIDER_CONFIG` plus
`NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256`. This is separate from model configuration.
Explicit emulation mode and independent calibration/runtime admission are mandatory.
The client has no driver, namespace attachment or run loop; manual cancellation
remains IntentCancellation. Privileged receiver alone consumes committed jobs.

Receiver readiness uses private `nanfo.autonomous-receiver-health/v1` Redis TTL
receipts: exact provider installation/runtime binding/resource/network/workspace/run,
random process identity, completion timestamp and monotonically increasing iteration,
authenticated with a protected hash-pinned HMAC key shared only by trusted backend
composition. Publish only after completed journal iteration and actual read-only
driver health probe, never a free-running timer. API verifies MAC, scope and age;
missing/invalid/stale receipt denies readiness and acceptance. This is bounded
liveness evidence, not calibration, actor authority or future execution guarantee.
Recovery requests do not need readiness. `recover --execution-id` must claim only
that exact cancelled row and never fall back to arbitrary work on the resource.

## Finding8 driver-boundary correction (2026-09-20)

Final checkpoint moved after every FRR inventory/binding read for adds and deletes.
The native namespace transport now exposes `mutate(name,args,checkpoint,timeout=5)`:
it validates the pinned PID/netns descriptor, prepares argv, invokes the synchronous
checkpoint callback and immediately starts the fixed command. Device-interface
implementations must preserve this ordering; no fallback to an unchecked write.
Dispatch and recovery callbacks remain distinct. Prepare writes no configuration;
verify only reads configuration and sends reachability probes. Failed apply does
not perform implicit cleanup: the receiver must enter independently owned recovery.

625 offline owner+reviewer-regression cases passed; scoped Ruff/whitespace pass.
Reviewer-positive defect repro preserved and now refuses its first write; adapted
safe reproduction proves22 reads, one revoked check, zero writes. Full evidence and
case matrix are in `ADR023Review.md` finding8. No live infrastructure was used.
Re-review new source fingerprints before installation. No calibration duration was
widened; the full inventory/checkpoint/transition timing must fit the independently
qualified budget, or final authority rejects before any next mutation.

## ADR023Review2–5 remediation (2026-09-20; supersedes earlier trust details)

**Implemented;349 scoped tests pass, including32 real PostgreSQL cases.** No real
calibration/guarantee was manufactured. Deployment/live qualification blockers below
still apply. Review reproductions were run before editing: all four reproduced.

* **Finding2:** independently preregistered `NetworkQualificationConfig.execution`
  now binds `nanfo.reviewed-execution/v1`, runtime discriminator, canonical executable
  plans by action ID, physical egress map (node/interface/queue_handle/source/
  destination) and physical demand map (source/destination logical and physical
  nodes/addresses). `SafetyInstallation.execution` must equal it exactly; every
  executable plan and logical route/physical chain is checked against that independent
  configuration. FRR plans omit only the runtime descriptor digest from the reviewed
  canonical plan to avoid a hash cycle; descriptor and equivalence evidence still
  require separate externally accepted pins. The immutable loaded configuration
  bytes remain in `ValidatedInstallation.reviewed_configuration`, and receiver
  authority rechecks the binding at dispatch. The FRR instrument's actual configured
  interface/queue/address mapping is also compared to it. Legacy measurement configs
  without an execution binding remain diagnostics, but cannot install an executor.
* **Finding3:** `0 <= actuation_delay <= policy.max_delay_seconds <= independently
  qualified total max_delay_seconds`; the reviewed scope also bounds policy total.
  Actuation is a component of total observation-to-transition delay. Shield expiry
  is exclusive at observed+total−actuation. Independent `validate_action` now checks
  elapsed observation age plus actuation against the total as well. A self-rehashed
  provider widening policy from a subsecond qualification to10s is refused.
* **Finding4:** Core frame acceptance runs Telemetry's public `evidence_item` over
  **both exact persisted JSON bodies**, then calls `TelemetryEvidenceService.pin`
  before inserting. This includes `telemetry_record:` strings, samples and nested
  recognized locators; pin IDs match historical/ORM enumeration. The previous
  custom `nanfo:autonomous-frame:` UUID scheme is superseded. Foreign workspace,
  foreign network and missing record references fail; pins and frame rollback or
  commit together. Duplicate locators are deduplicated by the public extractor.
* **Finding5:** control-first locking is retained. Checkpoint, begin-apply and
  verified-finish perform fresh authorization/deadline checks after contended
  execution/history locks, flushes and lock-renewal checks. Acceptance also rechecks
  after resource staging. No new device I/O occurs between acceptance and commit.
  Recovery continues to use exact ownership without requester impersonation.

### Regression evidence

`tests/unit/test_adr023_review_autonomy.py` rejects altered executable path, physical
egress/demand mapping, logical endpoints, widened total delay, missing independent
binding and unaccepted FRR runtime/equivalence descriptor. Tests distinguish a
reviewed envelope from the provider's own hash and cover exclusive remaining delay.
No test fixture is exported or installed as real calibration.

Ten actual PostgreSQL lock races cover role revocation/certificate expiry while
checkpoint/begin-apply/verified-finish wait on execution rows, plus begin-apply/
verified-finish waiting on provider history. Tests assert a real `pg_stat_activity`
Lock wait. Identity roles are real rows removed by a separately committed transaction;
the actual Identity profile/permission service is used (unrelated Network access is
stubbed). All fail before the simulated device boundary and preserve journal phase/
ownership. Four real pin transaction cases verify exact scope, invisibility before
commit and rollback of both frame and pins.

```bash
AUTONOMY_TEST_DSN=postgresql+asyncpg://postgres@127.0.0.1:55427/postgres poetry run pytest \
  tests/integration/test_autonomous_execution_postgres.py tests/unit/test_adr023_review_autonomy.py \
  tests/unit/test_autonomous_frr.py tests/unit/test_autonomous_causal.py \
  tests/unit/test_autonomous_frr_startup.py tests/unit/test_autonomous_execution.py \
  tests/unit/test_autonomy_service.py tests/unit/test_autonomy_safety.py \
  tests/unit/test_independent_validation.py --no-cov -q
```

349passed; scoped Ruff and `git diff --check` pass. The supplied vulnerability-positive
repro file was preserved unchanged: its plan/delay acceptance assertions now raise
on absent reviewed binding, its no-pin assertion observes an actual pin, and its
minimal lock fake lacks the newly required flush. The adapted regression and real
PostgreSQL race tests assert final revocation rejection directly, rather than treating
that fake's AttributeError as evidence of a security fix. Owned disposable PostgreSQL
was removed; no shared migration, privileged lab, training or commits.

## Ownership and implementation contract (published before code)

Migration **0027**, predecessor **0026**, is reserved for Autonomy provider frames,
execution journals and exclusive lab-resource fences. This work owns new
`autonomy/safety_provider.py`, `autonomy/provider_state.py`,
`autonomy/execution*.py`, `intent/autonomous.py`, and `emulation/autonomous*.py`.
`autonomy/providers.py`, existing Intent service and frozen AI/experiment files
remain owned by their respective workstreams. Parent owns deployment composition.

Factories will be `load_safety_installation(path, expected_sha256, validator)` and
`build_execution_providers(sessions, redis, installation, driver, resource_id)`.
The latter returns an executor and recovery provider implementing existing
`accept(db, ExecutionAuthorization)`, `verify(ExecutionReference)` and
`cancel(ExecutionReference)` contracts. Acceptance enlists without committing or
device I/O. Executor `run_one()` / `run()` processes durable accepted work.
Intent's new public `AutonomousAcceptance` boundary delegates only this separate
contract; it never creates manual approvals.

### Calibration/observer coordination

Existing `Observation` contains samples/evidence, **not** a feature dictionary;
existing `Proposal` contains `action_id`, checkpoint, observation contract and
evidence, **not** routes or bounds. Preserve these schemas. The measured observer
must register its exact canonical Observation digest and corresponding validated
`SafetyObservation` through `ProviderStateRepository.record_observation` in its
transaction. No missing-feature zero filling. An operator-attested baseline
`SafetyState` must be explicitly seeded and retained; subsequent accepted execution
updates history. Unknown/restarted measurement histories are blocked.

The installation is server-owned, hash-pinned, bounded JSON with version
`nanfo.calibrated-safety/v1`, workspace/network/run and observation-contract scope,
checkpoint allowlist, `SafetyPolicy`, `TrustedCalibration`, per-action routes and
measured queue service/error bounds, horizon/delay, and evidence manifest hashes.
Independent validator injection is mandatory: it validates raw evidence and
preregistered protocol, returning the digest of the exact installation it approved.
Self-asserted readiness, threshold-derived bounds and statistical extrema do not
create trusted calibration. Missing authentic evidence keeps deployment blocked.

### Isolated wire: `nanfo.autonomous-lab/v1`

This is a new private receiver invocation contract, not an HTTP route or an old
manual mailbox command. Fields (all required, unknown fields rejected):

* `version`: literal `nanfo.autonomous-lab/v1`;
* `execution_id`, `intent_id`, `decision_id`, `network_id`, `workspace_id`: UUIDs;
* `resource_id`: operator-installed exclusive lab identity; `fence`: positive int;
* `authorization`: existing immutable `ExecutionAuthorization` JSON;
* `installation_sha256`: hash of independently validated installation;
* `plan`: installed action's validated lab plan, bound to selected routes;
* `operation`: `execute` or `recover`.

Receiver loads the durable journal and compares the entire execute identity.
Recovery changes only operation; it cannot change plan, scope, IDs or fence.
Responses use existing `Verification`: execution_id, pending/verified/cancelled/
failed/uncertain, safe_to_release, evidence and reasons. Readback evidence is an
actual device configuration hash; verification does not claim traffic improvement.

The same durable record carries prepared rollback data, status, cancellation flag,
lease token/deadline and readback. Partial unique resource ownership excludes new
work even after lease expiry or restart. A monotonic resource fence survives
release. Receiver rechecks the persisted authorization, installed calibration,
current actor, control revision, STOP, approval/certificate deadline and ownership
immediately before every mutation. Redis serializes distributed workers; durable
ownership and receiver lock/fence remain authoritative if its lease expires.
Recovery uses exact journal ownership, independent of requester membership, and
never authorizes a new action. Only proven non-dispatch or verified compensation
releases exclusion. Verified installed policy remains owned until compensation.

## Deployment / acceptance gates

Production has no installed driver. Isolated emulation requires an explicitly
injected real driver, authentic calibrated installation, registered measured
frames/history, and migration0027. Existing OVS Actions may be wrapped only when
the receiver has sole ownership of its reserved resources and the manual/experiment
controllers are disabled. Keep journal storage durable across process restarts.
No privileged lab launch or training is authorized by this handoff.

Parent acceptance after handoff: serialize the authorized real lab campaign;
exercise exact readback, duplicate acceptance, concurrent resource exclusion,
STOP/revision/actor revocation/deadline at receiver, crash between mutation/result,
and exact compensating recovery. Unit devices are not live lab evidence.

Implementation/test results and final composition details will be appended here.

## Implemented handoff (2026-09-20)

### Exact interfaces for the other workstreams

* Continuous AI retains `providers.py`. Construct
  `CalibratedSafetyProvider(sessions, validated_installation)` and use
  `build_execution_providers(...)`'s `(executor, recovery)` in `Providers`.
  `AutonomyWorker.run()` starts an installed executor's `run()` task. API-only
  processes must not start that task. Worker acceptance now stages the decision's
  proposal/safety before calling accept, in the same transaction.
* Recommend now requires only observer/qualification/inference and records
  `recommendation_only`, `not_authorized_for_actuation` before safety assessment.
  Autonomous retains every safety/execution gate. No new public field or route.
* Observer integration: call
  `await ProviderStateRepository(db).record_observation(observation, safety_frame)`
  with the **same** returned `Observation` and actual measured `SafetyObservation`.
  Calls enlist without commit. Frame identities are immutable. Telemetry sample
  record references are pinned using Telemetry's public service before persistence.
  Provider frame reference UUID is UUID5(NAMESPACE_URL,
  `nanfo:autonomous-frame:` + canonical Observation digest); retention owner must
  include these new frame rows in historical reconciliation before full coverage.
* Operator history installation:
  `await ProviderStateRepository(db).seed_history(installation=installation,
  state=attested_safety_state, evidence=[...])`. Insert-once, never overwrite to
  bypass action history. The baseline routes must match actual pre-action lab
  readback. Incomplete attribution/history rejects dispatch.
* Independent validation is wired to the validator agent's actual
  `calibration_verification.load_trusted_calibration` through new
  `safety_installation.load_independently_validated_safety`. It reconstructs raw
  evidence using the independently owned module, then compares exact configuration,
  action-specific arrival/service/error/capacity profiles, route-to-egress chains,
  allowed old/new transitions, horizon/delay and threshold/drift policy. No fitted
  threshold or empirical extrema are converted to calibration.
* Intent public boundary is `intent.autonomous.AutonomousAcceptance(executor)`;
  no manual intent or approval rows are fabricated. Autonomy owns the execution
  journal; `intent_id` is an immutable logical correlation identity.

### Final provider installation v1 fields

`SafetyInstallation` in `safety_provider.py` is the executable schema. In addition
to scope/policy/calibration/evidence, it requires `configuration_sha256`,
`runtime_action: "isolated-ovs-autonomous/v1"`,
`transitions: [[old_action_id,new_action_id],...]`. Each action has `action_id`,
`routes`, `plan: LabPlan`, and `queues` containing `egress_id`,
`arrival_upper_bytes_per_second`, `service_lower_bytes_per_second`,
`service_upper_bytes_per_second`, `error_upper_bytes`, `capacity_bytes_per_second`.
These are exact reviewed profiles, not derived from the live queue threshold.
Current attributed arrivals must fit the installed profile; current capacity must
match. The independent calibration installation itself must be a hash-verified
entry in the provider evidence manifest. Operator pins also attest the OVS
plan-to-route mapping and actual baseline; do not install an arbitrary plan under
an unrelated action name. The independent queue validator does not certify OVS CLI
mapping or live device identity by itself.

### Parent deployment wiring

1. Apply migrations through0027 after0025/0026 are present. Import
   `app.modules.autonomy.execution_models` in Alembic metadata composition.
   Tables: `autonomous_resources`, `autonomous_executions`,
   `autonomous_observations`, `autonomous_provider_state` (all Autonomy-owned).
2. Protected calibration configuration supplies `root`, `calibration_path`,
   `calibration_sha256`, `provider_path` (root filename), `provider_sha256`,
   `expected_scope`, `trusted_preregistrations`, `trusted_attesters`,
   `accepted_guarantee_sha256`. No environment defaults or HTTP trust arguments.
   Do not mount mutable untrusted proposal directories as this root.
3. The explicit local composition is
   `execution_composition.compose_autonomous_lab(sessions=..., redis=..., lab=...,
   resource_id=..., results_directory=..., execution_mode='emulation',
   manual_enabled=False, experiment_enabled=False, calibration_config=...)`.
   It receives an **already admitted running Lab**, does not start one, validates
   the exact run and acquires the legacy `.executor.lock` for its entire lifetime.
   It returns `.safety`, `.executor`, `.recovery`, `.close()`.
4. This is an in-process receiver/device protocol deployment, not a remote mailbox
   bridge. The receiver process needs the backend Python runtime/dependencies,
   PostgreSQL/Redis access and access to the owned lab's `Actions` interface. The
   frozen Python3.9 experiment image is not a compatible backend worker image and
   was not changed. Parent must package the separate admitted receiver runtime or
   provide a driver implementing the documented async protocol with equivalent
   receiver-side authority; a manual mailbox adapter is not supported.
5. PostgreSQL journal and resource fences must survive process restarts. Redis
   locks are token checked and renewed at each mutation. PostgreSQL session locks
   serialize complete receiver calls; the original DB backend PID is checked at
   every mutation. Durable resource exclusion does not expire with worker leases.
   Device calls use shielded threads and wait for completion on task cancellation.
6. On shutdown, await receiver/device task completion before `.close()`. Compensate
   exact owned work before intentionally destroying a live lab. A different run
   cannot recover an old run's journal: retain exclusion for operator reconciliation.

Verified policies retain ownership (`safe_to_release=false`); worker history shows
verified without labeling ownership uncertainty. STOP/actor revocation/revision,
expiry, readback drift or interrupted apply requests exact recovery. Recovery
does not require the old actor's membership and cannot change execution identity.

### Verification so far / acceptance remaining

Disposable PostgreSQL16 at an isolated loopback port, real0027 upgrade/downgrade:
14 transaction/receiver tests passed; unit + existing autonomy regression campaign
288 passed at this checkpoint. Cases include transaction rollback/invisibility,
concurrent different/same acceptance, persistent fence increments, expired-lease
exclusion, two receiver connections, actual fake-device readback, post-accept
STOP/revision/actor/deadline/plan/calibration changes and restart compensation.
Independent validator adapter and legacy manual-lock exclusion have unit tests.

**No authentic installation was supplied or created.** Production remains blocked.
Parent-authorized serialized live lab acceptance remains pending; no privileged lab,
training, frozen experiment modification or commit was performed. Local synthetic
fixtures test arithmetic and lifecycle behavior, not measured calibration quality.

Continuous-AI owner confirmed the actual ADR014 passive feature contract lacks
the causal byte queues/attributed arrival bounds for `SafetyObservation`. Its
qualified runtime is Linux/FRR host-route; this driver's OVS policy is a distinct
runtime. The registry's historical qualification is therefore **not** evidence of
OVS action/runtime equivalence. Deployment remains blocked until authentic measured
frames, matching runtime/action qualification and exact mapping calibration are
installed. Do not bridge by converting packet queues to bytes or zero-filling
missing demand arrivals.

Final scoped gates after lock-renewal/retention integration: **288 passed** (including
14 actual PostgreSQL tests); legacy emulation suite **97 run, 6 skipped**, no failures;
scoped Ruff and `git diff --check` passed. Unit tests exercise three individual OVS
adapter mutation checkpoints and current readback with fake Actions. No live device
or deployment acceptance is claimed from those tests.

Follow-up run including independently owned validation regressions: **312 passed**.
The retention workstream has now added0027 frame/execution/provider-state enumeration
and transaction guards in Autonomy service; preserve those concurrent additions.

Final integration rerun with continuous live-provider tests: **348 passed**, including
**16 real PostgreSQL transaction/receiver tests**. Added stale-worker token rejection
and STOP between read-only preparation and the first write. One intervening run
failed because the synthetic fixture omitted the newly required runtime_action;
the fixture was corrected and the complete scoped command passed:

```bash
AUTONOMY_TEST_DSN=postgresql+asyncpg://postgres@127.0.0.1:55427/postgres poetry run pytest \
  tests/unit/test_autonomous_execution.py \
  tests/integration/test_autonomous_execution_postgres.py \
  tests/unit/test_autonomy_service.py tests/unit/test_autonomy_safety.py \
  tests/unit/test_autonomy_operator_controls.py \
  tests/unit/test_independent_validation.py tests/unit/test_live_providers.py \
  --no-cov -q
```

The command used an owned, disposable PostgreSQL16 container with tmpfs data and
unique schemas; shared PostgreSQL was not migrated. Test authorization callbacks
are injected while control/STOP/revision/history/journal transactions are real.
Current membership SQL and real OVS device acceptance remain parent live gates.

## Linux/FRR continuation: protocol published before implementation

New driver `emulation/autonomous_frr.py` will implement
`isolated-linux-frr-host-route/v1`. It preserves the actual frozen action map:
0=`access1,dist1,access2`, 1=`access1,dist2,access2`; h1↔h3 source-specific
/32 rules/tables19110/19111 on each router; h2↔h4 remains on FRR. New journal
preparation records all exact intended resources and the baseline routes before
any mutation. Restart compensation removes only matching persisted tuples, refuses
foreign selector/route state and verifies baseline route-get and background paths.
No frozen source, environment spec, image provenance or checkpoint loader changes.

Private wire v1 retains its envelope; `plan` gains a strict disjoint versioned
variant `{runtime:"isolated-linux-frr-host-route/v1", action:0|1,
runtime_binding_sha256:SHA256}`. The old LabPlan shape remains exact. Provider
installation's runtime discriminator accepts this new value only with a protected
independently accepted runtime-binding artifact, exact independently checked queue
configuration and plan/action map. Runtime binding records original checkpoint
contract/spec/image/source hashes **and** new receiver/acquisition source hashes,
namespace identity, action mapping and calibration configuration digest. It is
distinct from historical qualification, not an assertion that the original loader
accepts a new instrumented environment.

Validator-owner coordination: `CalibrationScope.configuration_sha256` currently
does not identify the driver. The execution adapter will require an externally
accepted hash of `nanfo.autonomous-frr-runtime/v1` in addition to existing reviewed
guarantee/calibration pins. This artifact binds network/run/provider/configuration,
driver/action map, model checkpoint/contract/spec and receiver/instrument source
fingerprints. The accepting independent review must explicitly cover runtime
equivalence; the adapter must reject missing/unmatched runtime evidence. No schema
change to the validator owner's files is made by this workstream.

Separate causal acquisition will retain native per-egress tc queue-byte endpoints,
departure byte counters and separately provisioned per-demand prequeue counters,
wall/monotonic read spans, route readback, unknown traffic/reset/drop failures.
Measured interval rates are diagnostics, never future arrival/service guarantees.
Only reviewed enforced demand envelopes may populate a SafetyObservation's future
arrival bounds; missing byte/drop/attribution/clock evidence blocks registration.
Instrumentation and its new fingerprint require preregistered independent
calibration; passive ADR014 history cannot be relabeled as this acquisition.

Parent startup will use an explicit protected pinned namespace/runtime configuration
and an exclusive receiver lock, with separate check/acquire/serve commands. Existing
manual and experiment controllers must be stopped before namespace ownership is
handed to the receiver. No arbitrary shell commands, namespace creation or privileged
launch are performed by this implementation session. Fresh qualified passive model
input is still required independently of causal safety input.

### FRR implementation and startup handoff

Implemented `LinuxFRRDriver` uses the exact two action paths, forward/reverse table
IDs19110/19111, static onlink /32 next hops and source/destination policy rules.
It reads **all** reserved router tables; unexpected selectors, marks, nexthops,
extra routes/rules or occupied unused routers stop mutation/compensation. Twelve
individual add commands each get a receiver checkpoint. Native route-get walks
both foreground directions and verifies unchanged background paths, then actual
ping readback. Restart recovery reconstructs only the persisted six resource tuples
and verifies the captured baseline after deleting them. No table flush is used.

`FRRPlan` is the isolated disjoint plan variant. Provider installation requires
`runtime_binding: ArtifactRef`; no FRR factory can omit its async dispatch guard.
The binding also records `baseline_action` (0 or1), nine PID/start-tick/netns-inode
identities and exact two action IDs. Namespace attachment pins open namespace
descriptors; PID reuse/namespace changes stop operations. A dedicated lifetime lock
excludes concurrent autonomous attachment. **Parent must terminate old experiment
and manual controllers and ensure exclusive ownership before handing namespaces
over**; a new filename lock cannot prove an old controller stopped.

#### Commands (provisioning only until parent admission)

Run in a separately packaged backend receiver runtime with `ip`, `tc`, `nft`,
`ping`, `nsenter`, access to the handed-off `/proc` identities, and the backend
PostgreSQL/Redis environment. Commands never launch/stop namespaces or a lab.

```bash
# Actual separate source map; does not alter historical environmentSpec/loader.
poetry run python -m scripts.autonomous_frr_receiver fingerprint --source-root /opt/nanfo

# Protected config pinned outside producer directories. Check performs no device I/O.
poetry run python -m scripts.autonomous_frr_receiver check \
  --config /secure/frr-receiver.json --config-sha256 CONFIG_SHA256

# Print nft JSON transactions only; no rule installation. Parent applies each
# per-node transaction only after privileged serialized campaign admission.
poetry run python -m scripts.autonomous_frr_receiver provision \
  --config /secure/frr-receiver.json --config-sha256 CONFIG_SHA256

# Read a bounded native window into a NEW file; never trains/fits/installs bounds.
poetry run python -m scripts.autonomous_frr_receiver acquire \
  --config /secure/frr-receiver.json --config-sha256 CONFIG_SHA256 \
  --output /evidence/new-causal-window.json

# Explicitly installed producer aligns and attests the causal frame with the exact
# existing public Observation digest; no automatic re-timestamping/feature synthesis.
poetry run python -m scripts.autonomous_frr_receiver register \
  --config /secure/frr-receiver.json --config-sha256 CONFIG_SHA256 \
  --capture /evidence/aligned-capture.json --capture-sha256 CAPTURE_SHA256 \
  --observation /evidence/observation.json --observation-sha256 OBSERVATION_FILE_SHA256 \
  --sequence 1

# Processes already accepted PostgreSQL work; startup is not autonomous approval.
poetry run python -m scripts.autonomous_frr_receiver serve \
  --config /secure/frr-receiver.json --config-sha256 CONFIG_SHA256 --once

# Exact journal compensation remains possible after actor/model/calibration expiry.
poetry run python -m scripts.autonomous_frr_receiver recover \
  --config /secure/frr-receiver.json --config-sha256 CONFIG_SHA256 \
  --execution-id OWNED_EXECUTION_UUID
```

`ReceiverConfig` in `backend/scripts/autonomous_frr_receiver.py` is the exact startup
schema. It names protected evidence/source/lock roots, existing calibration/provider
pins/scope/preregistration/attester/guarantee trust, independently accepted runtime
and equivalence digests, instrument path/byte hash/accepted **canonical** instrument
digest and actual receiver image ID. No defaults enable dispatch. `provision` and
`acquire` can run before completed calibration: they require explicit pinned recipe/
namespace handoff but confer no safety authority. `check/register/serve` require the
full independently reconstructed calibration. `recover` reads historical pinned
material and exact journal ownership without regranting expired dispatch authority.

`acquire` output deliberately has no `observation_sha256`; a separately reviewed
aligned producer must capture the actual model observation at that same endpoint,
retain its immutable reference and supply this binding. Registration checks exact
timestamp, run, runtime, instrument hash, native reconstruction and guarantee pins.
It does not convert interval rates to future bounds. Standalone acquisitions cannot
be registered as qualified model observations merely by changing their timestamp.

#### Instrument prerequisites / known measurement limits

`autonomous_causal.py` generates **non-actuating** netdev egress counter rules:
exact IPv4 source/destination/protocol demand partitions, named byte counters and
an unmatched counter. It reads those native tables plus one declared leaf netem
queue per egress, retaining byte backlog, departures, packet drops and read spans.
It rejects modified rule semantics, missing counters, counter reset, unknown bytes,
clock discontinuity, excessive read skew, endpoint conservation failure and any
drop delta (kernel tc output lacks dropped-byte counters). Source/normalized values
are reconstructed again at registration; self-asserted complete flags are insufficient.

This is a viable acquisition path **only on a reviewed compatible kernel/iproute2/
nft stack** with netdev-egress hooks and the declared byte-accounting semantics.
Frozen Debian Bullseye tools may not implement that hook. Upgrading them changes
runtime identity and requires a new accepted fingerprint/equivalence evaluation;
never substitute a forward-hook average or inferred drop size. OSPF, ARP, ICMP and
unclassified traffic hit unknown and block; complete control/background attribution
and all affected host/router egresses must be instrumented or separately accounted
by reviewed causal sensors. An IPv4-only counter recipe is not a claim that ARP or
link-layer traffic is covered. Failed windows remain evidence, not calibration.

#### Compatibility decision

The actual action **semantics** now match Linux/FRR. End-to-end qualified compatibility
is still **blocked**: current checked-in `experiment.environmentSpec('matched')`
uses version5, whereas the installed ADR014 registry requires version4 and frozen
source/spec/image evidence. The additional instrumentation/receiver has its own
source map and image. `validate_model_binding` requires exact checkpoint contract/
spec/action IDs and original source map; `FrozenModelProvider` still calls the
unchanged confined loader. No version translation, spoofed image ID or hash bypass.
An independent runtime-equivalence pin supplements, never replaces, model validation.

Parent needs: admitted exclusive FRR namespace handoff; actual matching frozen
runtime source/image distribution or separately qualified model; native instrument
support and complete causal attribution; preregistered train/holdout transition
measurements; reviewed arrival enforcement/service/within-window/sensor/delay
guarantees; exact runtime-equivalence/installation pins; aligned fresh passive model
observations; attested baseline history; current tenant actor/mode approval and0027.
Only then run serialized authorized accept→receiver→readback→STOP/revocation→recovery.

#### FRR verification result

Final scoped campaign: **323 passed**, including **18 real PostgreSQL transaction/
receiver cases**. The two added PostgreSQL cases use the concrete LinuxFRRDriver
against a fake kernel command/readback interface with real0027 journal transactions:
normal accepted→verified→revoked compensation, and restart after twelve kernel
writes/lost completion→exact restoration. Native acquisition tests cover rule,
counter/queue/capacity tamper, unknown traffic, drops, clock and source reconstruction.
Runtime tests cover explicit independent pins, scope, actual source digests and
unchanged model contract checks. Namespace tests open only the test process's own
namespace descriptor without setns or commands; stale start-time identity and
concurrent attachment are rejected. No actual privileged commands were executed.

```bash
AUTONOMY_TEST_DSN=postgresql+asyncpg://postgres@127.0.0.1:55427/postgres poetry run pytest \
  tests/integration/test_autonomous_execution_postgres.py \
  tests/unit/test_autonomous_frr.py tests/unit/test_autonomous_causal.py \
  tests/unit/test_autonomous_frr_startup.py tests/unit/test_autonomous_execution.py \
  tests/unit/test_autonomy_service.py tests/unit/test_autonomy_safety.py \
  tests/unit/test_independent_validation.py --no-cov -q
```

Scoped Ruff and whitespace checks pass. Receiver CLI `--help` works from backend.
Legacy emulation:97 run/6 skipped, no failures. Frozen `matched.py`, `ospf.py`,
`experiment.py` and `ai-engine/src/nanfo_routing` have no diff from this work.
An intermediate native acquisition test caught omitted route evidence in the
capture export; export was corrected and the full scoped campaign rerun. The
disposable PostgreSQL container is removed after verification; shared services
were not migrated. Parent deployment/current sprint consolidation stays with parent.
