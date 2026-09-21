# ADR025 independent experimental design review

## Frozen013 / outcome-v2 acquisition review — one reproduced audit blocker

Reviewed the executable snapshot, not mutable workspace code:
`ai-engine/artifacts/adr025-runtime-preparation-013/`, manifest SHA-256
`c2edcba14d8fec1efa5b2f8bf957b5f8922b10f86d8364bc34db82ed0069a030`.
Independent verification confirmed all **1,794 manifest files** and the pinned AI
interpreter digest. All seven declared readiness flags are true, including0029.
No source/snapshot edits, lab, Docker or database startup occurred.

### Closed findings and accepted protocol scope

IR-01 receipt aliasing and IR-02 foreign-selector cleanup are **closed** in this
snapshot: all five independent integrity probes pass against its actual code.
Canonical receipt snapshots stay unchanged after restore/replay; unexpected rule
selectors are denied. Snapshot runtime/receiver hashes:

- `emulation/experimental_lab_runtime.py`:
  `b7af4548159f0c5be64314e38ec25c20c38af7636028de2c4c75c12eec611e1a`.
- `emulation/experimental_lab_receiver.py`:
  `30291515919c9250557c06591ef8c70cb006db364b86a1ff87cb29cea984b9c9`.

Accept the revised **empirical outcome semantics**: a genuinely complete bad
measurement followed by verified exact restoration is a completed experimental
rejection, with candidate success=false. Simulation rejection has no post-action
metrics and is not rollback. Invalid/unknown measurements, missing evidence and
unexplained control failures remain protocol failures. Broad common thresholds
are unchanged and baselines retain the complete paired denominator. Existing model
qualification is an input requirement, never qualification earned from these
experimental rejected outcomes; formal calibration/production remain false.

The full raw-frame exporter now copies every journal-listed hash (including failed
responses), retains exact byte and canonical hashes, and the classifier refuses a
missing inventory entry.0029 invalidates old Autonomy coverage under table locks;
the snapshot includes experimental reference enumeration and current metadata0029.
These are verified offline properties, not a claim that migration or acquisition
has been performed by this reviewer.

### V2-01 — High: rejection branch can hide unexplained control failure and missing action recovery progression

**Exact source:** frozen013 `backend/scripts/audit_experimental_lab.py:336–389`,
SHA-256 `54ed017078332068a0893a1b2b0ea1430b33528f0807e7d860dccc94be12b1af`.

`classify_nominal()` calls `audit_journal(..., positive=False)`, which checks
bootstrap receipts but does not require the action's dispatch → interruption →
recovering → restored progression or compare the action recovery record against
the durable restored payload. At lines381–385 a failing raw window plus **any**
`verified` receipt is accepted as `performance_rejected_then_restored`, even if
that verified receipt describes a passing window. The branch returns before
reading the controller result at386–389. The alternative receiver-reason check is
also an unbound set across all receipts, not the failed command/window identity.

**Independent reproduction:**
`/tmp/opencode/test_adr025_outcome_v2_review.py::test_rejection_requires_action_restore_progression`
runs the real frozen classifier, numerical replay and journal checker. Its explicit
offline fixture uses a valid owner-contract chain and raw-count reconstruction,
hash-valid bootstrap receipts, a generic `verified` entry, a released/restored run
flag, standalone recovery receipt and exact native baseline readback. It deliberately
omits durable dispatch/interruption/action-recovery progression and sets controller
status=failed with `UnexpectedControlFailure`. The classifier nevertheless returns
protocol_complete=true. No production validator is mocked during classification;
fixture envelopes are synthetic and never represented as new measured evidence.

**Required correction:** introduce an outcome-specific rejection audit. Bind the
failed retained frame to the exact execute/verify request, selected action and
episode/index; require actual threshold-failure evidence for that frame, an allowed
corresponding controller/receiver termination, and ordered durable exact-action
recovery receipts equal to the exported record. A `verified` marker alone must
not establish rejection enforcement. Reject unexplained control failures even
when another window performs poorly. Retain and audit bootstrap cleanup separately.
Apply these checks to smoke classification too, since it calls this same branch.
Do not solve this by changing performance thresholds or discarding negative trials.

### Independent checks from frozen013

- **115 tests passed:** targeted backend suites including preserved raw numerical
  tests, plus all five independent receipt/foreign-state probes.
- **20 emulation tests passed.**
- **9 retention/STOP tests passed:** seven reference-enumeration unit cases and
  the two independent final-STOP probes. No DB integration claimed.
- New outcome-v2 tests: **2 passed, 1 failed**. Invalid measurement remains
  protocol failure with all aggregate metrics null; omitted failed frame is
  rejected. The desired invariant forbidding the false accepted rejection fails
  as described above. The first test invocation exposed a test-fixture reset/step
  mismatch; that synthetic envelope was corrected before the reported reproduction.

The protocol design and adapter corrections receive positive scoped review.
**Reviewer approval for the exact frozen013 acquisition pipeline is withheld for
V2-01**, because its smoke/nominal completion classifier can certify the wrong
outcome. After the audit correction and negative regression, use a new immutable
snapshot/gate receipt and fresh preregistration through the existing procedure.
This conclusion concerns empirical evidence correctness, not formal causal
guarantees or actual campaign results. Existing snapshots/evidence are unchanged.

---

## Post-fix integrity recheck — two new reproduced defects

This is the latest review status and supersedes the earlier three-blocker list.
No live lab, Docker, private/shared database or external Redis operation was run.
Production source was not edited; new independent probes are in
`/tmp/opencode/test_adr025_integrity_recheck.py`.

**Previous findings:** both independent STOP-interleaving probes now pass. The
core performs a bounded final control-locked transaction with current owning-service
authorization; the receiver rechecks STOP/abort/expiry after bootstrap admission
I/O. The new sole-writer `dispatch_authority(entry)` hook is separate from watchdog
`authority()`; the independent writer-plus-watchdog probe produces one grant.
`copy_private()` now writes exact-hashed bytes through container stdin to the live
mount, and the setup-file publication uses it. Fresh source-matched preregistration
remains an enforced prerequisite, not a newly reported defect: old plan001 is not
approval for changed bytes.

### IR-01 — High: retained receipts alias mutable runtime state

**Locations:** `emulation/experimental_lab_runtime.py:57–62` and
`emulation/experimental_lab_receiver.py:263–296` (inspected revisions below).

`state()` exposes `routing.owned` directly. `Receiver.handle()` incorporates that
object into a response and stores the same response in `self.receipts`. Subsequent
`MatchedRouting.close()` clears that list. Consequently an already delivered
bootstrap/execute response changes in memory, is rewritten with different contents
on the next journal persistence, and replays as different bytes for the same
immutable request ID. Other nested mutable state should be checked when fixing
the snapshot boundary, not only this one list.

**Reproductions:** three independent offline probes use the real Receiver,
GuardedRuntime and original preserved MatchedRouting over the existing fake kernel:

1. Bootstrap, serialize response, recover, replay identical bootstrap request:
   response bytes differ (`action_paths.owned` changes from six tuples to empty).
2. Bootstrap, save a detached delivered response, recover, read actual journal:
   the stored historical response no longer equals the delivered response.
3. Execute route1, save its serialized response as a lost receipt, recover:
   native journal response differs from the saved lost receipt. This directly
   violates the ambiguous-result auditor's equality requirement in
   `audit_experimental_lab.py` (`ambiguous_result_not_durable`).

**Correction:** detach complete receipt payloads at acceptance/publication using a
canonical JSON snapshot or equivalent deep copy; store immutable receipt bytes or
detached values and return detached replay results. Keep current runtime state
separate. Assert byte-for-byte stability across successor changes, restoration,
subsequent persistence and replay. These probes do not claim new measured traffic;
they reproduce corruption in actual receipt/lifecycle code without device I/O.

### IR-02 — High: cleanup accepts foreign rule semantics and deletes them

**Locations:** `GuardedRuntime.restore():166–179` delegates to frozen
`recovery/emulation/matched.py:138–164`; wrapper `command():64–103` validates
the deletion argv against owned tuples, not the complete observed rule semantics.

Frozen `close()` considers priority/table/source/destination sufficient identity.
A rule in that slot with an additional selector such as `fwmark` passes its check.
The wrapper then admits a broad `ip rule del` lacking the additional selector.
This is not exact-owned cleanup and can remove changed/foreign forwarding state.

**Reproduction:** install route0 through the real guarded original routing routine
over the fake kernel; add `fwmark='0x123'` to the observed `access1:19110` rule;
invoke `runtime.restore()`. It does not raise, issues deletion and reports original
restoration. The new test expecting foreign-state denial fails. This establishes
the missing readback validation and admitted deletion; no claim is made of a live
kernel reproduction.

**Correction:** in the separate wrapper, validate complete allowed rule/route
semantics and all reserved resources before destructive cleanup, including
unexpected selectors/extra rows. Reject conflicts and retain unresolved ownership.
Preserve the frozen source; add wrapper regressions for extra selectors as well
as changed source/destination. Revalidate ownership at the mutation boundary.

### Verification and scope

- Current targeted suites: **104 backend offline tests and 13 emulation tests
  passed**. No PostgreSQL integration tests were launched.
- Earlier independent core/receiver STOP probes: **2 passed**.
- New independent writer/watchdog separation probe: **1 passed**.
- New integrity probes: **4 failures**, representing the two defects above
  (three receipt-stability manifestations and one foreign-rule-cleanup check).
- Actual confined qualification/inference was rerun through `LiveModelAdapter`
  with preserved raw histories and explicitly offline clock envelopes, using
  in-memory Redis. Both directions again returned the original actions and
  probabilities recorded below; complete raw histories and episode IDs stayed
  unchanged. The new separate wrapper pin is
  `004b19d972cf3c3e9a6924f65d9c25854e3bf0f4c0e85b5fecc28b3b4a1e1560`;
  original lab provenance and checkpoint remain distinct and unchanged.
- Preregistered numeric replay again passed common-baseline equality with the
  declared broad empirical thresholds. No posthoc threshold changes were proposed.

Readiness remains **changes required for receipt integrity and exact-owned
cleanup**. Closure of the earlier defects is a positive offline readiness finding,
not actual campaign acceptance, formal calibration or permission to share the
exclusive campaign slot.

| Inspected source | SHA-256 |
|---|---|
| `backend/app/modules/autonomy/experimental/controller.py` | `f49275c4b1cc7c6a9ee760102a579a7ad8d5a23a397a8f7f22664f0b8001c75d` |
| `backend/app/modules/autonomy/experimental/authority.py` | `19eb1452d8977c00484f88bc9df14e0c35121a34108a7a4f02a232e5c11a2f10` |
| `emulation/experimental_lab_runtime.py` | `63faa8bdd46e60de28fa0aa555873a74020f1ac7cfb5b26f2c2844dcdd12b664` |
| `emulation/experimental_lab_receiver.py` | `676520f19598474b7a0b978e1f0c7b2f2947d462a1f2adaa9504f8bba516aa1f` |
| Preserved `recovery/emulation/matched.py` | `da13903064be198d52485a06593528d6d11d313bb2f4202e9137c5b1f9bb18fc` |

---

## Integrated prelaunch recheck — current verdict: BLOCKED

This section supersedes the initial availability/status findings below. Reviewed
the composed controller, campaign dispatcher, receiver/adapter and numerical
simulator against prepared plan
`/tmp/opencode/nanfo-experimental-campaign-001/plan.json`, SHA-256
`92736d20a8b1f6f022bfa927b6e2821fdc714065140c908dbfa46a97a9cf33eb`.
No lab, Docker operation, database or external Redis service was launched.

### Current blockers (actual defects only)

1. **High — final authority read can miss an already committed STOP.**
   `backend/app/modules/autonomy/experimental/controller.py:84–96` reads durable
   STOP, then performs its final awaited Identity/Network check, then returns
   after checking only time. STOP committed during that last blocking service
   call is not reread. Independent probe made the final authorization await
   commit STOP; the actual `checkpoint()` returned successfully. This can issue
   the campaign's per-add approval after durable core STOP.

   A related receiver path is reproducible at
   `emulation/experimental_lab_receiver.py:152–168`: bootstrap checks STOP before
   protected policy/admission reads, then returns without rechecking STOP/abort.
   The probe latched actual receiver STOP during `bootstrap-admission.json` read;
   `authority()` still returned success. The campaign's final `super().authority()`
   uses this same bootstrap branch.

   **Correction:** finish blocking authority/admission reads, then revalidate
   durable STOP/control revision and current ownership/time at the defined final
   dispatch boundary. Bootstrap must also recheck receiver STOP/abort and policy
   expiry after its admission read. Preserve owned recovery permission. This is
   a concrete missed-check interleaving, not a requirement for formal instantaneous
   revocation guarantees.

2. **Medium — watchdog duplicates mutation approvals and breaks final audit.**
   `backend/scripts/verify_experimental_lab.py:259–287` overrides general
   `authority()` to append an approval whenever the last transcript entry is an
   unfinished add. The writer and `Receiver.watchdog()` (`202–215`) both call it.
   Pending kernel I/O leaves `entry.completed=None`, so the watchdog can reuse
   the same challenge response and append a second approval. Independent probe
   called the real campaign authority twice for one pending mutation: two events
   with the same challenge ID were recorded. The final auditor explicitly requires
   `len(matched) == 1` (`audit_experimental_lab.py:363–370`), so this valid concurrent
   schedule fails campaign acceptance with `native_add_without_current_owner_authority`.

   **Correction:** keep mutation challenge/receipt issuance in the sole writer's
   final-mutation hook; let watchdog authority check liveness without issuing
   another mutation approval. Preserve one authoritative challenge receipt per
   mutation and test actual writer/watchdog overlap. Do not simply relax the
   auditor to accept arbitrary duplicate approvals.

3. **High for this requested launch — plan/source pins are stale.**
   The read-only command
   `python -B -m scripts.verify_experimental_lab check --output /tmp/opencode/nanfo-experimental-campaign-001`
   fails with `implementation_changed_since_preregistration`. Independent
   `source_pins()` comparison found ten changed/added paths: experimental
   `verification.py`; Identity `repository.py`, `service.py`; Network
   `deletion.py`, `outbox.py`, `repository.py`, `schemas.py`, `service.py`,
   `topology.py`; Simulation `history.py` (all under `backend/app/modules/`).

   **Correction:** retain plan001 as preparation history. After defects are fixed
   and source is stable, rerun relevant offline gates and preregister the actual
   source snapshot through the existing fresh-plan procedure. Do not bypass the
   mismatch, overwrite archived source, or carry a readiness claim from old bytes.

### Independently checked resolutions and numerical/model evidence

- **Bootstrap recovery is present in the integrated composition.**
  `CampaignTransport.recover_bootstrap():604–619`, forwarded through
  `CapturedPorts`, returns the core `BootstrapRecoveryReceipt` after baseline hash,
  empty-owned state and original forwarding readback checks. Its absence on the
  base `ExperimentalLabAdapter` is not a missing-method defect in this campaign.
- **Episode identity is distinct from journal run identity.** The campaign adapter
  retains the receiver's actual episode, and the core binds it via the durable
  bootstrap receipt. It does not rewrite raw `episode_id` to the control run UUID.
- **The prior WAL ordering defect is fixed at the runtime wrapper.**
  `GuardedRuntime.command():87–99` performs WAL and fault hooks before final
  authority. The remaining STOP defect is inside that final authority sequence,
  described above.
- **Cleanup no longer actuates or measures.** `restore():162–182` closes exact-owned
  routing and checks original empty tables/paths; it never calls `change()` or
  `frame()`. Recovery additions are explicitly rejected.
- **Targeted owner suites:** 101 backend offline tests passed, including preserved
  raw simulation/verification cases; 12 emulation offline tests passed, including
  original frozen routing equivalence, partial apply, WAL revocation and no-add
  cleanup. No PostgreSQL integration suite was run in this offline review.
- **New independent probes:** `/tmp/opencode/test_adr025_integrated_review.py`.
  Four desired-invariant probes fail on the defects above (source drift, final core
  STOP, bootstrap STOP, duplicate approval). Two positive probes pass: real
  confined model replay and preregistered numerical baseline equivalence.

The model probe ran actual full frozen qualification and actual confined inference
through `LiveModelAdapter` with in-memory Redis only. It used preserved measured
raw histories, unchanged, inside an explicitly synthetic **offline clock envelope**;
it is not a claim of newly acquired wrapped lab measurements. Actual results:

| Historical raw scenario | Model action | Probabilities [route0, route1] | Critic value |
|---|---|---|---|
| path0 | route1 | [0.012521963566541672, 0.9874780178070068] | 2.609820604324341 |
| path1 | route0 | [0.9661532044410706, 0.03384681046009064] | 3.0927767753601074 |

Both passed `inference_allowed`; original raw histories/image/source provenance
were unchanged and actual episode IDs differed from the journal UUID. Checkpoint
was `77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614`.
Original lab-source pin remains
`08c312c64154c9aedcd3b22eeb3573783590e0eb7183bc999cb8ef39b958dbbd`;
separate current wrapper pin is
`0e102ab00fe276cff73425da1648506fab68fe626478c9a45f13057f25ec1b1b`.
The model-adapter/equivalence receipt is separately pinned, not substituted into
the original raw provenance. No formal safety confidence is inferred.

The named plan already freezes common simulation limits (loss <=75%, modeled
residence latency <=1000ms, throughput >=0.1Mbps) and measured limits (UDP and
ICMP loss each <=0.75, RTT <=1000ms, goodput >=0.1Mbps, >=3 probes, >=1 received
byte), with no superiority gate or retuning. Independent replay of these exact
limits on preserved raw histories gives both routes admission in both scenarios:
foreground throughput approximately 1.462/5.931Mbps for path0 and 5.908/1.970Mbps
for path1. These are deliberately broad empirical operability thresholds, not an
optimization claim. All comparator lanes produce identical per-action numerical
outputs and admission-semantics hashes. Stricter test-only objectives are not the
campaign thresholds and must not be represented as its gate. Keep these declared
limits unchanged after collection; fix implementation/provenance rather than
adjusting limits to manufacture a pass. No additional threshold blocker is raised.

Source snapshots for the reproduced runtime findings:

| File | SHA-256 |
|---|---|
| `experimental/controller.py` | `7b62a8c308f53a2826359bb6c7fc73e53749aeff9cb487ceb39a836ee80cadda` |
| `emulation/experimental_lab_receiver.py` | `a8ede0d234ba3d944bee5ad99158177c1429478ffa7b5afa82e3849d61dacc15` |
| `emulation/experimental_lab_runtime.py` | `c63a263938a1b20382edfd0c29aa1d3dc41ef58869171559caef89872e708e77` |
| `backend/scripts/verify_experimental_lab.py` | `ebc58bd3e455e250a2de962d490cdc3074bdec314493b08280bc874514215e66` |
| `experimental/live_adapters.py` | `9a927c270b7a6a43d0001511fb154e8125bfea4ec2710cc723be3851f5b5bf55` |

`experimental/` in this table abbreviates
`backend/app/modules/autonomy/experimental/`. The empirical/formal separation
remains accepted; the launch blockers are the specific software defects above.

---

Date: 2026-09-20. Decision: **changes required in the integration contracts before
joined-loop acceptance**. The accepted empirical lab scope is appropriate; formal
causal calibration is not an additional admission requirement for this workstream.

## Review boundary and evidence

This is the initial research/design review, using the `code-review` skill. At the
initial inspection, ADR025 existed but no ADR025 `experimental` implementation,
adapter, simulation integration or tests were present. Initial production files
appeared during the review; the follow-up below records their concrete findings.
The Git index contained no staged
diff; the working tree contained substantial existing modified/untracked work.
“Staged contracts” below means the proposed integration and its available reusable
contracts, not an assertion that new production code has passed review.

Only this review document was edited. No privileged launch, campaign, service
mutation, migration or model change was performed. Findings are source-inspected
constraints and design gaps. One unprivileged fake-transport authority-race
reproduction is recorded below; no live lab failure or acceptance pass is claimed.

Primary references:

- `docs/adr/ADR-025-experimental-lab-closed-loop.md`, especially lines 18–58.
- Preserved qualified lab: `ai-engine/artifacts/adr024-qualified-001/recovery/emulation/`.
  References to **frozen experiment** below mean that directory's `experiment.py`,
  not today's `emulation/experiment.py` (whose matched spec is version 5).
- Frozen AI: `ai-engine/artifacts/adr024-qualified-001/model/source/`.
- `docs/project/CompletionProgram/RuntimeQualification.md` and
  `QualificationEvidence.md` for scope, identity and historical acceptance.
- Current Autonomy authorization/model/receiver and Simulation evaluator contracts.

## Findings and concrete corrections (severity ordered)

### ER-01 — High: name one actual routing owner, including reset and measurement

**Evidence:** frozen experiment `handle()` lines 625–668 calls `measure(0)` on
reset and `measure(action)` on step. `measure()` changes the initial route at
749–751, changes it under already-running traffic at 782–789, calls `change()`
again for end readback at 823–825, and closes routing on terminal/error at 889–897.
Frozen `matched.py:63–128` owns break-before-make rules/routes and partial cleanup.
This is an actuating environment, not a passive measurement service. Frozen AI
`env.py:188–205` sends that actuating step through its transport.

**Correction:** the experimental core must submit one admitted action to one lab
owner; that owner's guarded routing adapter must be the routing object used by
the experiment. Do not apply with an independent native receiver and then call
the original step to “measure” it. Do not run the frozen evaluation CLI as an
independent action producer beside the controller. Use confined read-only inference
for proposal generation. Reset, initial route installation, successor changes,
implicit terminal cleanup and explicit recovery all need recorded ownership.

Bind request ID, lab/run/container/namespace identity, fence, action and baseline
before the first possible mutation. An end-readback call must remain read-only:
lost adapter state must not make `change(action)` silently reinstall a route.
The passive observer only publishes evidence. A recovery supervisor may share the
owner process family, but must serialize/fence takeover rather than race its writer.

**Later verification:** count actual mutations across reset/step/readback/close;
deny a second owner; prove one proposal causes one owned action, and a duplicate or
lost-result retry never executes again.

### ER-02 — High: action duration is independent of step completion and “keep”

**Evidence:** frozen experiment stops senders, drains queues, stops receivers and
only then finalizes metrics (`833–874`); ordinary nonterminal steps retain routing.
The 300-second idle and 45-second request watchdogs (`920` onward) are not the
operator's action-duration contract. A terminal response has already called close.
ADR025 requires restoration on expiry, STOP, revocation, failed verification and
uncertain state, including while work is blocked.

**Correction:** persist the exact baseline and action deadline before dispatch.
Define the duration start conservatively at dispatch/first possible mutation, not
at receipt of successful verification. “Keep” preserves the action only until the
existing deadline; same-route decisions cannot silently extend it. Any renewal
needs explicit fresh admission and policy accounting. Minimum dwell never delays
STOP, expiry or failed-verification restoration.

Supervision must remain responsive while inference, counters, queue drain or IPC
blocks. Cancel/fence the outstanding writer, reconcile its outcome, and restore
exact-owned baseline state. Restoration authority survives actor revocation and
STOP; it does not authorize new routing. An expired/interrupted window is retained
as invalid, not completed later and freshened. Record overdue restoration honestly;
timeouts are operational limits rather than guaranteed completion bounds.

Baseline means the captured unmodified forwarding/resources for this owned lab,
not “action 0”: a route0 override can still leave owned policy rules installed.
On foreign-state conflict or failed compensation, retain unresolved ownership and
block new work. A terminal measurement proves historical route performance, not a
currently installed route that the core may mark kept.

**Later verification:** expiry during inference, apply, drain and verification;
STOP/revocation with an active kept route; same-action nonrenewal; restart recovery;
failed restore with no successor dispatch; exact baseline readback after cleanup.

### ER-03 — High: wrapper equivalence must not falsify frozen provenance

**Evidence:** frozen AI `cli.py:1049–1052` requires both full environment-spec and
image/source provenance equality with the manifest. `--generalization` does not
waive those checks. Frozen lab `environmentSpec()` hashes a fixed 13-file list;
an added wrapper can alter execution without entering that list. Current live
schemas admit only existing qualification protocols (`live_schemas.py:44–69`),
not an implicit wrapper-equivalence protocol.

**Correction:** pin and retain separately (1) original/derived checkpoint and
unchanged tensor identity, (2) frozen routine source map, (3) actual wrapper,
adapter, inference entrypoint and runtime/image identities, and (4) the empirical
equivalence protocol/results. A wrapper copied or injected into an unchanged image
still changes effective runtime provenance. Never replace actual image/source
values in raw measurements to satisfy the frozen validator.

If the exact frozen inference entrypoint rejects authentic wrapper records, make
the experimental compatibility boundary explicit: a separately reviewed adapter
validates actual provenance and feature semantics, then invokes the unchanged
encoder/model routines in the confined AI environment. Bind raw observation hash,
adapter/equivalence hash and numerical input/output hashes. Do not describe that
path as unchanged full-validator acceptance or alter the existing formal provider
to trust it. Reuse `FrozenModelProvider` unchanged only where its real contracts
actually match. PPO probabilities remain policy preferences, not safety confidence.

Equivalence evidence must cover both directions, previous action/history, actual
capacities, traffic/control ordering, count and time denominators, drain semantics,
terminal cleanup and unchanged deterministic model outputs for identical numerical
inputs. Report permitted instrumentation timing effects and fault-path deviations;
do not demand exact equality of independently acquired empirical packet timings.

**Later verification:** authentic wrapper provenance accepted only by its scoped
experimental adapter; changed wrapper/source/image pins rejected; original loader
still rejects mismatches; paired frozen/adapter encoding and inference agree.

### ER-04 — High: authority checks belong after blocking reads, at each mutation

**Evidence:** current `autonomy/service.py:97–106` checks current profile permissions
and owning Network access. Formal `execution_authority.py` additionally requires
formal autonomous controls and calibration, so it is not an empirical lab authority
implementation. `emulation/autonomous_frr.py:151–167` and
`autonomous_namespace.py:55–77` demonstrate the important final-check ordering:
namespace/inventory reads finish before the server checkpoint immediately before
mutation. The frozen matched driver has no corresponding current-authority hook.

**Correction:** implement experimental authority using current owning Identity and
Network service contracts plus the protected policy, durable STOP, expiry and
fence. A policy's actor UUID, startup permission check, cached `authorized=True`,
or successful inference is not current authority. Recheck after lock acquisition,
inference, simulation and blocking resource reads; perform a final check before
each route/rule mutation, including later mutations of a partially applied action.
Refresh time after authority I/O. Authorization/control-store failure denies new
mutation and triggers exact-owned recovery where required.

Serialize STOP/control revision and dispatch admission with a documented ordering.
Do not hold a control lock across a whole measurement such that STOP cannot latch.
Once STOP is acknowledged, queued actions must not later dispatch on stale
admission. Recheck current authority before recording keep after verification.
Separate recovery checkpoints validate ownership/fence, not revoked requester
permissions. These are empirical operational safeguards, not a claim of atomic
cross-process authorization or a formal zero-latency revocation guarantee.

**Later verification:** revoke actual membership/permissions and latch STOP while
each blocking boundary is paused; release it and assert no subsequent add occurs.
Use actual current-authority service integration as well as deterministic fault
injection. Prove owned restoration still works after revocation/expiry.

### ER-05 — High: simulation must be action-bound and capable of rejection

**Evidence:** `simulation/evaluator.py:363–400` computes genuine deterministic
finite-buffer metrics, but its `risk_gate` uses aggregate flows. It explicitly
reports configured-model provenance and `physical_safety_authorized=False`.
Its latency is delivered-byte-weighted residence time, not measured ICMP RTT.

**Correction:** invoke the pure evaluator before the sole action owner may mutate.
Construct the candidate's actual selected path and declared background load using
the admitted observation and pinned assumptions. Bind observation, proposal,
runtime route mapping, policy, evaluator/input/output and bounded-command hashes.
No hardcoded pass, unrelated scenario or evaluation after apply qualifies.

Check the selected foreground flow's objective as well as any aggregate objective;
background throughput must not mask foreground starvation. Reject unavailable
required metrics and incomplete horizons. Specify throughput/loss units and avoid
equating modeled residence time with measured RTT. Frozen returned queue values
are sampled peaks during load, not current queues at decision time after drain;
do not treat them as an exact initial queue snapshot. Document the chosen queue
and demand assumptions and their expiry.

Complete this numerical gate even though it grants no formal safety certificate.
Empirical lab policy authorizes the scoped experiment; configured simulation
admits its numerical candidate; measured verification decides keep/restore.

**Later verification:** a real evaluator case rejects the congested candidate and
admits an objective-satisfying candidate; rejected candidate causes zero mutations.
Cover foreground starvation hidden by aggregate throughput, route/hash mismatch,
missing metric and stale observation. Do not tune thresholds after seeing outcomes.

### ER-06 — High: verification failure must cause observable recovery

**Evidence:** frozen experiment finalizes a traffic aggregate after quiet drain;
samples themselves were acquired under load, with receiver totals including drain.
Frozen spec lines 33–49 preserve those denominators. The current native driver's
`verify()` (`autonomous_frr.py:169–195`) checks path/reachability and explicitly
returns `traffic_effects_verified=False`; three successful pings are not goodput
verification. Existing manual native evidence used a static-FIB fixture, not the
qualified FRR experiment runtime.

**Correction:** collect independently read actual selected-path state plus actual
sender/receiver counts, goodput, probe loss/RTT and acquisition timestamps for the
applied command. Preserve the frozen denominator and censoring rules; unavailable
RTT stays unavailable. Tie evidence to execution/run/window identities and use
measurement time, not file-publication time, for freshness. Post-drain inference
is a sampled closed loop under stationary workload assumptions, not observation
of continuously loaded instantaneous state.

Exercise a case where dispatch genuinely occurs, verification genuinely fails,
and compensation restores the exact baseline with fresh readback. Keep distinct
outcomes for predispatch rejection, partial apply, verified apply with failed
performance, ambiguous dispatch, restored and restoration uncertain. If the
experiment auto-closes on failure, journal and verify that actual cleanup rather
than inventing a second rollback. A fixture-edited result only tests handling;
it is not evidence that a route/link fault changed measured traffic.

**Later verification:** actual route/link fault after application, count/readback
mismatch, delayed/missing result, lost receipt and failed compensation. Show raw
mutation → failed check → owned removal → baseline readback chronology. Recovery
must finish/reconcile before another proposal can acquire ownership.

### ER-07 — Medium: matched baselines require the same complete runtime protocol

**Evidence:** ADR025 requires unused operational seeds and matched fixed0/fixed1
and heuristic baselines. Prior ADR024 seeds 3003–3014 and all reserved/failed
historical seeds are already consumed/reserved. Frozen workloads are stationary
per episode; changing capacity within an episode changes that qualified scope.

**Correction:** preregister a seed × scenario × policy matrix, including both
directional congestions, before collection. Audit historical training, validation,
test, operational and failed/reserved plans. Pair policies on the same seed,
generated demands/capacities, runtime/image/wrapper, initial forwarding, reset and
quiet-drain protocol, window/horizon, action-duration rules, simulation objectives,
verification and recovery policy. Compare complete controllers, including denied
actions and restore time, rather than giving baselines a different execution path.

Reserve ordering/randomization in advance to control host/time effects; same seed
does not promise identical empirical packets. Define whether fault scenarios are
outside the stationary qualification and report them accordingly. Keep every
attempt and negative result. Separate preregistered fault strata from nominal
performance strata, with explicit missing/invalid handling. Compute paired
episode/seed summaries and uncertainty, not packet/window pseudoreplication.
Report action/no-action counts, effective routes, restoration/idle time and
decision/action/recovery latencies. Do not imply PPO superiority unless supported.

## Ownership contract to settle before production review

| Component | Exact responsibility / boundary |
|---|---|
| Autonomy experimental core | Protected policy admission; current actor/scope checks; durable STOP, claims/fences and immutable proposal/action/recovery journal; no privileged route commands. Dedicated experimental persistence if needed under ADR025; no formal mode mutation. |
| Confined model runtime | Read-only evidence/feature validation through the declared compatibility boundary, unchanged encoder/tensors and deterministic action/probabilities; no lab authority, Docker transport, seed/scenario selection or route execution. |
| Simulation owner | Pure configured evaluator and numeric results; experimental integration binds those results to the exact proposal and checks its declared foreground objectives. |
| Lab adapter and owner process family | Exclusive lab identity/namespace ownership; guarded frozen experiment routing; actual traffic acquisition; durable before-image/partial-apply state; serialization with recovery. No competing receiver. |
| Passive evidence path | Read-only publication/pinning of original measurements; no hidden reset/step calls or authority to mutate routes. |
| Recovery supervisor | Detect expired/disconnected/uncertain owner, fence and reconcile before exact-owned restoration; retain unresolved status if restoration cannot be verified. |
| Acceptance verifier | Independent reconstruction of action, numerical admission, raw readback/counts and recovery against the preregistered seed matrix; no qualification flags inferred from an owner's success boolean. |

Minimum persisted binding before I/O: experiment/policy revision and hash,
actor/workspace/network, lab/run and actual runtime provenance, owner fence,
immutable request ID, original observation hash/times, model/input/proposal hashes,
simulation inputs/output/objectives, exact bounded route command, captured baseline
identity, duration/expiry and recovery ownership. Record acquired observation
references through Telemetry's owning evidence-pin contract where rows are used.
These are design requirements, not newly declared public APIs or event schemas.

## Formal/empirical separation decision

Approve the **separation** chosen by the user and ADR025. Existing formal
`autonomous`, SafetyShield, calibrated certificates and production readiness
requirements continue to describe their own mode. Do not demand unavailable
physical RF surveys, native service curves or mathematical causal/deadline proofs
to authorize this separately bounded empirical lab policy. Conversely, successful
empirical trials do not set those formal readiness flags or certify production.
The unresolved findings above concern correctness, current authority, faithful
measurement and recovery within the accepted empirical scope.

## Subsequent production/tests review status

Initial production inspection is recorded below; joined composition and acceptance
remain pending. Review subsequent files against ER-01–ER-07 with exact source
revisions and test evidence. Prior ADR024
recommendations and manual native-driver results do not close these joined-loop
checks. Final acceptance needs the actual inference → numerical admission →
current authorization → single-owner apply → independent measured verification →
keep/restore chain, plus meaningful failure recovery and the matched seed matrix.

## First production-contract follow-up (files appeared during review)

These findings apply to the inspected bytes, not a claim about subsequent concurrent
edits. New core schemas/ports/authority/persistence, migration0028, the numerical
adapter, lab contract/runtime and acceptance planner were available. Receiver,
joined composition and experimental tests were not present at this inspection.

### PR-01 — High, reproduced: journal I/O follows the final authority check

`emulation/experimental_lab_runtime.py:60–78` calls `authority()`, then `persist()`,
then `original_command()`. The journal can block while STOP/revocation/expiry
occurs. An unprivileged `python -B` probe imported the real `GuardedRuntime`, used
a fake network, and revoked its fake authority from `persist()`. Observed order:
`authority → persist/revoke → mutation → persist`. The mutation was still invoked.
No subprocess/device operation was used in this probe.

Move durable intent publication ahead of the final check. Finish all blocking
preparation and perform the final current-authority/STOP/expiry/fence checkpoint
at the last mutation boundary. Preserve separate recovery authority. Add a
regression that pauses the actual persistence boundary and revokes before release.

### PR-02 — High: restore creates new forwarding and may run another measurement

`experimental_lab_runtime.py:101–102` records `baseline = routing.action` after
reset has already installed route0. `restore():113–118` closes that routing, then
calls `change(baseline)` and potentially `frame(baseline)`. This reinstalls owned
rules instead of leaving original FRR forwarding restored, and can consume another
actuating experiment step. While `restoring=True`, the wrapper bypasses normal
authority for additions (`60–72`). Thus STOP recovery can include new rule adds
and workload activity, contrary to the intended exact-original-baseline cleanup.

Capture the actual pre-reset/pre-action resource baseline and make final restoration
remove/verify exact-owned state without another actuating frame. If an intermediate
recovery target intentionally includes an earlier owned override, bind that exact
before-image and its still-valid lifetime; distinguish it from final run cleanup.
Do not authorize arbitrary baseline-index additions merely with a `restoring` flag.

### PR-03 — High: UDP loss and probe loss contracts contradict each other

`experimental/authority.py:73–77` requires `record.loss_fraction` to equal
`1 - probe_received / probe_sent`. The frozen observation's `loss_fraction` is
UDP receiver/sender loss (`recovery/emulation/experiment.py`, `measurementOutcome`),
whereas probe counts measure ICMP. The wrapper's `thresholds():130–133` correctly
checks these separately. Genuine measurements need not give equal losses.

Give UDP delivery loss and ICMP probe loss separate named fields/checks. Retain
both raw denominators and provenance. Require each configured threshold independently;
do not reject valid evidence because different protocols differ or replace UDP
loss with ICMP loss to satisfy the core. Test unequal valid values and independent
failures of each threshold.

### PR-04 — High integration gap: the three published interfaces do not yet join

- Core `ports.py` expects `Observer.observe()` to return `MeasuredFrame` and
  `Transport.prepare/execute/verify/recover` to bind `PreparedAction` and hashes.
  Runtime `frame()` returns a raw request/response, readback and `completed_at`;
  its initial observe performs reset/routing. Declare who authorizes/journals that
  initial mutation before any core `prepare()` exists.
- Core and wire policy both use `nanfo.experimental-lab/v1`, but are incompatible
  strict objects. Core has actor/scope, registry, route IDs, assumptions/objectives
  and counts; `load_policy()` admits a different exact field set, numeric actions
  and no actor/scope. Define a separately named receiver projection and persist
  its hash linked to the full core policy; do not ambiguously reuse one digest.
- Simulator protocol returns `SimulationRecord` from `(MeasuredFrame,
  InferenceRecord, ExperimentalPolicy)`. Current `evaluate_actions()` consumes
  `FrozenMeasuredFrame`, `SimulationAssumptions` and two `ActionProposal`s and
  returns admission dictionaries. Publish the conversion/composition that binds
  actual route nodes to action indices/foreground link paths, evaluator source
  hash, objective policy and selected admission. Core's check of `admitted=True`
  alone is not the numerical adapter replay.
- `RuntimeResult` still names only existing qualification protocols. Wrapper
  provenance/equivalence and the inference admission path remain to be resolved
  as ER-03 describes; original source hashes alone do not cover monkeypatching.

These are incomplete-integration findings, not evidence that the final composition
has chosen an unsafe implementation. Resolve the mappings before campaign launch.

### Positive findings and remaining acceptance checks

The new simulation adapter already evaluates both routes with real sender rates,
checks raw HTB rate/ceil consistency, checks foreground objectives **and** aggregate
objectives (`simulation.py:224–231`), and reconstructs admission before dispatch.
This addresses the numerical substance of ER-05; binding it into the actual core
remains pending. Operator-configured queue/delay assumptions are explicitly typed.

The new core uses the owning current authorization helper rather than formal
calibration authority. Dedicated tables and immutable receipts preserve separation.
The planner pairs all four policies on the same fresh seed/scenario, randomizes
order and explicitly avoids a superiority claim. Its launch currently raises
`experimental_core_adapter_contract_not_available`; preparation is not acceptance.

Align the remaining count/duration contracts before collection: core permits
durations up to 86400s, receiver requests cap at120s, planner requests four actions,
but runtime permits only nonterminal indices1–3 and restoration can consume a
step. Publish the actual finite action/window/recovery budget and validate it at
admission. Duration0 is currently accepted for execute by the wire parser; either
reject it or define explicit zero-mutation behavior. The initial planner does not
yet pin wrapper/core/evaluator bytes and simulation assumptions/objectives; freeze
those into the campaign plan before traffic, alongside actual current actor scope.

### Source pins and verification record

SHA-256 of inspected first-production snapshots:

| File | SHA-256 |
|---|---|
| `emulation/experimental_lab_runtime.py` | `ac6469889e977cc826f9636fe40e2cd2bf3d17e374180cbfc480dcbfe3b527cc` |
| `emulation/experimental_lab_contract.py` | `027d86ba6b4149ee48f124665855ebdd7f3d7ead9f1dc52852f57624922cb67d` |
| `backend/app/modules/autonomy/experimental/authority.py` | `1cc91e55acb6bb81197447418d724dcfeda65e4310ee42478604d796de3f1f18` |
| `backend/app/modules/autonomy/experimental/simulation.py` | `cdc643eba22bcac8e5d47f78166ab57746293f7cb9d8e89b665d2d687953f3e4` |
| `backend/app/modules/autonomy/experimental/ports.py` | `ebae433e42e22b6007d49de24e2c2ff37a713dbbcbecd35de27dc25a0beb0dd8` |
| `backend/scripts/verify_experimental_lab.py` | `76eb8f0d3e1935f2ce5adc9191e8c577bb4055d443c0f02bee43b3d70281421d` |

Verification performed: static source tracing; one fake-transport reproduction
of PR-01; document whitespace check. No experimental suite, current-service
integration, actual inference-equivalence test or privileged campaign was run.
