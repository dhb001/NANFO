# Review closure — research evidence and remaining measurement plan

**Date:** 21 September 2026. **Status:** objective/evidence mapping and closure plan
prepared; research qualification remains partial. Tasks requiring human
participants, site surveys, instruments or authentic physical measurements **cannot
be completed here**. Their actual results remain **not collected / not executed**.

This supporting note applies [AcademicDocumentationGuide](../standards/AcademicDocumentationGuide.md),
read before preparing the note, and [ADR027](../adr/ADR-027-repository-review-closure.md).
The five objectives below were read directly from the single working
`ISPR2/Revised/Chapters_1_3_Reviewed/NANFO_Chapters_1_3_Reviewed.odt` content XML,
read-only. The ODT/PDF was neither edited nor re-rendered. This task reviewed local
records, not new external literature, and acquired no new research measurements.

## 1. Actual objective → evidence → closure mapping

The general objective is **“To develop a stability-aware deep reinforcement
learning flow orchestrator for proactive congestion control in an emulated
software-defined campus network.”** The bounded routing result supports part of
that aim; proactive integrated control and stability claims need the measurements
below. The original dates are retained as targets, not claimed achievements.

| Specific objective (verbatim, report §1.3.2) | Existing evidence and defensible scope | Remaining evidence / closure criterion |
|---|---|---|
| **i.** To analyse congestion indicators and traffic-management challenges under normal, burst and sustained-load campus-network conditions by September 2026. | Report §§3.2.1–3.2.2, 5.3.3 and 5.6.1; [academic review](../../ISPR2/Revised/Chapters_1_3_Reviewed/Academic_Review.md) records measured emulator observations and incomplete workload characterization. E1 below adds a bounded paired benchmark, not the full three-regime study. **Partial.** | Freeze normal/burst/sustained schedules and inclusion rules; collect matched offered-load, queue, goodput, RTT and loss traces with units, timestamps and denominators. Explain indicator behavior and failures separately by regime/direction. Missing regimes cannot be inferred from stationary windows. |
| **ii.** To compare the approaches and reported contributions of at least three existing intelligent network-management solutions by September 2026. | Report §2.3 and §5.6.2; academic review identifies Cisco Catalyst Center, Juniper Mist/Marvis, Arista CloudVision and four research implementations. A narrative comparison exists; it is not a NANFO-versus-vendor experiment. **Supported at review scope, source checks open.** | Verify exact accessible Cisco/Arista editions, dates, image provenance and claims; retain source/access records and APA 7 metadata. Resolve the recorded Cisco 403/Arista 406 access limitations without interpreting an access year as publication year. Update only from verified originals. |
| **iii.** To identify limitations in existing solutions concerning intervention timing, routing stability and reproducible evaluation by September 2026. | Report §§2.4, 5.6.3 and academic review: cited gap analysis distinguishes prediction/control, measurement-to-action timing, stability and reproducibility. **Supported as literature analysis.** | Retain a source/claim/limitation matrix with original task and measurement boundaries. Link each proposed experiment to the identified gap; do not convert a literature gap into a demonstrated NANFO advantage. Complete source checks from ii. |
| **iv.** To design and develop a PPO-based flow orchestrator with telemetry, operational safeguards and an administrator interface by October 2026. | Report Chapter 4 and §§5.3, 5.6.4; E1–E3 support frozen policy inference, non-actuating recommendations and separate manual-driver behavior. E4 records an attempted joined loop with failures. Software delivery and diagrams are substantial; calibrated integrated autonomy remains **partial/unqualified**. | Source/runtime/model/observation/action identity alignment, authentic causal bounds and installed enforcement, joined receiver traces, actual permission/STOP/recovery behavior, and independent scoped acceptance. New software regressions do not establish calibrated physical behavior. See P1/P4. |
| **v.** To test and validate the orchestrator against OSPF and non-learning baselines using delivery, congestion and routing-stability metrics by November 2026. | Report §§5.4, 5.6.5 and 6.2; E1 passes its bounded five-policy paired-seed benchmark. E4 fails full joined acceptance. Proactive timing, independent training repetitions, same-policy safeguards ablation, intended-user outcomes and complete recovery remain open. **Partial.** | Execute P1–P5 with predefined criteria and complete failed/blocked-attempt retention. Report paired independent experimental units, uncertainty and per-regime results. An objective can remain partially achieved if genuine scope revision is required; that revision requires the student/supervisor, not retrospective relabelling. |

## 2. Evidence ledger and current campaign status

These are existing records reviewed for this plan, not campaigns rerun by this
task. The [repository review](RepositoryReview-2026-09-21.md) and 18 September
academic review have different cut-off dates; later evidence extends only the
specific claim it actually tests.

| ID | Evidence anchor | Recorded result and boundary |
|---|---|---|
| **E1** | [ADR024 qualification review, final matrix](CompletionProgram/QualificationReview.md); [durable evidence index](CompletionProgram/QualificationEvidence.md); [benchmark outcome](CompletionProgram/QualificationEvidence-ADR024/evaluation/outcome.json) | Rebuilt checkpoint with unchanged tensor payload; five policies, 12 paired held-out seeds, 300 measurements / 240 decision windows; original scoped gates passed. Re-evaluating the same weights is **not independent training replication**. It establishes neither proactive lead time nor topology generalization. |
| **E2** | [Continuous service result](CompletionProgram/QualificationEvidence-ADR024/live/result.json) and E1's independent review | Six frames, four non-actuating recommendations and twelve exported durable rows. Bounded acquisition/inference/persistence demonstration; no autonomous dispatch or indefinite sustained-service claim. |
| **E3** | [Native-driver result](CompletionProgram/QualificationEvidence-ADR024/native/result.json), [qualification review](CompletionProgram/QualificationReview.md) | Owner 42-case record; 38 raw-command reconstructed cases plus four source-pinned exception receipts. Static-FIB emulation, not running FRR/OSPF convergence, physical-device qualification or a hard future deadline. |
| **E4** | [`nanfo-experimental-campaign-014/result.json`](../../nanfo-experimental-campaign-014/result.json); [current experimental repair handoff](ReviewClosure-Experimental.md) | Direct result reads `status: failed`, `reason: campaign_blocked_or_incomplete`, `calibrated: false`. Existing ledger records **68 main-matrix attempts: 60 completed, 8 failed**, plus four completed separate smokes. “Completed” includes keeps, measured rejection/restoration and predispatch rejection; it does not mean 60 improvements. |
| **E5** | [Physics handoff](CompletionProgram/Physics.md), [qualification review](CompletionProgram/QualificationReview.md) | Configured RF approximation and declared-split bias evaluation software exist. No real RF survey/equipment/data supplied in the recorded user context. Software fixtures do not establish physical accuracy or calibration. |
| **E6** | [Academic review, §§5.4/priority obligations](../../ISPR2/Revised/Chapters_1_3_Reviewed/Academic_Review.md); [full-stack repair handoff](ReviewClosure-Fullstack.md) | Browser/component and integration evidence support functional behavior at their executed scope. They do not supply participant consent, task observations, interpretation errors, satisfaction or intended-user acceptance. Current release deployment/fresh restore must be source-matched and separately evidenced. |

### Campaign014: preserve failed classifications

The eight failures remain in the historical result:

- `path0-1427-fixed1`, `path0-1429-heuristic`, `path1-1434-fixed1`: retained
  deadline crossings were classified as generic control/checkpoint errors.
- `path0-1435-fixed1`: expiry-adjacent heartbeat rejection; the initiating STOP
  cause is not established by the retained evidence.
- `path0-1429-fixed1`, `path1-1432-heuristic`: incomplete/stopped measurement
  frames; missing metrics stay unavailable, not zero or a performance rejection.
- `path0-1433-fixed1`: qualification failed before acquisition; missing
  `operator_policy` was a secondary reconstruction error.
- `path1-link-failure`: fault occurred after old-rule deletion, before candidate
  installation; durable core recovery remained uncertain. Later native cleanup
  does not by itself establish reconciled core restoration.

The [experimental owner handoff](ReviewClosure-Experimental.md) records offline
repairs and regression checks. Those are implementation evidence, **not a passing
replacement measured campaign**. New first-STOP logging cannot recover the missing
historical cause. Preserve all raw frames/results and original thresholds; never
promote failed cases based on repaired reconstruction logic alone.

## 3. Ordered acquisition and analysis plan

All rows are **planned / unexecuted in this task**. Owners below designate the
needed role, not a claim that a person has accepted the assignment. Thresholds,
sample sizes and exclusions must be justified and recorded before new acquisition;
this note invents no measured values or new success cutoffs.

| ID / objectives | Responsible role and prerequisites | Required evidence and analysis | Closure condition / current gap |
|---|---|---|---|
| **P1 — joined acceptance (iv, v)** | Integration/experimental owner and independent reviewer; stable source, new frozen runtime, matching offline gates, preregistered plan and explicit existing lab admission process. Follow the experimental handoff's exact sequence. | New immutable campaign root; fresh non-reused seeds; retained source/image/checkpoint/plan hashes, admission identities, complete pre/post frames, denominators, STOP causes, monotonic/wall clocks, qualification timing, action receipts and durable recovery. Preserve all attempts and invalid windows. | New source-matched measured matrix and independent acceptance under unchanged gates; report performance rejection separately from unavailable/unproven/control failure. Historical014 stays failed. No campaign launch occurred here. |
| **P2 — workloads and proactive timing (i, iii, v)** | Research/experimental owner; matched normal, burst and sustained schedules; predefined congestion event and intervention definitions, matched reference/baseline conditions and clock provenance. | Timestamp observation, inference, approval/dispatch, action completion and reference congestion onset. Define signed lead time as reference onset minus completed intervention time; retain negative/zero values and undefined cases. Compare full delivery/congestion traces against OSPF and non-learning baselines, not inference latency alone. | Predefined full matrix, baseline counterfactual rationale, independent repetitions and uncertainty by workload/direction. Without a valid reference onset, no proactive claim. Fast inference alone is insufficient. |
| **P3 — training robustness and stability (iii, v)** | Research owner; genuinely separate training initializations, fixed train/validation/test partitions, selection/stopping rules and locked analysis before final holdout. | Retain every training attempt/checkpoint and seed. Separate initialization variance from paired evaluation-seed variance. Measure route changes, dwell/oscillation, loss/queue/goodput and full control timing. Use a predefined same-policy safeguards comparison in a permitted non-production experiment; retain mandatory authority and STOP protections. | Independent training and matched ablation evidence with failures and uncertainty. Rebuilt tensor-identical E1 cannot count as another initialization. If a valid ablation cannot run, mark it blocked rather than comparing unlike policies as if causal. |
| **P4 — release and recovery (iv, v)** | Deployment/operations owner; exact source, schema0029, images, backup and disposable fresh restore target; dedicated authorized interruption environment. | Retain fresh installation/migration, encrypted backup/restore and functional checks; distinguish process restart, worker/receiver restart, link loss and whole-host interruption. Reconcile committed state, spool/replay, missing observations, in-flight authority and routing readback. Quantify observed data loss and recovery time where measured. | Source-matched current-release acceptance and each required interruption case. Container destruction, a unit test or an old-schema receipt cannot stand in for exact restoration or a whole-host test. Human-operated equipment interruption cannot be performed here. |
| **P5 — intended-user study (iv, v)** | Student/researcher with representative network administrators and actual participant access; appropriate consent/permission, a justified recruitment/sample plan and frozen task script. | Tasks: interpret telemetry and uncertainty, distinguish modeled/measured evidence, review a recommendation, identify pending/failed action status, recover from a page failure, and use authorized STOP/recovery in a suitable test environment. Record anonymized participant/task IDs, completion/errors, assistance, task time, interpretation mistakes and genuine feedback; include keyboard tasks. Predefine scoring/instrument and analysis. | Actual participant observations and analysis against predefined criteria. Recruitment, human task performance, consent and feedback **cannot be completed here**. Automated browser checks provide functional evidence only; do not create fictional participants or fill actual-results cells with expected outcomes. |
| **P6 — RF/physical-fidelity gap (related system claim; conditional iv/v extension)** | Student/site operator and competent measurement personnel; equipment, authorized site access, surveyed geometry, radio/device configuration and independently sourced measurements. | Record instrument identity/calibration, units, timestamps, AP power/frequency/antenna settings, receiver positions, material/geometry provenance and repeated observations. Predeclare grouped train/holdout campaigns; fit only training observations. Report baseline/fitted held-out count, MAE, RMSE, signed error and maximum absolute error with measurement uncertainty and unsuccessful fits. | Authentic measurements plus independent interpretation within a justified physical scope. The implemented `rf-declared-split-bias.v1` evaluator keeps `calibrated=false` even after measured holdout evaluation. Human surveys/instrument measurements **cannot be completed here**. The five stated objectives are wired/emulated; RF is not silently made a sixth objective or a prerequisite for reporting the bounded routing result. Broader RF claims remain unqualified. |

### Evidence handling and reporting gates

1. Keep a record per case with objective/requirement ID, protocol/source/runtime
   identity, expected result, **actual result or “not executed”**, evidence path/hash,
   status, failure/exclusion reason and review outcome. Preserve missing, invalid and
   blocked cases in denominators; never substitute a cleanup receipt for recovery.
2. Use independent seeds/episodes and training runs as the relevant statistical
   units. Adjacent windows are dependent; do not inflate sample size by treating
   every transition as an independent replicate. Predefine pairing, interval method,
   exclusions and any multiplicity handling before examining new holdout results.
3. Follow [evidence-hygiene handoff](ReviewClosure-Evidence.md): exact-byte private
   preservation, checksum-addressed references and credential-free allowlisted
   publication. Confirm supervisor access to genuine retained artifacts; a local
   ignored directory or a historical `/tmp` path is not durable examiner access.
4. Once genuine evidence is accepted, a separately authorized report update can
   revise Chapter 5 expected/actual tables, Chapter 6 objective-by-objective
   conclusions and finally the abstract. Retain negative findings and unqualified
   claims. No such report revision is performed in this task.

## 4. Human/source/administrative closure ledger

| Obligation | Status / next evidence required |
|---|---|
| Physical RF/site/device measurements | **Blocked externally; cannot complete here.** Actual instruments, site/geometry records and held-out observations required. |
| Intended-user measurement and acceptance | **Not collected; cannot complete here.** Genuine participants, task records and analysis required. |
| Supervisor scope/signatures/approvals | **Pending genuine human action.** If the general objective cannot be evaluated as promised, obtain a recorded scope decision; no approval is inferred. |
| Cisco/Arista source editions and image credits | **Open source verification.** Locate accessible originals and confirm metadata; no new web verification claimed by this note. |
| November course target versus original December Gantt | **Unresolved.** Student/supervisor decision required; retained image is not silently redrawn. |
| Repository/archive access, redistribution and retention | **Confirm with student/supervisor.** Provide an accessible credential-free index and permitted artifacts; no public availability inferred from a repository URL. |
| Current similarity assessment and required declarations | **Pending if required by course.** Obtain genuine current records and resolve disclosure with supervisor; report-editing override remains applied. |

**Completion boundary:** this note delivers a sourced closure plan. It does not
close scientific, participant or physical qualification by documenting its absence.
