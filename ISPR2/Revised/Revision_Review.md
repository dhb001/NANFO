# NANFO proposal revision review

**Student:** Dhruvin Hitesh Bhudia, 169646  
**Review date:** 17 September 2026  
**Assessment baseline:** `../DhruvinBhudia_169646_MrTiberiusTabulu-5.pdf`  
**Guide:** `../ICS Project II Proposal Guide 2026_V1.docx`  
**Assessment outcome:** 31.5/40; minor corrections indicated.

## Main findings

The current ODT already revised the abstract, background and problem statement, but still contained a duplicated first/second objective. Its second research question consequently had no corresponding development objective. Much of Chapter Two retained the earlier claims, and several references did not support the described systems. Chapter Three described a continuous-action, Ryu-embedded model and MySQL schema that no longer matched the implementation.

The root and `ISPR2` source ODT files were byte-identical when reviewed:

`e61b2ecd5177b4c06e5f226464b714fe2e8e3248327d17efd3dc55c07803e560`

The revised proposal keeps the assessed project title, student details, declaration and acknowledgment. It preserves the conceptual-framework image and the five original explanatory paragraphs, then adds the interpretation necessary for the current implementation. The original schedule remains the planning baseline. Changes to previously full-scoring methodology content are limited to application-consistency corrections, supporting citations and the design artefacts required by the supplied template.

## Marking-scheme response

| Criterion | Assessed score | Revision and rationale |
| --- | ---: | --- |
| Title | 2/2 | Assessed title and identity retained. |
| Abstract | 2/3 | Rewritten as a 183-word paragraph covering problem, gap, objectives, method, evaluation and expected contribution. |
| Contents and lists | 2/2 | Automatic contents, figure, table and equation indices regenerated after changes; obsolete page references replaced. |
| Background | 1.5/2 | Clear progression from education context to congestion, OSPF, SDN, learning, stability and the project. Added directly relevant sources and removed unsupported claims about the live university network. |
| Problem statement | 2.5/4 | Three paragraphs identify the operational problem, evidence-based gap and bounded proposed response. Claims about existing research are linked to specific sources. |
| Objectives | 2/4 | Four concise, distinct objectives with outputs and September/November/December milestones. The duplicated objective is corrected. |
| Relevant literature | 1/2 | Three commercial systems and four research implementations critically reviewed; direct relevance to congestion orchestration explained. |
| Use of literature | 1.5/2 | Distinguishes vendor functionality, learned performance prediction, routing algorithms and measured evaluation. Corrects misleading paper descriptions and vendor claims. |
| Adequacy of literature | 1/2 | Seven named systems/implementations, comparative table, integration synthesis and evaluation synthesis. Nineteen references support the final text. |
| Conceptual framework | 2/2 | Original image and five explanatory paragraphs retained; added variable mapping and a factual implementation interpretation. |
| Methodology selection | 2/2 | Experimental quantitative approach and Hybrid Agile retained; Scrum adaptation and supporting reference clarified. |
| Methodology diagram | 1.5/2 | Redrawn five-stage lifecycle; explanation covers inputs, outputs, feedback, validation, frozen testing and documentation. Incorrect figure/table cross-references removed. |
| Logical project approach | 2/2 | Pipeline retained, with factual corrections for synthetic data, discrete PPO, separate runtimes and matched baselines. Remaining evaluation is explicitly planned. |
| Tools and techniques | 2/2 | Existing tool roles updated to current implementation: PostgreSQL/Neo4j/Redis, FastAPI/React, PPO and distinct operator/comparison labs. |
| References | 2/2 | Existing author–date method retained, with alphabetized entries, hanging indents, appropriate italics and DOI/URL links. Bibliographic/content corrections are documented in the source audit. |
| Language | 2/2 | Third-person academic prose retained; exaggerated absolute claims replaced with precise descriptions. |
| Structure and layout | 2.5/3 | Times New Roman, 12-point text, 1.5 spacing, Roman preliminaries, decimal body numbering, captions and repeated table headers. Added separate limitations/delimitations and actual design figures. |

No numerical prediction of the revised mark is made. The examiner must assess the final submission and supporting evidence.

## Objective–question–literature–method alignment

| Order | Objective and matching question | Chapter Two | Chapter Three and evidence |
| --- | --- | --- | --- |
| 1 | Characterize five congestion indicators in three traffic families. How do these indicators vary? | 2.2.1–2.2.4: utilization, queues, delivery metrics and measurement implications. | 3.2.1–3.2.2 and 3.2.4: acquisition, feature contract and scenario profiles. |
| 2 | Compare at least three commercial and three research solutions. How do they meet the requirements, and what limitations remain? | 2.3.1–2.3.4 and Table 2.1: conventional routing, three commercial systems, four research implementations and comparison. | Requirements elicitation and the literature comparison are the observable deliverables. |
| 3 | Integrate PPO, operational safeguards and the administrator interface. How can these be integrated? | 2.4.1: integration and stability requirements; 2.5 synthesizes the framework. | 3.2.3, 3.3, 3.4 and 3.5.5: implemented model, development workflow, architecture and conditional safeguards. |
| 4 | Evaluate against OSPF and non-learning methods. How does performance and stability compare? | 2.4.2: comparable evidence, reproducibility, timing and ablation requirements. | 3.2.4: matched methods, held-out data, sample units, confidence intervals, proactivity and safeguards. |

The sequence is **telemetry → existing solutions → integration → evaluation**, restoring the assessed proposal’s intended flow. The framework follows the gap discussion as required by the proposal guide.

## Verified application changes reflected in the text

| Earlier proposal description | Current description | Repository evidence |
| --- | --- | --- |
| PyTorch agent embedded in Ryu | Separate learning/inference runtime and operator controller | `ai-engine/src/nanfo_routing/ppo.py`, `ai-engine/README.md` |
| Continuous routing weights and traffic split ratios | Categorical PPO selecting two paths; 16-value observation, separate 32-unit actor/critic hidden layers | `ai-engine/src/nanfo_routing/contracts.py`, `ppo.py`, `env.py` |
| Min–max traffic/adjacency input | Fixed logarithmic scaling, RTT availability and previous-action flags | `ai-engine/src/nanfo_routing/env.py` |
| Generic theoretical reward including energy | Implemented delivery, delay, loss, utilization, queue and route-change terms | `ai-engine/src/nanfo_routing/contracts.py`, `env.py` |
| Absolute Lyapunov safety and continuously bounded actor weights | Separate conditional next-step queue-envelope/drift checks and execution restrictions | `backend/app/modules/autonomy/safety.py`, `README.md` |
| Claimed institutional logs and exact university replica | Bounded synthetic campus-style emulation; institutional data not presumed available | `emulation/README.md`, project evidence records |
| MySQL Nodes/Traffic_Logs schema | PostgreSQL UUID-based inventory/telemetry, Neo4j graph, Redis events; module ownership | `backend/app/modules/network/models.py`, `telemetry/models.py`, root `README.md` |
| Broad autonomous routing claims | Qualified archived PPO benchmark distinguished from unclosed integrated autonomy/proactivity gates | `docs/project/ExpandedTraining-ADR014-Outcome.md`, `CurrentSprint.md` |
| Generic dashboard | React/TypeScript operator views, twin, simulation, intents, measured alerts, diagnostics, audit and real reports | `docs/project/OperatorCompletion-ADR018.md`, `ModulesAcceptance-Step13-Step14.md` |
| Dynamic port shutdown and energy savings | Energy estimation only; no physical power-control result | `docs/project/ModulesAcceptance-Step13-Step14.md` |
| Executable plugin capabilities | Metadata registry boundaries | `docs/project/ModulesAcceptance-Step13-Step14.md` |

Repository files were inspected as evidence; the proposal revision did not train a model, actuate the lab or change application source code. Existing application counts/results are historical evidence and are not represented as tests run during this document task.

## Important source corrections

- **Rusek et al. (2019)** models delay/jitter using a GNN. It is not itself the claimed DRL throughput/OSPF experiment.
- **Almasan, Suárez-Varela, et al. (2022)** evaluates optical-demand allocation, where accepted demands cannot be rerouted. The revised review explains that scope.
- **Li et al. (2025)** implements GTSR with multi-agent PPO in OMNeT++; the stated benchmark includes ECMP and learned baselines, not the claimed Mininet/OSPF comparison.
- **Makris et al. (2024)** concerns application-image placement. Its existence was confirmed through arXiv; it does not support the former routing claims. A Crossref 404 for an arXiv DOI is not evidence that an arXiv source is nonexistent.
- The DOI previously attributed to **Tang et al. (2024), Future Generation Computer Systems**, resolves to an attribute-based encryption paper.
- The DOI previously attributed to **Nguyen et al. (2024)** resolves to a paper about lateral movement in Active Directory.
- The DOI previously attributed to **Zhou and Liu (2024), bufferbloat**, resolves to *BeSleep*, about blockchain-enabled small-base-station sleeping strategies.
- The 2024 NGDN source was duplicated under two author lists. Crossref lists **Ruiyu Yang, Qi Tang and Yingya Guo**. The duplicate is not counted as two studies.
- **Cisco Catalyst Center** supports limited third-party visibility. **Arista CloudVision** explicitly supports campus networks and on-premises deployment. Generalized incompatibility and unsupported cost claims were corrected.
- **Juniper Marvis** documentation establishes troubleshooting functionality, subscriptions and permissions. It does not establish loss of local data-plane forwarding during a cloud outage.
- **Navarro-Alarcon et al. (2020)** is retained as a qualified control-theory precedent in robotics, not as a direct proof of network safety.

Every original bibliography entry is preserved in `Original_Reference_Audit.md`, with its revision decision. This preserves source traceability without presenting mismatched or unused entries as supporting evidence in the final proposal.

## Guide interpretation and remaining submission actions

1. **Abstract:** the template requests at least half a page and the assessment imposes a 200-word maximum. The revised 183-word paragraph is rendered with the required 12-point/1.5-spacing format and occupies approximately half a text page.
2. **Dates:** the assessed June 2026 title-page date remains the original proposal date. The revision includes sources and application progress through September 2026. If the institution requires a resubmission date on the cover, it should be updated consistently before submission.
3. **Milestones:** September, November and December 2026 are completion targets derived from the original April–December plan, including verification of already implemented components. They are not invented completion dates or claims of an official deadline change.
4. **Experiments:** twelve new held-out seeds per traffic family and three trained initializations are planned evaluation targets. They have not been performed by this revision. Archived results retain their original sample counts and limitations.
5. **Turnitin:** the old report images remain explicitly historical in Appendix A2. A fresh institutional similarity report is needed for the revised wording. The revision does not invent a similarity percentage or promise an AI-detection outcome.
6. **Signatures:** signature and approval fields require the appropriate student/supervisor action. Existing dates and signatures from the assessed PDF were not inserted into the new approval page.
7. **Local project citations:** Bhudia (2026a, 2026b) are labelled unpublished project records. Copies in `Evidence/` make the implementation claims inspectable; they are not substitutes for independent literature.

## Presentation and language checks

- Third-person wording throughout the newly written academic prose.
- The four questions mirror the four objectives in order and scope.
- Three commercial systems and four research implementations receive substantive comparison.
- Product descriptions are supported by product-specific documentation.
- In-text author–date citations correspond to bibliography entries; two different Almasan author groups are disambiguated by additional surnames.
- Proposed, modelled, measured and completed work are explicitly distinguished.
- Five numbered equations match the implementation rather than retaining obsolete continuous-time guarantees.
- The conceptual-framework raster is preserved unchanged; new supporting diagrams are explicitly author-created schematics, not vendor screenshots or measured interface captures.
- Automated index destinations, PDF text bounds and fonts were checked; detailed results are in `Validation_Summary.json`.

The PDF is the pagination reference. The editable ODT and DOCX contain the same revision; pagination can change if the DOCX is opened with a different word-processing engine or font configuration.
