# NANFO academic review and remaining evidence

**Review date:** 18 September 2026

**Working report:** [ODT](NANFO_Chapters_1_3_Reviewed.odt) · [PDF](NANFO_Chapters_1_3_Reviewed.pdf)

**Assessment basis:** *How to Write a Research Proposal & Documentation*, supplied as `ISPR2/Research Writing for CS 2 Projects - 2026 (3) (2).pdf`; class template; supplied examiner feedback; `docs/standards/AcademicDocumentationGuide.md`; latest student overrides.

## Overall judgment

The revised report is a substantially better-supported account of a **completed bounded routing experiment and a partially completed integrated research system**. It now extends through Chapter 6. The writing and document structure are much closer to the course requirements. The strongest result is the retained, matched PPO benchmark; the most important unresolved issue is that the title and general objective promise proactive, stability-aware orchestration whose complete integrated evaluation is still outstanding.

This is suitable for supervisor review as a September progress-stage report. It is **not yet evidence-complete final documentation of all five objectives**. Correctly admitting limitations improves credibility, but does not earn the same completion credit as executing the missing experiments.

The supplied proposal marking sheet records **31.5/40**, dated 4 July 2026. That is the historical examiner mark, not a mark for this revision. The supplied 40-point rubric assesses a proposal; it cannot establish a final-project mark for Chapters 4–6. The judgments below identify likely deduction risks rather than inventing an official new score.

**Judgment key:** Strong = supported at the stated scope; Conditional = sound presentation with an unresolved verification or assessment issue; Partial = substantive promised evidence remains missing. These are review judgments, not examiner verdicts.

## Front matter

| Item | Judgment | Review and remaining mark risk |
|---|---|---|
| Title and cover | Conditional | Specific technology and problem; 15 whitespace-delimited words with hyphenated terms counted as one. Report designation and September 2026 date now match the material. “Proactive” remains a research aim, not a demonstrated outcome; reconcile the final scope with the supervisor if timing evaluation cannot be completed. |
| Declaration/approval | Conditional | Names and admission number retained; signature/date lines remain blank for genuine completion. No approval is inferred. |
| Acknowledgment | Strong | Brief, research-related, third-person wording. The student must confirm the acknowledgment reflects actual contributions. |
| Abstract | Strong at stated scope | Rewritten around actual methods, samples, measured results and contribution. 179 words; 192 including keywords. Keywords are bold italic. No citations or equations. Meets the stricter 200-word cap, although its 1.5-spaced rendering is longer than the template's approximate half-page aspiration. |
| Contents and lists | Strong | Automatic fields refreshed. All 168 linked contents/figure/table/equation entries checked against destination-page footers. Four previously omitted landscape table captions are listed. |
| Abbreviations | Strong | Added relevant technical definitions and alphabetized the list. Expansion does not replace explaining a specialized concept in its relevant section. |

## Chapter 1: Introduction

| Section | Judgment | Review and remaining mark risk |
|---|---|---|
| 1.1 Background | Strong | Moves from traffic distribution and campus services to routing, learning and operational evaluation. Relevant research and protocol citations support the narrative. No invented campus statistics. |
| 1.2 Problem statement | Strong in formulation; partial in resolution | Ideal → shortfall → consequence/response sequence retained. The gap is bounded to the studied combination rather than claiming no comparable system exists. Stationary adaptation is now distinguished from preventive intervention. |
| 1.3.1 General objective | Partial | Clear and aligned with the title. Complete proactive, stability-aware integration is not yet demonstrated. Changing tense cannot close this issue. |
| 1.3.2 Specific objectives | Strong formulation; partial achievement | Five concise Roman-numbered statements, measurable scope and dated targets. No explanatory mapping paragraph under the objectives. Objectives i, iv and v retain substantive unfinished elements. |
| 1.4 Questions | Strong | Five questions correspond to the objectives in order and scope, without presupposing success. |
| 1.5 Justification | Strong | Links useful delivery to timing, stability and reviewable execution. Benefits are plausible and bounded; no unsupported saving or improvement claim for institutional deployment. |
| 1.6 Scope | Conditional | Separates operator and benchmark environments, synthetic measurements and excluded institutional data. November completion remains the course target. Original appendix schedule still extends to December; see unresolved items below. |
| 1.7.1 Limitations | Strong | Hardware, sample, shared-host and integration constraints now have explicit effects on interpretation. |
| 1.7.2 Delimitations | Strong | Intentional wired/emulated/two-path boundaries distinguished from unavoidable constraints. Manual QoS functions are not described as learned actions. |

## Chapter 2: Literature review

| Section | Judgment | Review and remaining mark risk |
|---|---|---|
| 2.1 Introduction | Strong | Defines a focused narrative review, source-selection rationale, recent-research preference and thematic organization. No fabricated systematic-search counts. |
| 2.2.1 Routing/traffic engineering | Strong | Separates reachability, configured costs, state-dependent routing and proactive intervention. |
| 2.2.2 Congestion indicators | Strong | Explains utilization, queues, RTT, goodput and loss with measurement boundaries. |
| 2.2.3 Operational challenges | Strong | Connects observation quality, model uncertainty and routing stability to the research problem. |
| 2.3.1 Cisco Catalyst Center | Conditional | Capabilities and vendor-evidence limitations are discussed and the original illustration is credited. Cisco returned HTTP 403 during this review; exact current publication dates, image provenance and capability wording need an accessible official copy for final independent confirmation. |
| 2.3.2 Juniper Mist/Marvis | Strong | Official datasheet accessible; August 2025 date verified. Operational value distinguished from a controlled DRL comparison. |
| 2.3.3 Arista CloudVision | Conditional | Relevant telemetry/change-management comparison and credited image. Official datasheet returned HTTP 406. Existing 2026 reference date and 2025 image copyright were retained, not newly authenticated. Confirm the actual edition; an access year is not automatically a publication year. |
| 2.3.4 DRL–GNN | Strong | Original study's optical-allocation task, architecture and unseen-topology evaluation distinguished from NANFO's repeated active-flow routing. |
| 2.3.5 ENERO | Strong | Hybrid DRL/local-search method and bounded timing result interpreted in its own action space. |
| 2.3.6 RouteNet-Fermi | Strong | Prediction distinguished from control; simulation, trace and physical-testbed error differences discussed. |
| 2.3.7 GTSR | Strong | Original paper checked for model, topology, workloads, control step, training steps and frozen testing. Different simulation assumptions remain explicit. |
| 2.3.8 Comparison | Strong | Three commercial platforms plus four research implementations exceed the minimum three-system coverage. Table compares purposes and limitations, not incompatible headline percentages. |
| 2.4 Gaps | Strong formulation | Connected, cited prose derives timing, stability, measurement-to-action and reproducibility gaps. Planned ablation and timing analysis remain open obligations. |
| 2.5 Framework | Strong design account | Original full-mark conceptual image preserved. Inputs/processes/outcomes and feedback are explained; arrows are no longer treated as proof of implemented autonomous integration. |

Literature currency remains a moderate assessment risk: foundational and 2022 studies are justified, and 2023–2025 work is included, but this is a selective narrative review rather than exhaustive coverage of all recent routing research.

## Chapter 3: Methodology

| Section | Judgment | Review and remaining mark risk |
|---|---|---|
| 3.1 Introduction | Strong | Experimental quantitative paradigm and OOAD identified; design artefacts remain in Chapter 4. |
| 3.2 Research paradigm | Strong | Variables, controlled conditions, matched seeds and limits to causal interpretation explained. |
| 3.2.1 Acquisition | Strong at emulator scope | Synthetic schedules and measured observations separated from institutional records; lawful source/provenance boundary explicit. |
| 3.2.2 Processing | Strong | Fixed transformations, availability indicators, missing-data semantics and dependent transitions explained. Actual input example added in 5.3.5.1. |
| 3.2.3 Training | Strong with declared exception | Architecture, reward, algorithm, seeds and checkpoint selection are explicit. The original 512-transition minimum was not reached; later authorization and test-only selection are disclosed in 5.3.5.2. |
| 3.2.4 Validation/testing | Partial | Matched held-out stationary benchmark is complete. Normal/burst/sustained workloads, multiple trained initializations, safeguard ablation and proactive lead time remain planned. |
| 3.3 / 3.3.1 Development method | Strong | Agile prototyping and Kanban-style tracking justified; no invented full Scrum process or completed review meetings. |
| 3.4 Lifecycle diagram | Strong | Original methodology figure retained with the five course-prescribed stages and attribution. |
| 3.4.1 Planning | Strong | Literature, contracts and assessment linked to priorities and evidence plans. |
| 3.4.2 Initial prototype | Strong at recorded scope | Technologies and component responsibilities explain how a working increment was built. |
| 3.4.3 Refinement | Conditional | Actual defect/validation-driven refinement described. Proposed supervisor-review cadence needs dated records before being reported as completed. |
| 3.4.4 Testing | Strong method; partial execution | Test levels and perspectives are distinguished; failed attempts and retests retained. |
| 3.4.5 Final evaluation | Partial | Final acceptance is a remaining stage, not a consequence of component test counts. |
| 3.5 / 3.5.1–3.5.3 Tools, learning and safeguards | Strong | Tools have specific roles; inference, measured control and conditional model assessment remain distinct. |
| 3.6.1 Documentation | Strong at retained scope | Actual archive and installation/operator material identified; later campaigns require their own evidence. |
| 3.6.2 Authentication | Strong at recorded scope | Scoped access deliverable linked to implementation/testing. |
| 3.6.3 Telemetry | Strong at recorded scope | Measurement path described with explicit replay and outage limits. |
| 3.6.4 Routing/safeguards | Partial | Standalone policy and application controls are delivered; calibrated combined live autonomy is outstanding. |
| 3.6.5 Dashboard/reports | Strong at recorded scope | Functional deliverables supported by pipeline/browser evidence, not participant usability evidence. |

## Chapter 4: Analysis and design

| Section | Judgment | Review and remaining mark risk |
|---|---|---|
| 4.1 Introduction | Strong | OOAD views selected to explain actual research-system responsibilities. |
| 4.2.1 Functional requirements | Strong catalogue; partial acceptance | Unique IDs, required behaviours and verification paths. FR-12 autonomy remains unfulfilled at integrated-system level. |
| 4.2.2 Non-functional requirements | Conditional | Testable access, identity and recovery outcomes are meaningful. Measured usability, broad performance and full recovery coverage remain incomplete; arbitrary thresholds were not inserted. |
| 4.2.3 Data requirements | Conditional | Provenance, integrity, ownership and evidence links added. Retention and recovery completeness still require verification. |
| 4.2.4 Interfaces | Strong specification | Contract, trust, acknowledgement and unavailable states described; additional design/test cross-links added. |
| 4.2.5 Traceability | Strong | Objective → requirement → design → test/evidence mapping strengthened. IDs assigned for documentation are not presented as an original historical backlog. |
| 4.3.1 Actors/use cases | Strong design account | External actors, system boundary and relationships retained from the critically reviewed diagram set. |
| 4.3.2 Observation workflow | Strong design account | Identity, validity, persistence and assessment eligibility visible. |
| 4.3.3 Approval/execution | Strong design account | Operator authority, dispatch and verified result distinguished. |
| 4.3.4 Overrides/failures | Strong design account | Unresolved restoration and guarded return retained. |
| 4.3.5 Information/state | Strong | Explains identity and lifecycle invariants across workflows. |
| 4.4.1 Architecture/classes | Strong | Two distinct landscape diagrams under the correct heading; module integration and actual software classes are not conflated with logical schemas. |
| 4.4.2 Logical data design | Strong | Two schemas distinguish ownership, foreign keys and cross-module logical references. |
| 4.4.3 Interface/events | Strong | Reconnection and authorized reconciliation sequence explains stale/context handling. |
| 4.4.4 Learning/safeguards | Strong design; partial implementation evidence | Compatibility, calibration and current authority separated from model qualification. |
| 4.4.5 Operator design | Conditional | Wireframe communicates intended evidence and error states. It is a design view, not a participant-tested interface or an exact screenshot of the latest UI. |
| 4.4.6 Deployment/recovery | Conditional | Isolation and file-handoff boundaries are explicit. A deployment diagram does not close fresh-restore or host-power-loss acceptance. |

All twelve Chapter 4 images and their original editable sources were preserved. Prior source-level connector/label review remains recorded in `Chapter_4_Diagrams/Diagram_Work_Log.md`; this revision checked their document placement and preservation rather than claiming new modelling experiments.

## Chapter 5: Implementation, testing and evaluation

| Section | Judgment | Review and remaining mark risk |
|---|---|---|
| 5.1 Introduction | Strong | Defines the different evidence types and completed benchmark clearly. |
| 5.2.1 Hardware/environment | Strong at documented scope | Host, laboratory and benchmark conditions differentiated; no institutional deployment asserted. |
| 5.2.2 Software/configuration | Strong | Versioned dependencies, processes and configuration roles presented. |
| 5.2.3 Deployment/reproducibility | Conditional | Dependency locks, initialization, migrations, readiness, access and licensing clarified. Full fresh-install/restore acceptance is not established by builds/imports. |
| 5.3.1 Identity/scope/data | Strong | Authorization and module-owned data behaviour linked to contracts. |
| 5.3.2 Devices/acquisition | Strong | Actual producer and measurement boundary described. |
| 5.3.3.1 Snapshot/messages | Strong | Record structure and identity permit traceable interpretation. |
| 5.3.3.2 Device trust | Strong within laboratory boundary | Protected bindings distinguished from producer-controlled values; no blanket trust in arbitrary physical devices. |
| 5.3.3.3 Rates/persistence | Strong | Counter-duration calculations, reset handling and stable deduplication explained. |
| 5.3.3.4 Buffering/reconnect | Strong with explicit limitation | Prefix replay and browser reconciliation supported; memory-only pending batch prevents a loss-free source guarantee. |
| 5.3.3.5 Power recovery | Partial | Specific interruption tests exist; complete host-power-loss recovery remains unverified. |
| 5.3.4 Simulation/manual actions | Strong at recorded scope | Numerical byte accounting separated from measured reroute/multipath/QoS results and the PPO action space. |
| 5.3.5.1 Dataset/preparation | Strong | Ownership, records, partitions, seed counts/proportions and real before/after sample supplied. Training/validation/test sets are split by workload episode, not mixed adjacent transitions. |
| 5.3.5.2 Training/selection | Strong transparent account | Seed 44, 384 transitions, 24 updates and hyperparameters supplied. Original stopping shortfall and authorized selection exception preserved. One initialization limits robustness. |
| 5.3.5.3 Inference/integration | Partial | Frozen inference/confinement supported; this is not live autonomous dispatch. |
| 5.3.6 Alerts/reports/operator workflow | Strong at recorded scope | Sustained alert conditions and complete report-generation/download workflow described. Report pipeline fixtures are not live-campus or usability results. |
| 5.4.1 Strategy/criteria | Strong | Expected outcomes and paired-seed statistical unit clear. Criteria are tied to the retained campaign rather than retroactively invented. |
| 5.4.2 Cases/defects/retests | Strong reporting; partial acceptance | Actual/evidence/verdict columns retained. Step14 progressed from 18 pass/4 fail/9 blocked to 22 pass/0 remaining executed-case fail/9 blocked; overall status remains partial. |
| 5.4.3.1 Routing performance | Strong bounded result | All 240 decision-window goodput/loss calculations and eight paired mean/CI comparisons checked. Nominal-cost OSPF is specified; no universal DRL superiority inferred. |
| 5.4.3.2 Training/stability | Partial | Learned directionality and route-change behaviour recorded. Independent training repetitions and same-policy safeguard ablation remain necessary. |
| 5.4.3.3 Timing | Partial | Inference separated from full control/observation time. Proactive intervention lead time was not measured. |
| 5.4.3.4 Application/recovery | Partial | Genuine application evidence, but nine blocked cases, missing participant outcomes and incomplete full recovery prevent complete acceptance. |
| 5.4.4 Presentation/interpretation | Strong | Tables and new Figure 5.1 expose pooled and direction-specific results with uncertainty. Narrow path-1 intervals are practically invisible at the pooled plot scale; exact values remain in the table. |
| 5.5 Version control/evidence | Conditional | Exact evidence paths, source commit and checkpoint digest supplied. Unauthenticated GitHub URL returned 404; supervisor access, redistribution terms and durable retention need resolution. |
| 5.6.1 Objective i | Partial | Measurement implementation is substantial; full workload characterization remains incomplete. |
| 5.6.2 Objective ii | Strong with vendor-source caveat | Seven systems analyzed without pretending to benchmark NANFO against commercial products. |
| 5.6.3 Objective iii | Strong gap analysis | Timing, stability and reproducibility limitations made concrete. |
| 5.6.4 Objective iv | Partial | Operator functionality demonstrated; combined calibrated autonomous controller is not. |
| 5.6.5 Objective v | Partial overall | Held-out stationary criterion passed; broader promised evaluation remains open. |
| 5.6.6 Validity | Strong | Internal, statistical, construct, external and reproducibility limits explained, including session effects, one initialization and heterogeneous directions. |

## Chapter 6, references and appendix

| Section | Judgment | Review and remaining mark risk |
|---|---|---|
| 6.1 Introduction | Strong | Added closure of the objectives-to-evidence chain without new experiments. |
| 6.2 Conclusions | Strong synthesis; partial achievement | Answers objectives in order and reports the bounded numerical result. Explicitly concludes that the general objective is only partly fulfilled. |
| 6.3 Recommendations | Strong | Identifies responsible audiences, actions, conditions and evidence-based priorities. |
| 6.4 Future work | Strong | Separates unfinished promised work from genuine extensions: topology transfer, changing demand/drift and a later authorized operator-decision pilot. |
| References | Conditional | 22 alphabetized APA-style entries; matching in-text author/year identities reviewed. Almasan groups disambiguated by second author. Italic titles/venues, hanging indents and DOI/URL forms retained; selected dates, issue metadata and OWASP URL corrected. Cisco/Arista verification limitations remain. Course 1.5 spacing takes precedence over generic APA double-spacing. |
| Appendix 1 | Conditional | Original Gantt image is unchanged and appendix contains the item/caption only. Its December end still conflicts with the November course target. No current similarity report or genuine approval was manufactured. |

## Priority evidence obligations before final submission

1. **Resolve title/objective completion:** execute integrated live PPO-plus-safeguard evaluation using compatible observations/action mappings and calibrated bounds, or obtain a genuine supervisor-agreed scope revision. Do not silently replace the research question with the easier completed benchmark.
2. **Complete the promised experiment matrix:** normal, burst and sustained load; timestamped intervention/reference congestion events; same-policy safeguards on/off; independently trained initializations. Retain workload plans, failed/blocked attempts, seeds, traces and analysis. Report seed-level uncertainty and route-change measures.
3. **Complete recovery acceptance:** fresh installation/restore and whole-host interruption, including the memory-only handoff boundary and any observations lost. Establish the limits actually observed.
4. **Collect intended-user evidence:** representative administrators, genuine tasks/consent where relevant, task outcomes, interpretation errors and feedback. Browser tests cannot substitute for this.
5. **Make the evidence examinable:** confirm supervisor repository/archive access, exact source/runtime/checkpoint identities and retention. Locate surviving originals for campaigns presently represented only by summaries.
6. **Close administrative/source issues:** verify blocked Cisco/Arista editions and image credits, reconcile the original December Gantt with the November target, obtain genuine signatures/approval and a current similarity assessment if required. Resolve the course assistance-declaration requirement with the supervisor; the student's explicit report-editing override has been respected.

## Verification record

- Original report: 125 exported PDF pages. Revised report: **133 exported pages**, with preliminary Roman numbering and main text ending on printed page 120.
- LibreOffice's internal layout reports 134 pages because it inserts an empty parity page immediately before Chapter 1. A diagnostic export including empty pages confirmed that page; the delivered export omits it. This is not an off-by-one index error: all **168 linked index entries** match the actual destination-page footers.
- All **18 original embedded images** are byte-identical, including the methodology lifecycle, conceptual framework, twelve Chapter 4 figures and original Gantt. New Figure 5.1 is derived from the retained experiment; its editable vector source is adjacent to the report.
- Twelve Chapter 4 figures, ten Chapter 5 tables, one Chapter 5 figure and five Chapter 3 equations have sequential captions. Landscape table captions now appear in the table list. Heading/list fields and caption sequences are automatic; prose cross-references still require care after future renumbering.
- Body style: Times New Roman, 12 pt, 150% line height. Reference hanging indents and keyword bold/italic formatting checked.
- Full-document contact sheets reviewed; selected figure, table, conclusion and reference pages inspected at larger size. Automated PDF text-bounds checks found no out-of-page text. These checks do not prove every diagram is semantically perfect.
- Five raw `evidence.jsonl` SHA-256 values matched the retained report. All 240 reconstructed window goodput/loss calculations and eight paired mean/CI comparisons matched. Archived rounded Student-t critical values were retained (2.2010 for twelve seeds; 2.5706 for six) rather than silently changing reported arithmetic.
- PPO mean goodput: **5.9217426285 Mbps**; nominal-cost OSPF: **3.9459536776 Mbps**. PPO-minus-OSPF paired mean: **1.9757889509 Mbps**, 95% interval **[0.6639664156, 3.2876114862]**. RTT difference: **−78.9355625 ms**, interval **[−139.9910714, −17.8800536]**. Advantage concentrated in path-0 impairment; no proactive conclusion follows.
- Research papers checked using original accessible texts and bibliographic metadata; official RFC, UML, African Union, Scrum/Kanban, PPO and Juniper material checked. ISO checks established official metadata, not full purchased-standard conformance. Cisco/Arista fetch restrictions and repository access uncertainty remain explicitly unresolved.
- No new model training, network experiment, participant study or application test campaign was performed for this document revision. Existing test results are attributed to their retained records.

## Separate assistance/provenance record

This supporting record is outside the academic report, in accordance with the student's explicit instruction removing preparation/AI commentary from the ODT/PDF. It does not assert that assistance was absent or that the university has accepted a separate declaration.

- **Tool/model:** OpenCode coding-agent harness; disclosed model `github-copilot/gpt-6-astra` (gpt-6-astra). The endpoint identifies GitHub Copilot; no further backend-provider identity was independently established.
- **Requested work:** audit/revise the existing report against the supplied course guide; improve section quality and APA references; give a strict section-by-section assessment; distinguish real evidence gaps. After context compaction, the user instructed continuation of known next steps.
- **Assistance retained:** revised academic prose, actual-results abstract, dataset/training detail, traceability links, Chapter 6 synthesis, selected bibliography corrections, automatic captions/indices, evidence-derived Figure 5.1 and this review. The agent generated these edits; student authorship understanding and approval are not asserted.
- **Checking performed:** course/template/examiner comparison, original-source checks with stated access limits, repository evidence inspection, raw digest and numerical checks, citation/reference matching, XML/style/caption validation, LibreOffice export, PDF destination/bounds checks and visual page review.
- **Revision history:** source ODT/PDF backed up in temporary storage before editing. Candidate iterations corrected caption bookmark-tail duplication, restored omitted table-index styles, and verified blank-page export behaviour. Existing report images and source experiments were preserved.
- **Responsibility and review:** the student must verify factual personal statements, understand and defend the methods/results, decide submission scope with the supervisor, and satisfy applicable disclosure requirements. No student verification, supervisor endorsement, institutional permission or detector outcome is claimed.
