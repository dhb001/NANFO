# Diagram preparation and verification record

Date: 18 September 2026. This supporting record is separate from the academic report.

## Tools and retained outputs

An AI assistant accessed through OpenCode prepared the diagram specifications, XML-generation code and accompanying Chapter 4 prose. A specific underlying model identifier and provider were not disclosed in the session. The diagrams were constructed as native mxGraph XML and rendered locally with mxGraph 4.2.2, Playwright/Chromium and `rsvg-convert`. LibreOffice integrated them into the existing ODT and refreshed its PDF. The renderer and draw.io were not used as separate generative-AI models.

Retained outputs are the eleven `.drawio` models, the combined eleven-page `.drawio` file, matching SVG/PNG exports, and the figure introductions, captions and interpretations in Chapter 4. Diagram labels and coordinates are preserved exactly in the editable XML. No private observations, credentials or personal records were uploaded to a diagram service.

## User's operative request (verbatim)

> now make a file for drawio files for the images for chapter 4 and make those files/images make sure to make it simple black and white and where nessesary can use icons and images and insert them in the document where nessesary and make sure that those diagrams and images you make are all following the rules of that like use dotted where it is supose to and arrow where nessesary and make sure that the content is sufficoent and can read clearly in the doc and fits and also make sure to research the official rules and how to make those diagrams online also to ensure they follow the proper structure format and the rules like ieee diagrams and the attached text which is the main and first and foremost should follow those insert them accourdingly to their right places in the obt doc

The request was followed by the course's Chapter 4 diagram guidance and classroom exercise. Its applicable modelling rules are recorded in `docs/standards/AcademicDocumentationGuide.md`: paradigm-based selection; external actors and system boundary; correct use of UML relationships; logical schemas with explicit key/cardinality meanings; editable sources; and narrative–diagram–caption–interpretation presentation. The retained models describe NANFO. They do not represent a student's manual-first classroom submission or a comparison of two separately used AI products.

## Refinements and checks

1. Researched the OMG normative specification, IEEE Author Center guidance and official draw.io documentation before finalising notation.
2. Inspected Chapter 4 and the Identity, Organization, Network, Telemetry, Intent and Autonomy models; checked override reconciliation, frontend contracts and deployment Compose files. Confirmed IntentExecution's unique `intent_id`, within-module foreign keys, logical cross-module identifiers and the optional lab's file-mount permissions.
3. Built eleven focused models. Decoded the native XML locally; prefixed element IDs after discovering that an unprefixed `keys` ID conflicted with the renderer's object lookup.
4. Reviewed all initial images. Reflowed the invalid-observation label, separated use-case connections, extended the include arrow's dash run, clarified restoration guards, added activity-final nodes, and routed the worker/file path around the data-store box. Used a deployment block view rather than incorrectly labelling mounted files as an execution environment.
5. Inserted each figure in its relevant subsection and added requirement-linked introductions and interpretations. Removed the outdated statement that Chapter 4 diagrams were still deferred. Added the primary OMG reference to the shared bibliography.
6. Corrected LibreOffice's export option typing after the first PDF reduced images to 300 dpi. The final PDF retains the 4,200-pixel images at approximately 737 dpi.
7. Checked native decoding, labels, monochrome styling, page fit, caption/lead placement, source-to-embedded-image correspondence, chapter-text preservation, original-image identity and all 156 index destinations. Inspected all final figure pages, with additional inspection after notation refinements.

These are preparation and technical-verification records. Student review, understanding of each retained model and supervisor approval have not been asserted.

## Critical-review revision requested by the student

The student reported overly simple diagrams, missing arrow stems, overlapping lines and text backgrounds cutting nearby strokes, and asked for a full image review before reinsertion. The student also asked whether architecture and class views existed and requested missing views only where needed.

The review confirmed that architecture existed as Figure 4.5, while the two class-style logical schemas did not supply a behavioural software-class view. The architecture was expanded and a single code-derived class view was added immediately after it. Later figures were renumbered. The class view uses `LabPlan`, `PendingLabCommand`, `LabCommand`, `LabResult`, `Mailbox` and `ExecutionWorker`, checked against their source definitions.

The earlier bounds-only review did not catch masking by white label rectangles. This revision made free-standing label backgrounds transparent, checked actual rendered text rectangles against connector segments and shape boundaries, and inspected all twelve images before updating the ODT. Refinements also addressed state compartments, permission-guarded sequence behaviour, result semantics, role inheritance and landscape layout. Body text and original images outside Chapter 4 were checked for preservation.

The final PDF has 125 pages. Twelve diagram leads and captions share their image pages; the architecture and software-class views occupy printed pages 54 and 55. All 157 contents/list destinations were verified. The final geometry checks report zero text/connector, unrelated-box, shape-overflow or diamond-label defects. Intentional stick-figure joints and sequence lifeline/message intersections remain normal notation. These checks support the recorded review; they are not a guarantee of perfection or a claim of supervisor approval.
