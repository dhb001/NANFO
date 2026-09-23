# R — Experimental014 diagnosis and repair handoff (ADR027)

## Corrected scanner recount —996 reservations,4 available,32 short (supersedes997)

Independent018 correctly identified an extraction defect: the old substring scanner
read `reserved_seed_count:1342` as a reservation. Origin:
`adr024-qualified-001/review/adr024-independent-runtime-review-final-002.json`,
SHA256`002d31c17281857c118c414d6c93c47e1ca5b083e661abf8cca3778316e5d800`,
field `reserved_seed_count` (line95). Historical inventories propagated that error.
**The earlier997 claim below is superseded; its frozen receipt is retained unchanged.**

Only active verifier/test code changed in this continuation:
- `backend/scripts/verify_experimental_lab.py`, SHA256
  `9e46d086343fffa3c0cfe95fb6c636172d03be5bd175ff030fedb7b5ec0c87c0`;
- `backend/tests/unit/test_experimental_campaign.py`, SHA256
  `200599ed6e52c5e13912d111257b44cda7a33de99497b4b4b73d82c1cae45937`.
This handoff is the sole documentation update; no runtime application edits.

Extractor uses explicit scalar/array reservation fields and named metadata
count/hash/reference/domain shapes instead of substring-based integer admission.
Unknown seed-bearing fields or invalid types fail closed. Actual selected/training/
plan/run assertions remain reserved. Domain declarations are not expanded into
consumption. Inventory corrections recurse through exact-byte SHA256 references;
relocated identical sources can substantiate corrections. Missing originals remain
reserved. Extra unexplained row or top-level assertions are not discarded.

For absent temporary001–009 inventory files, a narrowly **exact path+SHA256** reviewed
correction removes only the count-origin1342; the exact original review must also be
present and demonstrate that1342 is not an explicit reservation. This exception
does not apply to plan/run rows, unknown/changed inventories or arbitrary values.
Any genuine explicit1342 reservation would retain it in the global union. The
evidence receipt records all316 correction edges with reference hashes and paths.

Read-only recomputation across25,074 documents: **996 true or preregistered values
in1000–1999;4 unused;36 required;deficit32**. The only domain difference from the
old union is the count-only false positive. Verified all4 retained recent plan
documents and all9 missing earlier plan assertions still reserved. Post-publication
recount also returned996; the reference-only output does not reserve new values.

Evidence: `ai-engine/artifacts/nanfo-experimental-campaign-018-review/scanner-correction-recount.json`,
SHA256`409c7e80d758ce325d703487ce229e6825520f5385efeeb07f0069c3cb1ea882`.
Its test-source hash predates the final additional missing-inventory regression;
the final test hash is above. Verifier hash/recount evidence is unchanged.
Tests: **60 campaign tests passed**, including count1342 exclusion, typed ambiguity,
exact transitive correction, retained missing plans, unexplained assertions,
hash/path mismatch denial and origin-required correction. Scoped Ruff/whitespace pass.

Frozen018's1,818 payload files and original receipts were reverified unchanged.
No new campaign, freeze, admission, domain expansion or launch. Deployment parity:
active verifier/test bytes now differ from frozen018 and prior deployment source;
report this script drift separately if the executable release copies these files.
Existing acceptance remains scoped to its original source, not this corrected scanner.

---

## Active017 race repair and frozen018 gates — fresh plan BLOCKED by domain exhaustion

Active-source correction scope: `emulation/experimental_lab_contract.py`,
`emulation/experimental_lab_receiver.py`, `emulation/tests/test_experimental_lab.py`.
Frozen016 and all017 bytes remain unchanged; no old-plan retry or new launch.

Protected reads now anchor each directory component using no-follow directory FDs,
validate ownership/private leaf/ancestor permissions, and verify bindings again
after reading. Old bytes are discarded on genuine atomic replacement: only a safe
regular owned old inode with zero links and a **different**, safe regular single-link
pathname target permits reopen, at most3attempts. Missing paths, symlink/hardlink/
foreign/mode violations, changed parent bindings and in-place changes fail closed.
Unlinked bytes are never returned. Receiver authority still rechecks STOP, time,
scope and fence after protected I/O; a replaced revoked grant cannot become approval.

Failure diagnostics retain first protected-read failure separately from a subsequent
generic controller STOP: allowlisted file role, stage, attempt, inode/device,
owner/mode/link metadata and clocks, without file contents or arbitrary pathnames.
These survive in native journal/rejected receipts, including errors caught by the
original measurement routine. No blanket permission for unlinked files was added.

Deterministic regressions include actual replacement after open/during read/between
fstat and pathname stat, replacement churn, actual unlink, symlink, hardlink, FIFO,
directory, unsafe old/new modes, foreign file owner metadata, parent-path swap,
in-place mutation, revoked replacement authority, STOP during retry and secret-free
diagnostic retention. Foreign UID is injected at the actual fstat boundary; tests
require no privilege/chown. Existing original-routing and recovery tests still pass.

Prepared immutable root (1,818 files):
`/home/DHB/Documents/NANFO/ai-engine/artifacts/adr025-runtime-adr027-preparation-018/`

- Manifest SHA256: `18d051b0d513302bfbfc6b23f8b697b884b68bb9026f38260b314354992d89d3`.
- Gates: adjacent `adr025-runtime-adr027-preparation-018-gates/offline-gates.json`,
  SHA256`5c6accadb7d7881cee56c1adce6eb9eef251e01ed4239752de17b1b4a14e22fb`.
- Frozen gates via `/tmp/opencode/r07-backend/bin/python`: **115 backend passed,
  3 historical014-only skips;34 receiver/runtime passed;2 independent STOP probes
  passed;Ruff clean**. Active scoped stricter emulation Ruff also clean. Targeted
  backend composition61passed before freeze. No unnecessary repeated live check.
- Contract SHA256: `e0c308e589baaf8eda78444d1ed22d3420f95d51343b488101e5f9e5caea74a9`.
- Receiver SHA256: `f58895c1bcb1c0a517dab64b1cc25ee8bc29353ae0778a15de476500e5628a73`.
- Receiver tests SHA256: `8dba977caaebf01dd8dbfd98f688a213a9f57849c93c8f14c67ad4bb53a133de`.

Attempted the actual frozen `prepare --pairs 6 --budget-seconds 14400` with the
unchanged passed gates and all historical roots including017. It failed before
output creation with `unused_operational_seeds_exhausted`: **997/1000 values in
the permitted1000–1999 domain are reserved;3 remain,36 required**. Verified current
union is exactly017's prior961 reservations plus its36 selected values. This is
not a new receipt duplication or a reason to discard old failed reservations.
No plan hash exists, and no new values were reserved. Thresholds/budgets/domain
were not changed. Parent notified; resolving the domain requires explicit reviewed
direction rather than quietly reusing values or changing split/qualification scope.

Reference-only blocked-preparation receipt (no operational arrays):
`ai-engine/artifacts/nanfo-experimental-campaign-018-review/preparation-blocked.json`.
Records25,069 inventoried documents, provenance hashes/counts, all7readiness flags
true and original AI interpreter digest unchanged. Snapshot reverified after output.
The bounded preparation lock was released. No018 admission or launch is authorized.

**Deployment parity:** latest deployed/core0029 acceptance was for earlier frozen
source. The active protected-read/receiver wrapper now differs, and018 also snapshots
the current integrated tree. Prior deployment success must remain labelled with its
original source identity; it does not certify018. Parent needs separately scoped
latest-source deployment acceptance or an explicitly documented frozen-release
difference before claiming current-source parity. This workstream did not deploy.

---

## Actual authorized017 run — 4smokes complete,67/68 matrix complete, overall FAILED

Parent explicitly authorized exact plan
`284c869adeec8e9d8bf7834b2e37f8636ce05153090ce3c9c03180a195a9ff6b` after independent
review SHA256`1938051d84c377adcaefa2ec47172227d88c495cd7d071f9fe5ea312e3ef6a9c`.
Rechecked unchanged frozen016 manifest/all1,817 files, actual backend/base interpreter
hash and original AI interpreter, exact lab/Redis images, plan and new reservations.
Created private0600 exact-plan admission with15-minute launch-admission validity;
never printed its contents. Run used `/tmp/opencode/r07-backend/bin/python`, the
common exclusive campaign lock and attached foreground subprocess with15,600,000ms
outer tool timeout. Actual attached duration **5,366.617s (~89m27s)**, returncode1.
No source changes, same-plan retries, threshold changes or training occurred.

Private retained evidence root:
`/home/DHB/Documents/NANFO/ai-engine/artifacts/nanfo-experimental-campaign-017/`.
Review/diagnostic root: adjacent `nanfo-experimental-campaign-017-review/`.
Both are ignored/private; raw authentication material is not a publication bundle.

| Actual recorded stratum/outcome | Count |
|---|---:|
| Separate smokes, all kept then restored | 4/4 |
| Nominal kept then restored | 34 |
| Nominal complete performance rejection then restored | 13 |
| Nominal invalid measurement (failed) | 1 |
| Fault restored | 18 |
| Fault predispatch rejected | 2 |
| Matrix completed / failed / not run | **67 /1 /0** |

These are retained outcome counts, **not** a full-campaign acceptance pass or a
claim that rejected candidates improved performance. Full offline auditor executed
after the campaign and returned `campaign_blocked_or_incomplete`, agreeing with
`result.json`. Postrun diagnostic visited all68 cases and retained every unavailable
window. No paired-denominator dropping or historical014 outcome reclassification.

### Remaining failure and concrete software diagnosis

`path1-1564-qualified`: execute step1 and verify step2 are complete/passing. Failed
verify step3 raw canonical SHA256
`17d64bfcf42f94ec4989395955f079967b61a99e53dd4b0f4325e87f849a4f35`
has `truncated:true`, `measurement_complete:false`,
`error:protected_regular_owner_file_required`; native request
`9617ffcb-94e8-4ddb-bc19-f942ac02dc63` rejects `original_measurement_failed`.
Core interruption15:22:56.756591Z precedes deadline15:23:12.898951Z, so this is
**not expiry or bad performance**. First retained STOP is the controller's response
to rejection (`operator_or_controller`, monotonic37310.82288625), not an earlier
watchdog cause. Core restored15:22:57.050809Z and released; native restored too.
Aggregate metrics correctly remain null in `outcome-audit.json`.

An offline probe against **exact frozen016** contract reproduced a concrete
atomic-publication race: `protected_read()` opens a valid0600 owned regular file;
concurrent `atomic_write()` replaces its pathname before `fstat`; the open old inode
then has `st_nlink=0`, causing the strict `st_nlink==1` check to raise exactly the
retained error. During verification, receiver authority repeatedly reads
`authority.json` while authenticated heartbeat publication atomically replaces it.
The replacement remains valid and protected. Receipt:
`nanfo-experimental-campaign-017-review/protected-read-race-reproduction.json`.
Contract hash`811aed1593dbafa0ed931dbc7697af8464f662234eeae4055516e7f633b24056`.
The live frame does not retain pathname/fstat metadata: **exact live interleaving
is not proven**, although the software race and matching failure are reproduced.

Parent notified: a successor needs bounded reopen/revalidation for atomic-replace
races, preserving owner/mode/no-follow/hardlink checks and freshness/STOP semantics,
with deterministic replacement and malicious-file regressions. Do not simply waive
file protections. No fix was applied to frozen016 and017 was not retried. Any fix
requires newly frozen reviewed source, fresh preregistration/seeds and new admission.

### Cleanup and final retained checks

`cleanup.json`: removed=true, unresolved_resources=[], private Postgres/Redis ports
closed, children reaped, owned Redis container/volume removed, private store tree
removed. Independent postrun Docker inventory confirmed **72 owned lab containers
absent and all72 owned lab volumes absent**; pre-existing containers remain running.
Common lock could be reacquired after exit. Snapshot reverified unchanged.

Safe credential-free report files within the private review root:
- `launch-process-result.json` — attached lifetime/returncode and private-log digest;
- `postrun-audit.json` — actual full-auditor failed verdict;
- `postrun-diagnostic.json` — all68 recorded outcomes and raw-window reconstructions;
- `postrun-cleanup-verification.json` — exact-owned absence/store cleanup/lock check;
- `protected-read-race-reproduction.json` — offline reproduced defect and evidence limit.

The campaign's native/core journals retain successful recovery evidence, including
the fresh path1-link-failure case; prior014 remains unchanged. Fresh successor
measurement and final independent postrun acceptance are still required. No
production, RF, physical safety or model-retraining qualification is claimed.

---

## Prepared017 — same verified frozen016 source; final independent review pending

Independent016 review identified one prelaunch blocker: the sibling preparation
receipt repeated selected operational values after the saved inventory, and the
actual conflict checker correctly refused it. Read
`ai-engine/artifacts/adr025-runtime-adr027-preparation-016-review/independent-review.json`.
016's plan, receipt, gates, manifest and review remain byte-for-byte unchanged.

Per parent direction, **no scanner/code change or new freeze** was necessary.
Prepared017 from the same frozen016/backend using `/tmp/opencode/r07-backend/bin/python`
and the same source-matched passed gate receipt. Its17,868-document inventory includes
the old016 preparation receipt at its independently recorded hash as a reservation.
All36 newly selected operational values are disjoint from that full inventory.
Exactly4smoke+48nominal+20fault, source/model identities, thresholds, simulation,
outcomes and all budgets remain unchanged from016. The new review receipt contains
only hash-linked artifact references and counts, **no repeated operational values**;
the scanner's actual `seed_values()` returns an empty set for it.

Paths under `/home/DHB/Documents/NANFO/ai-engine/artifacts/`:

- **Plan:** `nanfo-experimental-campaign-017/plan.json`, SHA256
  `284c869adeec8e9d8bf7834b2e37f8636ce05153090ce3c9c03180a195a9ff6b`.
- **Reference-only receipt:** `nanfo-experimental-campaign-017-review/preparation-receipt.json`,
  SHA256`46bb2b2a3d8dbc1ce7edfb44453aec491da613874d035d2015085558783b9042`.
- **Reused executable root:** `adr025-runtime-adr027-preparation-016/`, manifest SHA256
  `d35bf39e2d2bcf94b9b21e3e6731d8779af738d2375672770861e64456c52d4f`.
- **Reused gates:** `adr025-runtime-adr027-preparation-016-gates/offline-gates.json`,
  SHA256`f85eeeab5eb797e95bcae66e4a6e4c7b3a8da5856730f57200591378170d6cb8`.

After publishing the final017 receipt, the **actual frozen** `verify_runtime_snapshot()`,
`validate_plan()` and `reject_new_seed_reservations()` all passed. The old016 receipt
still hashes to`981473d35331814e0edcb99df7d4f9a00759b8e3ad7995056bc9b8b7010a9e29`.
No provenance bypass, historical rewrite or conflict-check relaxation. Preparation
took/released the bounded common lock. New017 trees are ignored/private. No launch,
parent admission, new qualification claim or fresh measurement occurred.

Final reviewer must target **plan017 with frozen016**, not the blocked016 plan.
Following independent final review, parent may issue exact-plan017 admission. Use
the launch command below with `--output .../nanfo-experimental-campaign-017` and a
new parent-issued017 admission, from the same frozen016/backend. Global budget
14,400s and proposed attached outer timeout15,600,000ms remain unchanged.

## Preserved016 preparation record — superseded by017 after independent block

Parent subsequently authorized preparation. **No launch/admission was issued or
performed.** New executable snapshot contains1,817 pinned files. Paths below share
the prefix `/home/DHB/Documents/NANFO/ai-engine/artifacts/`:

| Artifact | Relative path | SHA-256 |
|---|---|---|
| Frozen manifest | `adr025-runtime-adr027-preparation-016/frozen-runtime.json` | `d35bf39e2d2bcf94b9b21e3e6731d8779af738d2375672770861e64456c52d4f` |
| Offline gates | `adr025-runtime-adr027-preparation-016-gates/offline-gates.json` | `f85eeeab5eb797e95bcae66e4a6e4c7b3a8da5856730f57200591378170d6cb8` |
| Preregistered plan | `nanfo-experimental-campaign-016/plan.json` | `f461a3626128a765188e98022317684bc116f354dc2f3f590090f89ce498793c` |
| Offline qualification | `adr025-runtime-adr027-preparation-016-review/offline-qualification.json` | `11b958c653b4391daf683ab25ca38598a23a95a802ae37e28521364076e528ce` |

Full machine-readable handoff:
`adr025-runtime-adr027-preparation-016-review/preparation-receipt.json`.
Executed gates from snapshot/backend using **`/tmp/opencode/r07-backend/bin/python`**:
115 passed/3 explicitly historical014-only skips;24 receiver tests;2 durable
independent STOP probes;Ruff clean. Additional preserved-raw/retention suites:
11 passed. All7readiness flags, including0029, true. Snapshot manifest reverified
after real confined offline qualification; no frozen source modified.

The vanished `/tmp` independent STOP test was recovered from014's preserved
`source/backend/tests/frozen_independent_review.py` lines77–128 into durable
`backend/tests/unit/test_experimental_independent_stop.py`, with the same two
interleavings. Gates now load that source-pinned file, not an optional external
test. Parent notice was sent before freeze. This is preservation of reviewed
regressions, not new independent reviewer approval.

Preparation also corrected seed discovery to include repository-root014, and
conflict checking to exclude only the current private campaign when it is nested
under an inventoried artifact root. Both have regressions. Snapshot/plan015 were
prepared before the latter correction and remain unchanged, reserved and superseded;
016 is the only proposed review target. Its inventory contains17,848 documents and
both014/015 reservations. Nominal seeds:1499,1508–1518. Fault seeds:1519,1528–1539,
1548–1554. Separate smoke seeds:1555–1558. Exactly4smoke+48nominal+20fault cases;
unchanged thresholds, action/age limits and outcome semantics. Plan016 selects the
existing permitted **14,400s** global budget to allow the full matrix; case180s,
bootstrap90s, cleanup reserve180s, I/O60s, lease65s, action30s. Proposed attached
outer tool timeout: **15,600,000ms** (4h20m). Exhaustion still records unrun cases
as failures; there is no automatic replay or success-by-budget exception.

Original AI interpreter: `/home/DHB/Documents/NANFO/ai-engine/.venv/bin/python`,
SHA256`f7c6210eb40fadcd3c2889dddd24a15fc2c9f926aec5a03bf9da66e12d581526`.
Actual confined qualification passed `adr024-rebuilt-evaluation-v1`, stationary
campus-small-v4 historical benchmark only; safety_authorized=false. Checkpoint
`77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614`, tensors
`3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967` unchanged.
Exact lab image inspected locally:
`sha256:954462c0f00d5bbaa72ea144f6064936b399c430e6ab94bffcf1c00d134ea0d7`.
Postgres binaries present; Redis binary absent but the plan's existing exact
Redis fallback image`sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2`
was inspected present. No image was launched/pulled/rebuilt.

All new trees are Git-ignored and protected (0700 roots,0600 published files).
Preparation alone took the common lock via its bounded CLI; it was released.
No credential files were generated/published by this preparation. Snapshot source
remains executable independently of later workspace docs/tests/CI changes.

After independent reviewer accepts **these exact hashes**, parent may issue the
protected admission for plan016. Proposed command, **not executed**, from
`.../adr025-runtime-adr027-preparation-016/backend/`:

```sh
/tmp/opencode/r07-backend/bin/python -B -m scripts.verify_experimental_lab launch \
  --output /home/DHB/Documents/NANFO/ai-engine/artifacts/nanfo-experimental-campaign-016 \
  --parent-admission /ABSOLUTE/PRIVATE/PARENT-ISSUED-PLAN016-ADMISSION.json
```

Fresh qualified model checks still execute per case; the offline receipt cannot
substitute for current runtime authorization or measured acceptance. Unknown014
STOP initiators and timing cause remain evidence limits described below.

---

## Original offline-repair handoff

Status: **offline repairs implemented; fresh measured acceptance and independent
review remain blocked/pending**. No privileged launch, freeze, seed reservation,
training, weight change, threshold change or commit in this workstream. Parallel
workspace edits preclude a meaningful final source freeze now.

## Evidence and eight failures

All paths below are relative to `nanfo-experimental-campaign-014/`. Its raw frames,
source, plans, journals and results were read only. The separate evidence-hygiene
owner handles credential-token preservation/removal. Historical014 still reports
60 completed / 8 failed matrix cases plus four smokes. A completed rejection is
not candidate success, and none of the eight failures is established as a legitimate
complete bad-performance rejection.

| Case | Retained evidence and actual diagnosis |
|---|---|
| `path0-1427-fixed1` | `controller-result.json` records `experimental_checkpoint_elapsed_during_authority` from `_checkpoint_state`, while verifying. `journal.json`: action deadline **21:26:05.521030Z**, interruption **21:26:05.945504Z**, previous durable holds at 21:25:55.953575 and 21:26:03.078117. All three post-action frames are complete. Core and native restore succeeded. Software misclassifies action expiry crossing blocking authority I/O as a generic checkpoint/control failure; not a performance failure. |
| `path0-1429-heuristic` | Same exception at the outer checkpoint deadline test after verification. Deadline **21:36:28.900745Z**, interruption **21:36:28.962334Z**; durable holds and three complete post-action frames, native/core restoration. Same expiry reason defect. |
| `path1-1434-fixed1` | Same final-authority exception; deadline **03:58:14.466880Z**, interruption **03:58:14.914450Z**. Three complete post-action frames, prior holds and exact restoration. Low-capacity route1 had substantial loss but all retained post-action windows passed the unchanged broad gates. No basis for calling this performance rejection. |
| `path0-1435-fixed1` | `controller-result.json` fails in the pre-verify heartbeat with generic receiver rejection. Deadline **03:59:47.175785Z**, interruption **03:59:47.367082Z**; step3 complete at probe timestamp03:59:44.232464Z and held03:59:45.102813Z. Receiver is stopped/restored. This is expiry-adjacent heartbeat rejection, consistent with the watchdog; **the original first STOP cause is not retained**, so the exact initiating thread/reason is unproven. Do not retroactively accept it from timing alone. |
| `path0-1429-fixed1` | Raw frame **`d6104afffeb46cda5297f6fb2cc5ec69a259055df73e6f8c6cbcc6525a3d13dd`**, step3: `measurement_complete:false`, `truncated:true`, `error:stopped`; no count denominators. Native verify receipt **ad22dbee-dc04-4446-9c80-2a20b862e370** rejects `original_measurement_failed`. Core heartbeat rejection/interruption **21:37:56.907417Z**, before deadline **21:38:02.266965Z**. Steps1/2 complete and passing; failed step stays unavailable. First STOP trigger cannot be recovered from retained artifacts. |
| `path1-1432-heuristic` | Raw frame **`01fa398f2d0e760868acdf32e202abf839bb88e499f8289338f0d7e25ca3c2e5`**, execute step1: `measurement_complete:false`, `truncated:true`, `error:stopped`; no traffic/probe metrics. Native execute **21182098-2e5e-48ec-8e9f-54181acff4a6** rejects `original_measurement_failed`. Core heartbeat rejection/interruption **21:54:00.080395Z**, before deadline **21:54:18.035710Z**. Not proven congestion loss or expiry. First STOP cause is missing. |
| `path0-1433-fixed1` | `attempt.json`: `qualified_frozen_runtime_unavailable` at joined-case qualification, **before receiver startup/policy creation**; `qualification.json`: `live_installation_expired_or_future`; `registry.json` installed **22:03:04.642755Z**, expires **22:09:05.642755Z**. Missing `operator_policy` is a secondary reconstruction error, not a missing policy from an executed loop. Retained artifacts lack qualification start/end clocks, so suspend/wall-clock discontinuity versus elapsed expiry is unproven. Do not extend installation lifetime or bypass qualification. |
| `path1-link-failure` | `intervention.json`: boundary **after first old-rule deletion** (break-before-make), not after candidate-route installation. Exact-owned access1-eth1 down **102581.314–102581.645** monotonic, up **102587.238–102587.617**. Failed step2 says `Routing cleanup uncertain; lab shutting down`; transcript ends with old route1 deletion **102582.961842**, no new candidate route installation. Core recovery runs **102584.264–102585.256**, while the original path is still down, and becomes `uncertain`. Frozen `matched.close()` removes rows, then requires original FRR forwarding; the injected outage prevents this readback. Native later becomes restored after link-up, but core never durably reconciles/release. Receipt **2acdac2f-c300-4ddc-a2ae-b16e8bd95dba** even contains verified restoration with status `rejected`: the receiver exception branch failed to update status after successful second cleanup. This is control/recovery failure, not a measured candidate-performance rejection. |

For each acquired case, `raw-frame-inventory.json` binds exact bytes and canonical
hashes; `native-journal.json` binds original frames and native receipts;
`journal.json` gives action deadlines, durable phase chronology and release state.
Independent count reconstruction uses the existing `raw_performance()` evaluator,
not bootstrap metrics as a substitute for failed steps. Every invalid window keeps
null aggregate metrics. Legitimate bad-performance cases elsewhere in014 remain
useful regression inputs; stricter diagnosis does not rewrite their recorded results.

## Implemented changes and limits

- **Expiry identity:** core rechecks the actual pending action deadline when blocking
  authority/commit crosses a bound. It reports `experimental_action_expired` only
  for that deadline; STOP/current authority and ownership checks remain enforced.
  Adapter maps a denied heartbeat to expiry only with an authenticated first
  `watchdog:action_expired` cause and locally elapsed admitted command deadline.
  No blanket acceptance of heartbeat/checkpoint errors. Existing audit still requires
  complete passing windows, durable hold and exact action/bootstrap recovery.
- **Recovery:** wrapper bounds original-forwarding reconciliation by the existing
  receiver heartbeat interval (10s in campaign policy). It retries only known
  readback failures **after owned rows are empty**; no new route additions, no retry
  of unknown mutation/foreign-state errors. Permanent outage remains unresolved.
  Successful fallback cleanup of a recovery request now returns `ok` with its real
  restoration, while failed execute/verify remain rejected. Original frozen routines
  and cleanup semantic guards are unchanged.
- **Missing cause:** first STOP is retained with wall/monotonic latch timestamps in
  the native journal and rejected receipts; secondary controller STOP cannot overwrite
  it. Watchdog records a finite credential-free cause code; response transport failure
  also latches a cause. Denied heartbeat wire receipts are exported without tokens.
  This repairs observability, **not a claim to have fixed the unknown014 STOP trigger**.
- **Preacquisition:** manifest retains attempt/qualification references; missing policy
  reports the actual setup failure instead of KeyError. Qualification start/end wall
  and monotonic clocks plus original registry validity are recorded for future diagnosis.
- **V2-01 review:** rejection requires ordered exact-action prepared → dispatching →
  interrupted → recovering → restored, durable recovery equality, allowed controller
  termination and exact failed-frame/native request-response binding. An unrelated
  `verified` marker or bad window cannot hide an unexplained control exception.
- **Read-only diagnostic:** `audit_experimental_lab --diagnose` visits all68 slots,
  reports recorded status separately, verifies references/raw inventories, reconstructs
  every available window and shows native versus core restoration. Always returns
  `diagnostic_only`, acceptance=false, exit1. Output must be outside evidence.
  It is an owner-run independent reconstruction of evidence, not reviewer signoff
  or a replacement for full acceptance audit.

## Offline validation

Commands (working directory `backend/` unless stated):

```sh
poetry run pytest tests/unit/test_experimental*.py --no-cov -q
poetry run ruff check app/modules/autonomy/experimental scripts/verify_experimental_lab.py scripts/audit_experimental_lab.py tests/unit/test_experimental_review_closure.py ../emulation/experimental_lab_receiver.py ../emulation/experimental_lab_runtime.py ../emulation/tests/test_experimental_lab.py
# From repository root:
python -B -m unittest emulation.tests.test_experimental_lab -q
# Diagnostic-only, expected exit1; never writes into014:
poetry run python -B -m scripts.audit_experimental_lab ../nanfo-experimental-campaign-014 --diagnose --output /tmp/opencode/adr027-experimental014-diagnostic.json
```

Final combined experimental backend run: **126 passed** (before the final additional
denied-heartbeat export regression); **24 receiver/runtime tests passed**. Scoped
Ruff and whitespace checks passed. Read-only diagnostic report:
`/tmp/opencode/adr027-experimental014-diagnostic.json` (68 cases,8 recorded failures,
diagnostic-only). Final additional denied-heartbeat export regression: **1 passed,
9 deselected**; scoped Ruff passed again. Total exercised backend cases:127; no
full-suite or live acceptance claim. Git's campaign014 diff lists only the separate
owner's71 token removals; raw/source/result files have no working-tree diff.
Regression coverage includes actual retained negative frames,
expiry crossing final authority, bound versus unrelated heartbeat denials,
first-STOP immutability, restored-but-rejected recovery, transient/permanent outage,
foreign-state nondeletion and forged/missing failed-window enforcement. Three
read-only historical014 regressions explicitly skip in new executable snapshots
where014 is deliberately absent; portable synthetic boundary regressions still run.
No PostgreSQL/Redis integration or privileged campaign is claimed here.

## Source freeze → preregistration → review → parent admission → run

1. Parent integrates all disjoint ADR027 changes and confirms stable source. Review
   the still-unproven STOP causes and qualification timing above. Check exact frozen
   gate contents, including the existing independent STOP-review input; missing review
   file blocks gates rather than being silently dropped.
2. From workspace/backend create a **new** unused ignored
   `ai-engine/artifacts/adr025-runtime-<new-id>` via
   `python -B -m scripts.verify_experimental_lab freeze --output ABSOLUTE_NEW_ROOT`.
   Never amend013,014 or any failed snapshot. Manifest publication rehashes source
   to detect concurrent edits; preserve unchanged weights and separate AI interpreter.
3. From **that snapshot/backend**, using the actual backend interpreter directly,
   run `-B -m scripts.verify_experimental_lab gates --output ABSOLUTE_NEW_GATE_ROOT`.
   Source-matched0029 readiness and complete model/reference closure required.
4. From the same snapshot prepare a new plan with `prepare --output NEW_CAMPAIGN_ROOT
   --pairs 6 --budget-seconds 7200 --gate-evidence NEW_GATE_ROOT/offline-gates.json`.
   Inventory all historical reserved/failed seeds including014 read-only. Four fresh
   separate smokes (2model+2heuristic),48 nominal and20 fault cases, unchanged common
   simulation/measurement thresholds,30s observation/action limits and all denominators.
5. Independent reviewer checks exact manifest/plan/gates, especially V2-01,
   link-recovery ordering, first-STOP provenance, and qualification timing. The
   afterwrite1 link fault can be a cleanup/partial-transition fault; it must not be
   described as completed candidate performance. If an after-installation measured
   fault is additionally required, preregister a new explicit boundary before collection.
6. Parent alone issues protected exact-plan live admission after review. Only then
   launch from frozen source under the common exclusive lock with an attached outer
   timeout exceeding campaign/setup/cleanup bounds. No launch authorization exists
   in this handoff. Changed bytes require new gates/plan/admission.
7. Retain every attempt, first STOP cause, denied heartbeat, qualification clocks,
   failed frame, native/core restoration and unresolved case. Re-run the full auditor
   and independent reviewer after acquisition. Invalid/unproven cases remain failures;
   destruction is never substituted for durable exact routing recovery. Fresh full
   measurement and reviewer signoff are still required to close R.
