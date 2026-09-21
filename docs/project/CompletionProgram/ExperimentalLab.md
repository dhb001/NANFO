# ADR025 experimental-lab integration handoff

Status: core implemented and transaction-tested; this document is the internal protocol
handoff for the transport, simulation and campaign owners. No calibrated-autonomy
mode or public API enum is added. ADR025 is the authority for this separate CLI.

## Exact public internal protocol (v1)

### Campaign unblock interface (2026-09-20, supersedes older identity text below)

* `ExperimentalPolicy.policy_kind`: `model` (default), `fixed0`, `fixed1`, or
  `heuristic`. `InferenceRecord.policy_kind` must match. Baseline `result` is
  `ComparatorResult`, `proposal` is `BaselineProposal` with checkpoint null, and
  `qualification` is explicitly null. `ComparatorAdapter(policy).infer(frame)`
  chooses ordered fixed route or least utilization, then least packet queue, then
  lowest index. Its rule/input/action are independently reconstructed at admission.
  All variants use the SAME controller simulation/authority/execution/recovery.
* `snapshot.run_id` MUST equal raw `history.frames[0].response.data.episode_id`.
  `policy.run_id` is only journal identity. Optional `policy.measurement_run_id`
  binds an already-known episode; otherwise an authoritative bootstrap receipt
  binds the newly generated episode. Without either, old run equality applies.
  Never rewrite raw episode or snapshot episode to make a journal UUID match.
* Campaign first captures exact original receiver baseline READ ONLY, constructs
  `BootstrapCommand`, then calls `controller.admit_bootstrap(command)` BEFORE reset.
  This creates the run and commits `bootstrap_prepared` receipt with baseline,
  ownership, receiver-policy, runtime and core-policy hashes. Reset uses
  `controller.checkpoint` at receiver mutation boundaries. After reset call
  `controller.complete_bootstrap(BootstrapReceipt)` with authentic episode and
  exact registry/checkpoint/weights/model-source pins, then
  `controller.run(admitted_bootstrap=True)` on that SAME controller instance.
* Transport implements `recover_bootstrap(command, checkpoint)` returning
  `BootstrapRecoveryReceipt`: request, command, original baseline and ownership
  hashes; `restored`/`uncertain`; complete independent evidence. Called even if
  inference failed before action preparation or STOP arrived before observation.
  It restores the receiver-owned original baseline, not an inferred route index.
  The original receiver remains the independent cleanup owner. A missing method,
  uncertain receipt or crashed reset retains core resource ownership. Campaign
  wraps reset/complete/run in try/finally recovery; restart uses `recover()` only.
  Preferred helper: `await controller.bootstrap(command, reset)` performs admission,
  supervised `await reset(command, checkpoint)`, completion and failure recovery.
  Reset callback returns `BootstrapReceipt`. It never replays reset after uncertainty.
* `LiveModelAdapter(registry, redis, policy, equivalence_path=...)` uses the unchanged
  confined qualifier/inference and retains complete `RuntimeResult` metadata.
  Call `await model.prepare()` BEFORE bootstrap/acquisition to prequalify (expensive).
  Infer atomically publishes canonical original-episode snapshot in its registered
  private observation path. No receiver credentials/transport enter inference.
  `wrapper_equivalence_sha256` pins a `WrapperEquivalence` JSON file; distinct
  `model_adapter_sha256` pins `live_adapters.py`. Equivalence binds exact runtime,
  registry/checkpoint/weights/model source, evidence digests and explicit scope.
  Existing frozen full validation remains required; incompatible wrapper evidence
  fails rather than rewriting its provenance or claiming formal calibration.

Use a 30-second action bound and an I/O bound/lease accommodating real roundtrips
(roughly4s acquisition and8s inference, measured separately). There is no fabricated
subsecond live guarantee. Repeated cached verification may preserve original
timestamps only; core independently rejects age>policy maximum (never above30s).

Final checkpoint order: complete journal lock waits/flush/commit, current authority,
recheck durable STOP/time, then current owning-service authority/time read. A final
bounded transaction then locks the resource/run and pending action, validates the
current control identity and STOP, flushes lease state, and uses the public owning
Identity/Network services on that SAME session for fresh DB authority. It compares
control identity (policy hash/fence/lease token/monotone STOP/release), ownership and
all deadlines after those reads and checks time again after commit. This prevents
STOP acknowledged during earlier Identity I/O from yielding a dispatch grant, and
preserves revocation detection after blocking journal I/O. The final transaction
is bounded to min(5s, installed I/O timeout); timeout rolls back and denies.

No lab/model/transport I/O occurs inside that transaction. Receiver invokes the
callback AFTER its blocking write-ahead/readback work, immediately before each
mutation. A STOP competing with the final locked decision serializes on its control
locks; it cannot acknowledge a commit while those locks are held. This is a short
empirical ordering point, not an atomic database-to-kernel mutation guarantee.
After commit, receiver must consume a request/fence/mutation-bound acknowledgement
exactly once at its sole-writer hook and recheck receiver STOP/time before the add.
Queued/old approvals must never authorize mutation after acknowledged receiver STOP.
Watchdog checks cannot issue or reuse mutation acknowledgements. Recovery remains
an independent exact-owned permission and does not perform user authorization.

Receiver/campaign integration note: the parallel receiver's earlier handoff setting
`policy.run_id=bootstrap.episode_id` is no longer required. Bind receiver journal
`run_id` to core journal UUID and measurement episode separately. `observe` must
validate actual episode against `measurement_run_id` or authoritative bootstrap
receipt, not force journal UUID equality. Transport also needs `recover_bootstrap`
for pre-inference failure cleanup. These requirements supersede earlier handoffs.

Import contracts from `app.modules.autonomy.experimental.schemas` and protocols
from `app.modules.autonomy.experimental.ports`. All methods are async. All returned
contracts are validated again by the controller; hashes use `contract_digest`.
Use **`experimental.schemas.contract_digest`** for both Pydantic records AND raw
dicts (baseline/history); the older `autonomy.schemas.contract_digest` accepts only
Pydantic records. Transport owner: update your digest import accordingly.

* `observer.observe() -> MeasuredFrame`: complete `PassiveSnapshot`, canonical
  `MeasuredFeatures`, full existing `Observation`, and `RuntimeIdentity` (resource,
  container, image, source and wrapper pins). Preserve raw history, timestamps,
  run/snapshot IDs, counts and provenance; unavailable measurements stay null.
* `model.infer(frame: MeasuredFrame) -> InferenceRecord`: the exact frame digest,
  complete `RuntimeResult`, `Proposal` and `Qualification`. No authority in model.
* `simulator.simulate(frame: MeasuredFrame, inference: InferenceRecord,
  policy: ExperimentalPolicy) -> SimulationRecord`: frame/inference/policy digests,
  selected `action_id`, `admitted`, `assumptions`, `objectives`, `reasons`,
  `evaluator_sha256`, and complete numerical `result: dict`. This is configured-model
  experimental admission, never a safety certificate. Simulation owns this adapter.
* `transport.prepare(command: ActionCommand) -> PreparedAction`: READ ONLY capture
  of exact original owned state; returns the unchanged command, `baseline: dict`,
  `baseline_sha256`, `ownership_sha256`. The request UUID, resource/fence, run ID,
  bounded route, policy/frame/inference/simulation digests, expiry and runtime pins
  are already in the command. No reset/route mutation during prepare.
* `transport.execute(action: PreparedAction, checkpoint: Checkpoint)
  -> ExecutionReceipt`: `Checkpoint = Callable[[], Awaitable[None]]`. Adapter must
  invoke it immediately before EACH mutation, inside its exclusive resource lock,
  including after lock waits. Reject stale fences and duplicate execute UUIDs;
  persist driver ownership before mutation. Receipt binds request/action digests,
  exact route, outcome (`applied`/`uncertain`) and complete evidence.
* `transport.verify(action: PreparedAction) -> VerificationRecord`: independent
  exact route readback plus actual traffic metrics, timestamp/window/count
  provenance, action digest, run identity and evidence. Never trust an applied
  receipt as verification. Missing counts/metrics cannot pass.
* `transport.recover(action: PreparedAction, checkpoint: Checkpoint)
  -> RecoveryReceipt`: cancel pending work and restore ONLY exact owned baseline,
  independently read it back, bind request/action/baseline digests; status
  `restored` or `uncertain`. Idempotent recovery is allowed, execute replay is not.
  Recovery checkpoint validates durable ownership/fence/lease only, independently
  of expired/revoked operator approval and STOP. Foreign state must stay untouched.

Transport must share the lab's common process-family lock with all routing code;
measurement never changes routes. Recovery must fence pending old execute before
returning restored. A timeout never proves cancellation. Uncertain recovery retains
exclusive durable ownership. Neither lease expiry nor STOP releases a resource.

## Composition

`ExperimentalController(sessions, authority, ports, policy)` owns transactions.
`Ports(observer, model, simulator, transport)` is dependency injection for real
adapters. A protected hash-pinned installation selects an importable adapter factory
`module:function`; it receives `policy` and `options` and returns `Ports`. CLI factory
loading is explicit and source-hash pinned, never selected by inference/user JSON.
`Ports` calls optional synchronous `adapter.bind_checkpoint(checkpoint)` on observer/
transport immediately after controller construction (deduplicated if same object).
This is local wiring only, no I/O. Use it to bind transport heartbeat authority for
`observe`/`verify`; execute/recover still receive their distinct checkpoints explicitly.
Frame snapshot `run_id` equals the original raw episode UUID, bound through explicit
`measurement_run_id` or committed bootstrap receipt. The policy journal UUID stays
separate. Route tuple order must equal frozen action-index order.

Review PR-03 correction: `loss_fraction` and `max_loss_fraction` are UDP loss.
ICMP loss is independently derived from `probe_sent`/`probe_received` and gated by
`max_probe_loss_fraction` (conservative default zero). They need not be equal.
Simulation/verification owner must return **UDP** `VerificationRecord.loss_fraction`,
and map `max_probe_loss_fraction` independently; an earlier simulation handoff that
called this field probe loss is superseded by the corrected core schema.

Existing-provider bridge: `live_adapters.LiveFrameObserver` and
`FrozenInferenceAdapter` retain the complete existing frozen subprocess result.
Snapshot files for that bridge must use canonical sorted compact JSON with no
trailing newline, so existing registry exact-byte SHA equals the core canonical
snapshot SHA. Original registry episode/run equality checks still apply. A wrapper
with a different envelope must use a separately pinned experimental model adapter.
Transport now uses `experimental.schemas.contract_digest` for raw dicts and
implements `bind_checkpoint`. The bootstrap recovery method and distinct episode
binding are the current additional transport handoff.
Campaign owns actual live adapter composition and lab acquisition. Transport owns
emulation implementation. Core owns CLI, schemas, durable policy/controller/journals,
and migration0028 (after0027). Simulation imports the schemas above directly.

## Durability and policy

Dedicated Autonomy-owned resource/run/action/append-only receipt tables. Commit
phase and input records before any driver I/O; no driver/model/observer/simulator
await occurs inside a database transaction. Phases: observing, inferred, simulated,
preparing, prepared, dispatching, verifying, holding, recovering, restored, rejected,
uncertain. Restart never executes an existing action: cancel if never prepared,
otherwise recover the exact persisted action. Immutable receipts are append-only.

Policy binds actor/network/workspace, disposable disconnected lab/runtime pins,
model registry/checkpoint/weights/source pins, exact routes/devices, preregistration,
simulation assumptions/objectives, verification thresholds, <=30s observation age,
dwell, total/window action counts, maximum action duration and absolute expiry.
Current Identity/Network owning services recheck membership/permissions before
admission and every mutation. STOP is irreversible for a run and survives restart.
Fresh policy/run admission cannot bypass unresolved resource ownership. Restoration
is an independent capability restricted to the previously persisted owned state.

## Validation and remaining acceptance

Core tests exercise actual AsyncSession PostgreSQL transactions, committed-before-I/O
visibility, concurrent resource exclusion, durable STOP, stale/expired/revoked gates,
receipt immutability, uncertain dispatch and restart restoration. No privileged lab
launch is part of core work. Joined live campaigns and independent acceptance remain
the campaign/review owners' responsibility; fixtures are not measured lab evidence.

Controller also polls current authority, STOP, ownership and action deadlines while
observer/model/simulator/driver I/O is outstanding. It cancels the await and enters
exact recovery on interruption. The receiver's independent watchdog/fencing remains
required: asyncio cancellation and elapsed time do not prove a remote mutation ended.

## Operator installation and CLI

Migration `backend/alembic/versions/0028_experimental_lab.py` follows0027. It creates
four separate `experimental_lab_*` tables, a partial unique unresolved-action
index, database-enforced immutable receipt payloads and write-once action/policy
bindings. No calibrated-control/provider table is modified. Apply through the
normal approved Alembic deployment; tests apply/undo0028 only in isolated schemas.

The protected installation JSON has exact fields:

```text
version: "nanfo.experimental-installation/v1"
policy: ExperimentalPolicy.model_dump(mode="json")
factory: "installed.module:build_ports"
factory_sha256: SHA256 of that module's exact source bytes
source_pins: {"/absolute/dependency.py": exact-byte SHA256, ...}
options: factory-owned validated composition configuration
```

Include the factory source itself and all adapter/wrapper/model-entrypoint sources
in `source_pins`. Ancestor paths must be owner/root-controlled, non-symlink and not
group/world-writable. The installation file's hash pins all policy and factory
options before acquisition. Factory construction is read-only: it returns ports,
never acquires/resets a lab. Runtime acquisition remains campaign-owned.

From `backend/`:

```bash
poetry run python -m scripts.experimental_lab status --config /absolute/installation.json --config-sha256 HASH
poetry run python -m scripts.experimental_lab stop --config /absolute/installation.json --config-sha256 HASH
poetry run python -m scripts.experimental_lab run --config /absolute/installation.json --config-sha256 HASH
poetry run python -m scripts.experimental_lab recover --config /absolute/installation.json --config-sha256 HASH
```

Alternatively set `NANFO_EXPERIMENTAL_CONFIG` and
`NANFO_EXPERIMENTAL_CONFIG_SHA256`. Database/Redis use existing backend settings.
`status`/`stop` do not import the adapter factory, so unavailable adapter dependencies
cannot block the durable STOP latch. `run` requires a new run UUID and refuses an
existing run even if released. `recover` is repeatable, uses the exact installed
policy and persisted baseline, and deliberately does not call user authorization.
A live different controller lease blocks recovery takeover until expiration;
expiration alone never releases lab ownership. Preserve the original installation
and pinned recovery implementation until ownership is verifiably released.

## Initial core verification record (2026-09-20)

* `tests/unit/test_experimental_lab.py`: **14 passed**.
* `tests/integration/test_experimental_lab_postgres.py`: **18 passed**, actual
  PostgreSQL/asyncpg with0028 upgrade/downgrade per unique test schema. Private
  unprivileged cluster under `/tmp/opencode/experimental-core-pg-20260920`, port56483;
  no shared database was migrated. Real Identity profile/role SQL revocation was
  tested; Network access is mocked in that focused role-revocation test.
* Additional existing parallel workstream suites: adapter/simulation/campaign,
  **44 passed** at the inspected revision. These are unprivileged fixture tests.
* Core-owned files: scoped Ruff clean; CLI `--help` and scoped whitespace pass.

Regressions cover complete frame hashes, model/route/simulation mismatch, stale
data, missing metrics, independent UDP/ICMP loss, protected configuration hashes,
transaction rollback/visibility, concurrent ownership, STOP-before-run and STOP
racing admission, immutable receipts/latch, total/window/dwell budgets, final
mutation checks, real role revocation after lock wait, ambiguous apply, uncertain
restoration retaining ownership, restart without replay, recovery without renewed
approval, and STOP/expiry interrupting blocked verification.

Remaining joined acceptance belongs to the campaign/review owners. In particular,
the transport must honor read-only observation/preparation or preregister/journal
its initial lab setup separately before core observation. Core cannot classify an
unannounced reset in `observe()` as read-only acquisition. Receiver process-death
recovery, exact-original cleanup and wrapper equivalence require the independent
transport evidence described in `ExperimentalReview.md`.

## Campaign-blocker revision verification (2026-09-20)

Combined core PostgreSQL/unit, simulation, adapter and campaign suites: **100 passed**.
Scoped Ruff clean. This includes true-episode canonical model publication using a
stubbed frozen subprocess (no new measured model or lab result), honest comparator
records/reconstruction and all three baseline kinds through the durable joined
controller. Actual PostgreSQL tests prove committed bootstrap ownership before reset
I/O, lost-reset acknowledgement recovery without replay, missing cleanup retaining
ownership, STOP before inference preserving baseline authority, immutable authentic
episode binding, and a journal UUID distinct from raw episode through the whole loop.

Regression also revokes authority after the final journal commit and confirms the
last current-authority read rejects the mutation callback. Cached verification
timestamps are rejected after30s. Numerical verifier mapping was inspected:
`verification_record` uses UDP loss for `loss_fraction` and the separate policy
probe threshold for ICMP. No existing calibrated provider/mode was changed.

The approved action-duration schema now caps actions at30s. Successful fixture
actions use1s rather than the former fragile0.1s; dedicated expiry tests remain
short. Live policy must allow its real transport roundtrips and retains the same
30s age/duration ceilings. Private PostgreSQL testing only; no privileged launch.

## Final checkpoint STOP/revocation correction (2026-09-20)

Independent `test_stop_during_final_current_authority_read_is_not_admitted` from
`/tmp/opencode/test_adr025_integrated_review.py`: **1 passed** on the corrected core.
Core unit + actual PostgreSQL suites: **51 passed**. The independent missed-STOP
interleaving is also retained as a repository unit regression. Deterministic tests pause
both outer current-authority awaits, commit/acknowledge STOP on a separate DB
connection, resume the reads and require denial. Another pauses the final journal
flush, commits a real Identity `UserRole` deletion, and requires403 from the current
owning-service check. A blocked final locked authority is bounded, rolls back, and
allows queued STOP to commit. Prior journal-wait revocation and final-commit
revocation regressions still pass. Scoped Ruff clean. Migration head remains0028;
existing immutable policy/fence/token and irreversible STOP supply control identity.

## Experimental telemetry retention closure — migration0029

**New migration head:0029**, after0028. Controller operational flow is unchanged.
`experimental/references.py` installs guards when experimental ORM models import;
direct repository/CLI writes therefore receive the same protection as service
writes. Every recognized reference in `LabRun.policy`, all five `LabAction` JSON
fields, and `LabReceipt.payload` is pinned in the owner's flush transaction before
the evidence commits. This includes frame samples/history/provenance, inference
and qualification evidence, simulation, baseline, bootstrap, verification and
recovery receipts. Existing explicit frame-list pins remain conservative aliases.

Extraction uses Telemetry's existing `reference_ids`/`evidence_item` grammar only:
`record_id`, `source_record_id`, `telemetry_record_id`, their declared list forms,
`telemetry_record:<UUID>` strings and supported serialized evidence fields. Other
UUIDs, episode/snapshot IDs and hashes are not inferred to be telemetry references.
Network/workspace scope comes from the hash-verified immutable owning run policy;
nested payload scope never overrides it. Missing, malformed and foreign references
reject the owner write and roll back its pins. Version-bound reference IDs match
historical enumeration and remain idempotent on replay. Public Telemetry pin
services retain pin/delete serialization and permanent released-pin protection.

Autonomy reference pagination now has nine stages, preserving the original six
and appending experimental runs/actions/receipts. Cursor v2 wraps the stage/key;
valid older cursors restart at stage0 so no old history is silently skipped.
Experimental tables are optional on older deployments; same-owner joins resolve
authoritative run scope, without cross-module table joins. Malformed historical
references use the existing `unknown_retained` reconciliation semantics.

Migration0029 changes coverage metadata only: globally revoke Autonomy coverage,
reset every completed/in-progress Autonomy reconciliation to cursorNULL and zero
counters, and preserve all telemetry, pins, journal evidence and other owners'
coverage. Re-enrollment requires the real owner-service historical scan through
all nine stages. Its new registration time conservatively retains pre-enrollment
records, including the prior unprotected interval. Downgrade also invalidates
coverage; it never reinstates an obsolete completeness claim. Deploy matching
guards/enumerator with0029 before resuming reconciliation/retention workers; an old
worker must not re-enroll against its obsolete six-stage contract.

Only a private PostgreSQL instance is used for migration/race verification. No
shared database migration is performed. Parent deployment/head assertions must
advance to0029; campaign evidence remains pinned to its original source snapshot.

Retention verification: **97 passed** across the new reference unit/PG tests,
existing retention unit/PG tests, and experimental controller PG regressions.
The new suite contains7 unit and13 actual PostgreSQL cases, including nested
recognized locators in every persisted action field, receipt-only references,
policy references, foreign/missing/malformed scope rollback, receipt replay,
released pins, workspace-isolated pagination, legacy cursor restart, completed and
in-progress coverage invalidation across workspaces, historical scans/re-enrollment,
unknown-history preservation, both pin/delete race orders and deleted-event replay.
Scoped Ruff and whitespace checks pass; Alembic reports exactly `['0029']`.

An intermediate broad rerun encountered a private-cluster `pg_depend` disk-quota
error; compacting that catalog with `VACUUM FULL` resolved the test-environment
blocker. Final97-test run passed. The existing blocked-verification expiry test
now waits with a1s fixture budget and accepts either genuine expiry checkpoint
error while asserting verification was entered; production timing/flow is unchanged.
