# Chapter 4 diagrams

Open **[NANFO_Chapter_4_All_Diagrams.drawio](NANFO_Chapter_4_All_Diagrams.drawio)** in draw.io/diagrams.net. Its twelve named pages contain the complete editable set. Each figure is also available separately as native `.drawio`, vector `.svg` and high-resolution `.png` files.

**Architecture:** Figure 4.5, printed page **54** / PDF page **67**.  
**Software classes:** Figure 4.6, printed page **55** / PDF page **68**.  
Both appear under **4.4.1 System Architecture and Class Design**, on landscape pages. The separate logical schemas are Figures 4.7–4.8.

The figures are inserted in the existing [working ODT](../NANFO_Chapters_1_3_Reviewed.odt) and [matching PDF](../NANFO_Chapters_1_3_Reviewed.pdf). Captions and narrative belong to the report; the exported images contain the diagrams and necessary notation keys.

## Placement and purpose

| Figure | Editable source | Section | Main requirement links |
|---|---|---|---|
| 4.1 | [Application actors and use cases](Figure_4_01_Use_Cases.drawio) | 4.3.1 | FR-01–FR-11; NFR-01 |
| 4.2 | [Observation validation and assessment](Figure_4_02_Telemetry_Activity.drawio) | 4.3.2 | FR-03–FR-05; DR-01–DR-03; NFR-02–NFR-03 |
| 4.3 | [Manual approval and execution](Figure_4_03_Manual_Execution_Activity.drawio) | 4.3.3 | FR-07–FR-09; IR-05 |
| 4.4 | [Override restoration and guarded return](Figure_4_04_Override_State_Machine.drawio) | 4.3.4 | FR-09; NFR-05, NFR-07 |
| 4.5 | [System architecture and module integration](Figure_4_05_Component_Architecture.drawio) | 4.4.1 | NFR-05, NFR-10; IR-01–IR-05 |
| 4.6 | [Command execution classes](Figure_4_06_Execution_Class_Design.drawio) | 4.4.1 | FR-07–FR-09; IR-05 |
| 4.7 | [Identity, resources and observations](Figure_4_07_Resource_Logical_Schema.drawio) | 4.4.2 | FR-02–FR-04; DR-01; NFR-02 |
| 4.8 | [Execution, publication and control records](Figure_4_08_Execution_Logical_Schema.drawio) | 4.4.2 | FR-07–FR-09, FR-12; NFR-02, NFR-10 |
| 4.9 | [Realtime reconnect sequence](Figure_4_09_Reconnect_Sequence.drawio) | 4.4.3 | IR-01–IR-02; NFR-01–NFR-03 |
| 4.10 | [Model inference and admission safeguards](Figure_4_10_Model_and_Safeguards.drawio) | 4.4.4 | FR-10, FR-12; NFR-04, NFR-07; IR-04 |
| 4.11 | [Operator evidence-view wireframe](Figure_4_11_Operator_Wireframe.drawio) | 4.4.5 | NFR-01, NFR-03, NFR-06; IR-01 |
| 4.12 | [Deployment and lab boundaries](Figure_4_12_Deployment_Boundaries.drawio) | 4.4.6 | IR-03, IR-05; NFR-05, NFR-11 |

## Notation and print rules

The student's Strathmore course guide is the primary authority. UML semantics follow OMG UML 2.5.1; IEEE guidance informs print clarity, fonts and image resolution. IEEE journal column widths do not replace the course's report-page layout.

- **Use cases:** actors remain outside the application boundary; solid undirected lines denote participation. A hollow-triangle generalization points from the authorized operator to the generic observing responsibility. The dashed open-arrow `«include»` relationship points from the including case to the required checks. Authentication is a protected-task precondition and its own use case.
- **Activities:** rounded actions, decision diamonds, bracketed guards, solid open-arrow control flows, initial dots and activity-final bullseyes.
- **States:** solid directed transitions connect actual override state names. Unverified restoration retains `restoring`; mode return has its own checks. The enrollment precondition is explanatory text, not a guard on the initial transition.
- **Components:** dashed open arrows point from the using component to the dependency. Grouped modules summarize responsibilities within the monolith.
- **Software classes:** separate name, attribute and operation compartments; `+` for public members; solid hollow-triangle inheritance; numerical association multiplicities; dashed use/type dependencies. Selected classes and signatures were checked against `backend/app/modules/intent/lab.py` and `worker.py`.
- **Logical schema:** UML class compartments, solid associations with numerical multiplicities, and dashed reference dependencies. `PK`, `FK`, `REF` and `UQ` are explicitly defined schema annotations. No crow's-foot or IDEF1X identifying-line convention is implied. Within-module foreign keys and cross-module logical references remain distinct. Intent-to-execution multiplicity is **1 to 0..1**.
- **Sequence:** dashed lifelines; solid open-arrow asynchronous messages; solid filled-arrow synchronous calls; dashed replies; an activation bar for the REST operation. Socket acknowledgement is an asynchronous protocol message, not a synchronous return. The `opt [scope permitted]` fragment guards the complete successful reconciliation branch.
- **Specialised views:** the model and deployment block diagrams explain their connector meanings; the wireframe is an unpopulated design view.
- **Print:** black strokes and text on white, with consistent Times New Roman labels. Portrait figures use 5.70 inches / **10.94 pt** labels / **737 dpi**. The two landscape figures use 8.40 inches / **10.75 pt** labels / **750 dpi**. SVG exports preserve vector shapes and text. Body prose remains 12 pt with 1.5 spacing.

## Official research sources

Accessed 18 September 2026. The dated primary UML specification was added to the report's shared APA bibliography. The other links document preparation guidance.

1. **Object Management Group (2017), UML 2.5.1:** [official specification metadata](https://www.omg.org/spec/UML/2.5.1/About-UML), [normative PDF](https://www.omg.org/spec/UML/2.5.1/PDF). Relevant clauses: 7.7 dependencies; 9.2 classifiers/associations; 11.6 components; 14 state machines; 15 activities; 17 interactions, particularly 17.4.4 message notation; 18 use cases.
2. **IEEE Author Center:** [Improve Your Graphics](https://conferences.ieeeauthorcenter.ieee.org/write-your-paper/improve-your-graphics/) — consistent fonts, approximately 9–10 pt at final size, legible monochrome distinctions and suitable formats.
3. **IEEE Author Center:** [Resolution and Size](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/resolution-and-size/) — black-and-white line art above 600 dpi.
4. **draw.io (21 January 2021):** [UML 2.5 shape library](https://www.drawio.com/blog/uml-2-5/) — supported structural and behavioural diagram families.
5. **draw.io:** [Sequence diagrams](https://www.drawio.com/docs/diagram-types/uml/sequence-diagrams/) — lifelines, activations, messages and guards.
6. **draw.io:** [Crow's-foot notation](https://www.drawio.com/docs/tutorials/crows-foot-notation/) — distinguishes ER cardinality symbols from UML numerical multiplicities. The delivered logical schemas use the latter consistently.

## Verification and editing

Native models were decoded and rendered locally with mxGraph 4.2.2. SVGs were rasterized with `rsvg-convert`; LibreOffice refreshed the ODT's contents and figure/table/equation lists and exported the PDF with image downsampling disabled.

The critical-review revision identified oversized white label rectangles as the cause of cut connector stems. Free-standing labels now have transparent backgrounds and are placed clear of strokes. Checks cover text–connector clearance, text touching unrelated boxes, text outside shapes, diamond-label containment and page boundaries. All twelve source images were visually inspected before integration, followed by inspection of the rendered document pages.

Validation confirmed twelve Chapter 4 figures, captions and leads on their respective figure pages, sequential page numbering, **157 correct index destinations**, preserved text in Chapters 1–3 and 5, and byte-identical original images. `Verification.json` records final dimensions, pages and checks. The architecture and software-class figure interpretations also fit on their respective landscape pages.

### Critical-review changes

| View | Correction or justified additional detail |
|---|---|
| Use cases | Added report generation and restoration; replaced redundant crossing associations with justified actor generalization. |
| Telemetry | Added event identity, stored provenance and stale-data handling; reflowed labels within the action boxes. |
| Execution | Clarified verified completion/non-mutation versus an unresolved outcome; retained explicit final nodes. |
| Override states | Added internal-activity compartments, separated retry and restoration paths, and moved arrows away from compartment separators. |
| Architecture | Expanded module ownership, workers, laboratory integration and data-store responsibilities; routed dependencies without crossings. |
| Software classes | Added the previously absent behavioural class view using actual plan, command, result, mailbox and worker definitions. |
| Logical schemas | Retained correct keys/cardinalities; removed label masks and clarified logical-reference and uniqueness annotations. |
| Reconnection | Kept messages and guards between lifelines; added permission checking and a guarded successful interaction fragment. |
| Model safeguards | Separated model/calibration qualification from current execution authority and stop-state admission. |
| Wireframe | Added evidence-inspection controls and explicit loading, empty, error and stale-state guidance. |
| Deployment | Moved the entry path away from the host title; named worker responsibilities and clarified file-reader/writer roles. |

After editing a diagram, export that page at its original aspect ratio. Retain 4,200 pixels of width for portrait PNGs and 6,300 for the two landscape PNGs, replace the corresponding ODT image, update the figure list and re-export the PDF without image downsampling. Native `.drawio` sources are the editable authority; changing a PNG alone does not update them.
