# ADR025 joined experimental acceptance campaign

## Current —017 failed;018 repair independently accepted, fresh plan blocked (2026-09-21)

Authority: [experimental owner handoff](../ReviewClosure-Experimental.md) and
[master matrix](../ReviewClosure-Completion.md). Earlier preparation/no-launch
sections below are historical records, not the current campaign status.

- **Actual authorized017:** unchanged frozen016 source and original model/runtime
  identities; **4/4 smokes completed,67/68 matrix outcomes completed,1 invalid
  measurement**. All **20 fault outcomes completed** (18 restored,2 predispatch
  rejected). Nominal outcomes:34 kept/restored,13 complete performance rejections/
  restored,1 invalid. The full auditor and result remain **FAILED**; completion is
  not evidence that every candidate improved performance.
- Invalid case **`path1-1564-qualified`**, verify step3:
  `protected_regular_owner_file_required`, truncated/incomplete measurement. Earlier
  steps passed; core/native restored and core released. Missing aggregate metrics
  remain null. This is not action expiry or measured bad performance.
- An atomic-publication race was reproduced against frozen016: replacement between
  open and fstat leaves the safe old inode with zero links. The exact live
  interleaving is unproven because the frame lacks pathname/fstat metadata.
  Active emulation now uses protected bounded reopen (at most3 attempts), discarding
  old bytes and revalidating owner/mode/no-follow/link/path bindings and current
  authority/STOP. Frozen016 and campaign017 bytes remain unchanged; no same-plan retry.
- **Frozen018 gates:**115 backend passed/3 historical014-only skips,34 receiver/runtime
  passed,2 STOP probes passed; Ruff clean. These are offline checks, not fresh measured
  acceptance. [Independent018 review](../ReviewClosureEvidence/experimental017-018/018-independent-review.json),
  SHA256 `61ae01ccca57b5607566791ebd8dc811c25b84af57b0dbdcc7530c493087cd80`,
  accepted the bounded protected-read repair and independently reconfirmed017 failure.
- Reviewer found `reserved_seed_count:1342` was a diagnostic cardinality falsely
  treated as a reservation. Active typed/provenance extractor correction passed
  **60 campaign tests**; genuine/preregistered and missing-plan reservations remain.
- **Fresh018 plan BLOCKED:** corrected **996 of1000** permitted train-operational
  values in1000–1999 reserved;**4 available,36 required,deficit32**. No fresh output:
  no plan hash, new reservations, admission or launch. Preserve failed reservations
  and the train/validation/test split. Any domain decision requires explicit reviewed
  direction; do not silently reuse values, widen the domain or declare completion.
- Latest core0029 refresh **c8rorfzd accepted28pass/0fail/5blocked**, backend
  `a2bf67af…`, accepted source `f7105617…`. Subsequent source changes are only the
  experimental verifier scanner/test (`9e46d086…` verifier), not core behavior;
  current tree is not entirely byte-identical to the accepted image. Core acceptance
  does not qualify experimental actuation or authorize a new protocol/domain.
  [Durable credential-free evidence](../ReviewClosureEvidence/README.md) preserves
  the new refresh/retention records and earlier deployment/browser receipts.

Physical RF, intended-user study, independent repeated training, proactive/stability
evaluation and full recovery remain [research evidence obligations](../ReviewClosure-Research.md).

## Historical continuation: diagnosis, outcome-v2 and executable source isolation (NO LAUNCH)

Parent instructed investigation/preparation only pending wrapper/core and retention0029
fixes. Campaign009 and all previous plans, thresholds, frames and reported results
remain unchanged. No new lab/services were launched in this continuation.

### Exact009 failure diagnosis and evidence limits

Root: `/tmp/opencode/nanfo-experimental-campaign-009/`. Raw inspection script:
`/tmp/opencode/diagnose_009_raw.py` (read-only). Inspect each named case's
`controller-result.json`, `journal.json`, `native-journal.json` and `wire-*.json`.

**Critical retention defect:** receiver runtime wrote `frame-<canonical sha>.json`
for every original response, including incomplete/rejected windows, but the old
verifier copied journal hashes and successful wire frames only before destroying
the receiver volume. The failed frame's bytes are **not present** in retained009
evidence. This prevents precise failed-window count/drain reconstruction. No
historical file is repaired, invented or relabeled. New verifier exports every
hash-listed raw frame, validates canonical hash and exact bytes, and fails audit
if even one frame is missing.023/024 historical artifacts remain untouched.

| Case | Established facts | Exact missing frame hash / unresolved cause |
|---|---|---|
| `path0-1391-fixed0` | Fixed0 selects congested2Mbps route0; real simulator admits under common broad limits. Bootstrap: sender1603 packets/1923600bytes/2.628423522s, received502/602400bytes, goodput1.833494473Mbps, UDP loss68.683718%, ICMP4/13 received (69.230769% loss), RTT396.489ms, verified-empty drain. Execute receipt UUID`d8fcb42e-7e64-40e7-91af-2d9e97bedb3c` rejected `measured_verification_failed`, then exact restore. Dispatch20:36:58.140149Z, interruption20:37:05.959589Z, deadline20:37:27.428971Z: **not action expiry**. | Step1`9d7a91cb6869ab1b77d4dc37d2631e8cd709222d29a26679f78f4cce3867f467` missing. Likely legitimate low-capacity performance rejection, but which threshold/count failed is unprovable from009. Bootstrap loss was below75%; do not substitute bootstrap metrics for step1. |
| `path1-1392-heuristic` | Lexicographic least-utilization heuristic chooses route1 despite2Mbps capacity: baseline utilization route0≈0.309313 versus route1≈0.000377. Execute step1 is valid: foreground sent6093/7311600bytes over9.907417324s, received3057/3668400bytes,2.962144325Mbps, UDP loss49.827671%, ICMP17/49 (65.306122% loss),149.467ms RTT; drain verified-empty. Hold receipt UUID`0bd63837-7e2c-4b3d-b0c5-700ab433c0ad` rejected `hold_measurement_failed`. Interruption20:38:30.295796Z, deadline20:38:36.013653Z: **not action expiry**. Exact restore/release recorded. | Step2`d5803633a4edb19f547f7bbf2569aae4418a45d33d3278b83de3a13ec5040a1b` missing. Poor performance on selected low-capacity path is plausible; no claim of the exact failed threshold. |
| `path0-1391-heuristic` | Correctly selected route1. Execute step1 valid:5892 packets/7070400bytes sent over9.660776346s,4944/5932800 received,4.91289709Mbps, UDP loss16.089613%, ICMP41/48 (14.583333% loss),61.204ms RTT, verified-empty drain. Verify rejected `original_measurement_failed`. First retained controller STOP request20:32:46.396520Z; interruption20:32:47.630909Z; action deadline20:32:57.357061Z. Thus **not action expiry**. A second STOP followed; recovery was exact. | Step2`ca1c7d4731c1b7a52d1e11ca380f510a23ca22488c43f43c0736a1d9ff756c4b` missing. Cannot distinguish incomplete drain, original measurement exception, or a liveness/STOP race. Controller reports heartbeat `experimental_receiver_response_binding_invalid` (generic ingress rejection); do not classify this as poor performance. |

### Parent prompt for owner agents

> Adapter/wrapper owner: use the three cases above. Preserve every failure frame and
> clock attachment in rejected receipts (or durable frame inventory), exact operation
> request hash/ID, the threshold checks/raw denominators, and structured STOP cause
> with monotonic latch time. Distinguish complete bad performance from invalid
> measurement and auth/fence/heartbeat interruption. Current generic heartbeat
> ingress rejection masks the reason; retain a credential-free reason receipt.
> Investigate `original_measurement_failed` and concurrent keepalive/guarded-heartbeat
> STOP ordering without changing original frozen routines or thresholds.
>
> Core owner: one admitted action has one30s lifetime; no renewal via verify. A
> complete measured failure must cause exact recovery and retain the failed numerical
> record before throwing. Expiry during an in-flight verify must restore without
> discarding the reason/frame. No nominal protocol pass for incomplete measurements,
> unexplained control exceptions, unverified recovery or a mere rejected flag.
>
> Retention owner: finalize0029 and current metadata; the next plan requires0029 and
> all evidence ownership/pins needed before history deletion. Campaign launch waits
> for those fixes and a new parent admission. Do not edit009 or other agents' files.

### New-plan outcome semantics (not retroactive to009)

`nanfo.experimental-outcomes/v2` retains identical simulation and measured gates
for model/fixed0/fixed1/heuristic, with separate fields for protocol completion and
candidate performance:

- `kept_then_restored`: actual complete passing measurement/readback, durable keep,
  finite termination and exact restore. Candidate pass=true.
- `simulation_rejected`: independently replayed negative numerical admission, no
  action dispatch, bootstrap cleanup verified. Candidate pass=false, post-action
  metrics=null; this is not rollback.
- `performance_rejected_then_restored`: admitted candidate, complete original
  measured counts showing an actual threshold failure, correct selected-route
  readback, rejection enforcement and exact native/core restoration. Candidate
  pass=false; failed-window metrics retained. This is a valid protocol outcome,
  not a successful candidate.
- Invalid measurement, missing frame, unexplained control failure, uncertain
  recovery or unexecuted case remains protocol failure. All selectors obey this.

Paired seed denominators always include every preregistered policy. Null metrics
stay null; aggregate mean is unavailable when any paired result is unavailable.
Per-pair candidate outcomes and descriptive SD are retained, without dropping bad
windows or making superiority claims. Both model directions still require actual
kept results. Next smoke stage is **2model +2heuristic** on four fresh separate
seeds: models must keep, heuristics must produce audited complete protocol outcomes.

### Executable source snapshot

New `freeze --output ROOT` copies the complete backend/emulation/scripts/deploy
source/config/test family and the entire preserved qualified model evidence into a
new independent tree. It excludes env credentials, keys, caches, generated outputs
and symlink directories. Manifest records every byte hash, original root, model
origin→snapshot mapping, and the existing qualified AI interpreter's absolute path
and hash. That interpreter retains its independent environment; model/source data
are read from snapshot copies, never rewritten historical files.

Run **from snapshot/backend using its verifier**, with snapshot-only PYTHONPATH for
controller/migration/gate children. `ROOT` is derived from that verifier's actual
file. Source checks hash the snapshot, not current workspace. Only the explicitly
read-only seed inventory can inspect original artifact roots. Launch refuses a
workspace invocation lacking the frozen-runtime manifest. Exact model bytes are
rechecked at the rebased snapshot path. New0029 readiness remains mandatory.

First `/tmp` snapshot attempt hit the user tmpfs quota and published no manifest.
It is not runnable/accepted. Snapshot staging moved to the allowed Git-ignored
`ai-engine/artifacts/adr025-runtime-*` root; original evidence is untouched. The first
complete preparation snapshot passed106 backend/20receiver/2independent STOP tests,
but lint inherited the ancestor AI directory's Ruff rules. Gates now use explicit
isolated Ruff defaults matching the backend's actual defaults. A new snapshot,
not edits to the existing snapshot, is required for that correction.

### Verified frozen preparation011 (no new plan/seeds/admission)

**Superseded for next preparation by013 below;011 remains unchanged.**

- Frozen executable root:
  `ai-engine/artifacts/adr025-runtime-preparation-011/`
- Manifest SHA256:
  `5a6e5d8593cc0fb18a6703124b1debad774dcb3f5c36f0330f21a3af02e87021`
-1794 exact-byte source/config/test/model files; complete source family and model
  reference closure resolve inside this root. AI interpreter remains the exact
  separately installed `ai-engine/.venv/bin/python`, not a workspace code import.
- Executed gates **from snapshot/backend**:106 backend tests,20 receiver tests,
 2 independent STOP probes, isolated backend-default Ruff all passed. Receipt:
  `ai-engine/artifacts/adr025-runtime-preparation-011-gates/offline-gates.json`.
- Snapshot verification and readiness run from that same root succeeded for all
  existing contracts but explicitly reports `retention_schema_0029:false`.
- Live execution is disabled pending final0029 current metadata/owner fixes and
  new parent admission. Working-tree migration0029 appeared after snapshot011;
  `CURRENT_SCHEMA` still0028 at this check. Do not update011 in place. Freeze a
  fresh full source tree after the final owning-agent changes settle.

Commands after parent declares fixes complete (preparation only first):

```sh
# From workspace/backend: create a NEW immutable source family, no acquisition.
poetry run python -B -m scripts.verify_experimental_lab freeze \
  --output /home/DHB/Documents/NANFO/ai-engine/artifacts/adr025-runtime-final-012

# Then set the working directory to that snapshot's backend/. Invoke the existing
# backend interpreter directly, not Poetry/project discovery in the workspace.
/home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python \
  -B -m scripts.verify_experimental_lab gates \
  --output /home/DHB/Documents/NANFO/ai-engine/artifacts/adr025-runtime-final-012-gates
```

Only then preregister a new plan from that frozen root with its gate receipt,
4 fresh smoke seeds (2model+2heuristic) and all68 matrix cases. Original seed history
is read-only inventory; it is never added to executable module lookup. Parent must
issue a new exact-plan live admission. No such admission/plan was created here.

### Final ready preparation013, including0029 (NO LAUNCH)

0029 and current metadata settled during this continuation. A subsequent012 copy
detected concurrent edits to `backend/scripts/audit_isolated_suite.py` and its test
and was rejected;012 is not an accepted freeze. No source in prior snapshots was
updated. Freeze publication now writes the valid manifest only after the original
source family is rehashed unchanged; an interrupted/drifted future copy has no
valid manifest.

Accepted executable root:
`/home/DHB/Documents/NANFO/ai-engine/artifacts/adr025-runtime-preparation-013`

Manifest SHA256:
`c2edcba14d8fec1efa5b2f8bf957b5f8922b10f86d8364bc34db82ed0069a030`

1794 copied files verified. Gates executed in this root's backend directory pass:
106 backend tests,20 receiver/runtime tests,2 independent STOP probes and Ruff.
Receipt: sibling `adr025-runtime-preparation-013-gates/offline-gates.json`.
All7readiness flags are true, including retention_schema_0029. This demonstrates
offline harness readiness, not new empirical performance or final reviewer approval.

Parent can review the frozen sources and the diagnosis above, then preregister a
new campaign from **013/backend**, using its gate receipt and preserved model copy.
The resulting plan requires4separate smoke seeds (2model,2heuristic),48nominal and
20fault cases; all prior campaign seeds remain reserved. Do not invoke a verifier
from the mutable workspace or update013 after acquisition. No new measurement plan,
seed reservation, live admission, lab, service or network traffic was created in
this continuation. Parent's new exact-plan authorization remains required.

## Sustained authorized campaigns004–009: actual joined smokes pass, full matrix fails

All these launches used the common exclusive lock and an attached foreground tool
process with **4800000ms outer timeout**, **3600s global deadline**,180s cleanup
reserve. No owned script was edited while its campaign process was active. Every
source correction used new gates, a new immutable plan and new unused reserved seeds.
No threshold,30s observation age,30s action duration, matrix size or qualification
requirement was relaxed. Sources and raw evidence of all prior attempts are retained.

| Campaign | Actual outcome |
|---|---|
|004 | Both smoke receivers reached real FRR startup but zebra could not traverse `/run/nanfo` under inherited077 umask. Captured full credential-safe diagnostic; exact resources cleaned. |
|005 | Preregistered Network service/repository bytes changed before acquisition; refused. No lab measurement. |
|006 | Real fresh inference/simulation/authorized dispatch reached; path1 verified/held/restored; path0 denied as original observation aged beyond30s during Docker challenge overhead. |
|007 | Reduced redundant heartbeat rate; path0 still stale during dispatch, path1 receiver heartbeat rejection. All failures/restoration retained. |
|008 | Bounded attached per-operation challenge bridge removed repeated Docker startup overhead while preserving **every per-add real core authority check**. Both positive smokes passed; three matrix cases completed/restored. `core/schema_version.py`/`runtime_health.py` changed midcampaign; remaining acquisition refused. |
|009 | Both positive smokes passed again. Matrix actually acquired five nominal cases: qualified and fixed1 completed/restored; three nominal cases failed actual original/measured verification. Five Identity/Network sources then changed during campaign; remaining acquisition refused. Full audit correctly reports failed. |

### Campaign009 measured smoke reconstruction (not part of68)

| Direction | Actual model route | Goodput Mbps | Probe RTT ms | UDP/probe loss |
|---|---|---:|---:|---:|
| path0 | route1 |6.1327990602|24.143|0 /0|
| path1 | route0 |5.8187887854|24.177|0 /0|

These are actual freshly acquired qualified inference → configured simulation →
real private-store authority → routing → raw readback/traffic → verified hold →
exact restoration results. A separate read-only process reconstructed both using
the auditor. It is **not independent reviewer signoff or a complete paired result**.

Actual matrix blockers, without changing acceptance:
- `path0-1391-fixed0`: native receipt `measured_verification_failed`.
- `path0-1391-heuristic`: `original_measurement_failed`; controller heartbeat also
  surfaced `experimental_receiver_response_binding_invalid` during receiver stop.
- `path1-1392-heuristic`: `hold_measurement_failed`.
- Concurrent source drift: `identity/service.py`, `network/service.py`,
  `network/schemas.py`, `network/deletion.py`, newly added `network/asset_mapping.py`.
  Remaining cases were refused before acquisition. They are not passed or rollback.

Campaign009 plan SHA256
`267efd7b3287a3b2322ef4a560e6bb398a1ff9b86eacaa8d054540069729cd61`.
Evidence root `/tmp/opencode/nanfo-experimental-campaign-009/`:
`smoke-result.json`, `postrun-reconstruction.json`, `campaign-evidence.json`,
each case's complete exception chain/native journal/receipts, and `cleanup.json`.
Campaign008's successful smoke evidence remains independently retained in its root.
Final cleanup verified no owned lab/Redis containers/volumes or live private PG
remain; shared service IDs unchanged. No detached campaign process remains.

**Full68 measured acceptance remains FAILED, not completed.** Parent must resolve
actual nominal failures and stop source drift before another whole-matrix attempt.
Do not retune the preregistered limits or reuse any retained plan's reserved seeds.

## Authorized live attempts002/003 — first actual blockers (2026-09-20)

Parent authorized separate protected live admissions after final STOP/duplicate
authority corrections. Core now ends authority checks with a bounded serialized
control/current-DB-authority decision; receiver rereads STOP after bootstrap
admission I/O; mutation grants moved to sole-writer `dispatch_authority`, with
watchdog liveness checks issuing no duplicate grant. Current tests and the two
independent STOP probes pass. Review correction receipts bind exact plan/gate hashes.
Campaign001 and all its reserved seeds remain untouched and were never launched.

Campaign002 preregistered two additional positive smoke seeds1076/1077, then the
unchanged48nominal+20fault matrix on separate seeds. Plan hash
`a54a1c0f643f79e71f1f1a72dd83696ff1a6e5bdad059e75b9582807e9f71f8d`.
Private PostgreSQL/Redis migration/login and frozen qualification succeeded. Both
smokes failed **before receiver startup**: Docker archive `cp` cannot resolve a
directory created in the container's `/run` tmpfs. Full68 was retained `not_run`.
All owned services/containers/volumes were cleaned; shared services untouched.

After reporting that verifier setup bug, added exact-byte stdin transfer with
SHA256 validation for wrapper files, reran gates and prepared fresh campaign003:
plan hash `88a2bcfe461fb64c98dcbda61b17d6dc0a393548b28a5c18cd90e66014c4e72b`.
Its first smoke reached the receiver and failed protected ownership validation:
archive-copied receiver policy/token files were not owned by the receiver EUID.
No fresh frame, inference or route action occurred. The300s outer tool timeout
interrupted the second smoke; exact remaining container IDs/labels were inspected,
diagnostic retained, and ONLY its remaining lab/Redis containers and volumes removed.
Private PostgreSQL had exited; its exact temporary tree was verified and removed.

Current correction applies root-created0600/no-follow/exclusive/hash-verified stdin
publication to **all** receiver inputs, including policy/token/admission/barrier files.
An unprivileged, disconnected, no-lab container probe confirmed uid=euid=0,
mode0600,nlink1 and successful tmpfs write. Campaign46 offline tests and scoped
Ruff pass after this correction. No new campaign has been prepared/launched with
these last changed source bytes.002/003 frozen source and raw attempts are unchanged.

Evidence:
- `/tmp/opencode/nanfo-experimental-campaign-002/result.json` (failed smoke gate)
- `/tmp/opencode/nanfo-experimental-campaign-002/cleanup.json` (complete)
- `/tmp/opencode/nanfo-experimental-campaign-003/interrupted-result.json` (failed;
  all68 not run;0 fresh measurements/model inferences)
- `/tmp/opencode/nanfo-experimental-campaign-003/interrupted-cleanup.json`
- `/tmp/opencode/nanfo-experimental-campaign-003/private-copy-correction-probe.json`

Next launch must use fresh gates, a fresh plan and fresh reserved seeds. Use a
whole-campaign outer timeout exceeding the7200s protocol budget plus setup/cleanup;
the tool's300s timeout terminates the process and is not a polling mechanism.
This is an actual setup-blocked result, not joined-loop acceptance or performance.

## Execution boundary

The campaign runner schedules **48 matched nominal trials and20 fault trials**,
retains each outcome and invokes the offline auditor before reporting success.
Preparation and tests are authorized. **No privileged campaign has been launched.**
Parent must separately admit the final exact plan after core/adapter readiness.

Owned implementation:
`backend/scripts/verify_experimental_lab.py`,
`backend/scripts/audit_experimental_lab.py`, and
`backend/tests/unit/test_experimental_campaign.py`.
Core/receiver/simulation contracts are the parallel owners' published modules,
not mocks or copies of the original experiment's routing implementation.

## Protocol fixed before acquisition

- Six fresh operational seeds per direction; each seed/scenario uses qualified,
  fixed0, fixed1 and heuristic controllers. Twenty further seeds are dedicated to
  faults. Operational seeds are unused values in frozen train range1000–1999;
  no training or held-out retuning is performed.
- Seed/scenario/policy order is preregistered with randomization seed25092026.
  Shared reset, runtime, offered demand, shaping, two-second measurement semantics,
  simulation assumptions, authorization, execution, verification and recovery.
- Baselines use actual core `ComparatorAdapter`/`ComparatorResult`, checkpoint and
  qualification null; no fabricated model probabilities. The declared heuristic is
  `least-utilization-then-queue/v1`, the owner's deterministic lexicographic rule.
- One action per disposable graph. Four-step maximum; reset0, execute1, verify2/3,
  never terminal step4 as proof of held routing. Actual action bound30s, age<=30s,
  minimum dwell2s, I/O60s, lease65s, per-case controller budget180s plus90s setup.
- Default whole-campaign budget7200s including180s cleanup reserve. Parent may
  preregister2400–14400s via `--budget-seconds`;3600s is supported but may exhaust
  before all cases. Every unexecuted suffix is recorded `not_run`, non-success.
  No automatic campaign retry or replay of an uncertain execute.
- Configured simulation: both directed router paths; exact HTB egress/interfaces;
 120000-byte buffers and zero initial queues are **operator assumptions**, not
  converted sampled peak packet backlogs.5ms/link,10ms ticks,200ticks. Model limits:
 75% loss,1000ms modeled residence latency,0.1Mbps minimum throughput, checked for
  both aggregate and selected foreground flow. These broad operational experiment
  limits are fixed before fresh acquisition, not optimized on measured results.
- Measured keep limits: goodput>=0.1Mbps, UDP loss<=75%, independently counted ICMP
  loss<=75%, ICMP RTT<=1000ms,>=3 sent probes and positive traffic bytes. Missing
  metrics never become zeros/passes. Model residence latency is not ICMP RTT.
- Report all paired seed deltas, missing denominator, descriptive sample SD, route/
  no-route decisions and decision/simulation/action/recovery durations. No empirical
  superiority, formal calibration, production qualification or RF claim is implied.

## Actual joined paths

Private PostgreSQL/Redis provisioning reuses `verify_measured_twin.LocalLab` and its
owned teardown. Redis falls back to the exact local image
`sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2`
when the redis-server binary is absent.0028 is applied only in that fresh database.
Identity account/roles/membership/network are provisioned privately; actual
`AuthService.login` and access validation run, then `CurrentAuthority` calls current
owning Identity/Network contracts. No live authentication/provider mocks.

Each trial has one exact-ID, owner-labelled, network-disconnected receiver container,
using recovered image954462… and separately copied wrapper source. Original
`/opt/nanfo` sources and model weights are untouched. The receiver owns all routing,
including explicit bootstrap; there is no parallel frozen evaluation action producer.

Core controller runs in a real separate subprocess with private services. It uses
the owner observer/model/comparator/simulator/transport ports. Instrumentation saves
complete returned records without changing measured request/response contents.
Original episode UUID and snapshot UUID bindings are preserved. Privileged IPC uses
the owner's bounded exact-container operator transport. Credentials never enter
model inference or retained request frames.

The separately source-pinned campaign receiver subclass lives in the owned runner
script. Status exposes the owner's actual read-only baseline before reset. The core
commits `BootstrapCommand` first, supervises original reset, then stores authoritative
`BootstrapReceipt` and enters `run(admitted_bootstrap=True)` on the same controller.
Campaign transport maps exact receiver baseline cleanup to `BootstrapRecoveryReceipt`;
it does not release on an unverified cleanup. The model uses actual `LiveModelAdapter`
with its own source pin and explicit offline equivalence evidence scope.

Each native add, after WAL, requests an exact challenge-bound current core checkpoint
before dispatch. Campaign authority records retain that join; no cached authorization
boolean substitutes for the real owning-service check. Bootstrap checks use the same
controller ownership and current authority. The original routines remain unedited.

Path1 fault trials preregister original step1 to route1 under bootstrap authority,
so the correct model route0 proposal has a real mutation boundary. The authentic
warm-up frame/episode is used for inference, action is step2, verification step3.
Nominals all retain matched reset0. Both reset and warm-up evidence remain recorded.

## Faults (both directions)

| Case | Mechanism | Preregistered boundary / acceptance |
|---|---|---|
| delayed-data | Real elapsed publication delay | Beforewrite0: hold acquired frame beyond age limit, preserve timestamps, require zero execute |
| STOP-before/after | Real durable core STOP plus receiver STOP | Before first mutation / after first completed mutation; no later new routing |
| revoke-before/after | Real committed private-PG member downgrade | Same exact boundaries; current owning-service check must deny; recovery remains authorized |
| link-failure | Real `ip link set down/up` in exact-owned namespace | Afterwrite1; recorded PID/start/netns, argv/results and readback; actual verification failure and recovery |
| disconnect | Real SIGSTOP, heartbeat loss, then process reap | Afterwrite1; watchdog recovery, new process reconciles old journal |
| restart | Real SIGKILL and distinct recovery subprocess | Afterwrite1; wait actual lease expiry; recover only, no repeated execute |
| partial-apply | Explicit injected owner failpoint `raise` | After successful write1; retained native prefix and exact compensation |
| ambiguous-receipt | Explicit injected response loss | Pause after write1; retain actual eventual native receipt and drop only transport response; recovery without replay |

The receiver's protected one-shot `failpoint.json`/`boundary.json`/`release.json`
handshake determines write position; host sleeps never stand in for a mutation
boundary. Real intervention and injected-failpoint labels are distinct. A missed
boundary, no-op route without the required write, absent verification failure or
uncertain restoration fails that case. Predispatch rejection is not rollback.
Receiver-process death is distinct from controller death; no fresh graph is rebound
to an old journal to fabricate recovery.

## Evidence and audit

`plan.json` pins full model-reference closure, seed inventory, matrix, limits and
source bytes. `source/` stores exact campaign/core/adapter/wrapper/evaluator/identity/
network/migration/provider sources and dependency lock. Source pins are checked
again before every trial; concurrent changes cause recorded failure, not an implicit
updated campaign. Prepared plan/source files are never overwritten.

Per case retain raw bootstrap/frame history, actual qualified output or honest
baseline result, configured simulation input/output, prepared before-image, native
receipt/transcript/readback, immutable core journal export, traffic sender/receiver/
probe counts and clocks, actual auth scope evidence, process identities/results,
intervention and boundary events, all failures and cleanup. Wire records omit only
the credential token. Failed child return codes and unavailable records are retained.

The complete `campaign-evidence.json` references exact bytes for all68 cases in
order. Auditor validates frame→decision→simulation→prepared→receipt→verification→
recovery joins, numerical replay, actual native journal/command prefix, no execute
replay, original forwarding/tables restoration, matched admission semantics, real
count-derived metrics and both qualified directions. A partial/blocked matrix can
never report passed. Owner-run audit is not independent review signoff.

## Historical seed inventory resolution

Read-only inventory completed over **7096 relevant artifacts** at the initial
continuation check, including plans/failed reservations, JSONL sessions and embedded
checkpoint JSON. Later preparations enumerate again. Durable AI artifacts, original
emulation output, compact evidence and ADR024/ADR025 campaign roots are included;
symlink directories are not traversed and malformed relevant artifacts fail closed.

The three `native-driver-*` campaigns are proven **manual static-FIB, no model seeds**
by `nanfo.native-driver-acceptance/v1` protocols, `scoped-manual-driver-campaign`
authority, `static-FIB-no-OSPF` fixture, empty seed set and exact preserved runner
hash matching each protocol. Their protocols remain inventoried; only raw native
syscalls/results/setup evidence is excluded with that explicit provenance record.
For failed `/tmp/opencode/native-driver-ze6l5g0r`, protocol SHA
`eb27e77019538b8f3b194db44cbf6bc975d1e9969bba54a2d57f06dacb956130`
and original runner SHA
`b7d40393aa80dacbba5b368b47c65817d99eb7fde180d04eead61e10591cad61`.
Root-owned result permissions need no change; no historical chmod/edit occurred.

Unchanged input checkpoint `77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614`,
report `e6ee9c1bd99e3f6961db497db664335684fa277bd1a1c86a8034570ac116056d`,
tensor payload `3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967`.
Historical performance is not new campaign performance.

## Commands (from backend)

```sh
poetry run pytest tests/unit/test_experimental_campaign.py --no-cov -q
poetry run ruff check scripts/verify_experimental_lab.py scripts/audit_experimental_lab.py tests/unit/test_experimental_campaign.py

poetry run python -B -m scripts.verify_experimental_lab gates \
  --output /tmp/opencode/experimental-offline-gates-final

# Authorized preparation only; output must not exist.
poetry run python -B -m scripts.verify_experimental_lab prepare \
  --output /tmp/opencode/nanfo-experimental-campaign-001 --pairs 6 --budget-seconds 7200 \
  --gate-evidence /tmp/opencode/experimental-offline-gates-final/offline-gates.json
poetry run python -B -m scripts.verify_experimental_lab check \
  --output /tmp/opencode/nanfo-experimental-campaign-001

# Parent grants LIVE admission separately after final source/contract checks.
poetry run python -B -m scripts.verify_experimental_lab launch \
  --output /tmp/opencode/nanfo-experimental-campaign-001 \
  --parent-admission /absolute/private/parent-admission.json
poetry run python -B -m scripts.audit_experimental_lab \
  /tmp/opencode/nanfo-experimental-campaign-001 \
  --output /tmp/opencode/nanfo-experimental-campaign-001/independent-audit.json
```

Admission: owned0600 regular JSON, version`nanfo.experimental-parent-admission/v1`,
`core_adapter_ready:true`, `authorize_privileged_launch:true`, exact `plan_sha256`,
finite future `expires_ns`. Preparation permission is not this live admission.
All preparation/launch campaigns take the same nonblocking lock inode:
`/tmp/opencode/nanfo-privileged-lab-slot.lock`; never unlink/replace it.

## Offline verification

Campaign tests and combined core/simulation/adapter checks run through the executable
`gates` command, plus original receiver command-equivalence tests. Scoped Ruff is
included. The gate receipts pin source bytes before and after tests; changes during
checks or before preparation invalidate them. Tests exercise all68 scheduler slots, retained failure/
budget suffix, unresolved-owner stop, exact fault dispatch mapping, no credential
publication, real retained raw-frame interface replay, seed disjointness and locked
admission. Unit fixtures are not live positive evidence. Final checks are recorded
with the final source-pinned gate receipt. Prior intermediate receipts remain retained.

### Prepared campaign001 (no launch)

Preparation and source/model/seed check completed successfully:

- Root: `/tmp/opencode/nanfo-experimental-campaign-001`
- Plan SHA256: `92736d20a8b1f6f022bfa927b6e2821fdc714065140c908dbfa46a97a9cf33eb`
- Nominal seeds1012–1023:48 trials, six pairs per direction.
- Fault seeds1024–1043:20 distinct trials.
-155 exact source/test/dependency pins archived; no subsequent conflicting seed
  reservations found by a fresh read-only inventory.
- Gate receipt: `/tmp/opencode/experimental-offline-gates-003/offline-gates.json`:
  **97 combined backend offline tests passed**, including45 campaign tests;
  **12 original receiver/runtime tests passed**; scoped Ruff passed.
- `check` returns `prepared-not-launched`, all six contract-readiness checks true.
- No parent live admission was generated. No privileged container, private service,
  migration, model inference campaign or network traffic was launched.

Parent's next live command, only after issuing the matching private admission:

```sh
poetry run python -B -m scripts.verify_experimental_lab launch \
  --output /tmp/opencode/nanfo-experimental-campaign-001 \
  --parent-admission /absolute/private/parent-admission.json
```

Any source modification invalidates campaign001; retain it as a reserved attempt
and prepare a new campaign after fresh gates. Its unchanged seeds cannot be silently
recycled into a replacement plan.
