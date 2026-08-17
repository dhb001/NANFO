# One-Shot Prompt: Create Final User Manual + Full Testing Guide (Simple English)

Use this prompt exactly as written in your autonomous coding session.

---

You are writing the **final combined documentation** for NANFO.

Your output must be one single document that combines:
1. A **User Manual** (for non-technical and non-networking users).
2. A **Full Testing Guide** (step-by-step, complete coverage, in correct dependency order).

## Primary Goal
Create a detailed but easy-to-understand guide so that a person with zero networking background can:
- Understand what NANFO does.
- Use all major UI features correctly.
- Test the system end-to-end in the right order.
- Know dependencies (what must be done first before next steps).
- Know expected results and how to troubleshoot failures.

## Writing Style Rules (Mandatory)
- Use very simple English.
- Short sentences.
- Avoid jargon. If jargon is required, explain it in one line.
- Assume the reader is not a networking expert.
- Be explicit. Do not skip steps.
- Use checklists and numbered steps.
- Include examples of values users can type in fields.
- Explain "why this step matters" in plain words.
- Add visuals wherever they improve understanding.

## Visual Requirements (Mandatory)
- Add a visual for each major section where possible.
- Use Mermaid diagrams for:
  - Big picture user journey flow.
  - Dependency chain (A before B).
  - End-to-end master test sequence with stop/go gates.
  - Realtime data flow (UI -> API -> WebSocket updates).
- Add UI screenshots for every major page/workflow if available in repo artifacts.
- For each screenshot, include:
  - A short caption in plain English.
  - Numbered callouts (1, 2, 3...) that match the step text.
  - What the user should click/type in that screen.
- If real screenshots are not available, include clear placeholder markers with exact capture instructions, for example:
  - `[Insert Screenshot: Login page with email/password fields highlighted]`
- Add simple tables or matrices where they reduce text complexity (for dependencies, test coverage, and troubleshooting).
- Prefer visual-first explanation: show the diagram/table first, then explain in simple words.

## Output File to Create
Create and fully populate:
- `docs/project/NANFO-User-Manual-and-Full-Testing-Guide.md`

## Source-of-Truth Inputs to Read First
- `docs/architecture/README.md`
- `docs/architecture/Architecture.md`
- `docs/architecture/Frontend.md`
- `docs/features/Authentication.md`
- `docs/features/Organization.md`
- `docs/features/Telemetry.md`
- `docs/features/Topology.md`
- `docs/features/Simulation.md`
- `docs/features/IntentEngine.md`
- `docs/features/Alerts.md`
- `docs/features/Plugins.md`
- `docs/features/Reporting.md`
- `docs/api/REST.md`
- `docs/api/WebSocket.md`
- `docs/api/EventAPI.md`
- `docs/project/CurrentSprint.md`
- `docs/project/DevelopmentJournal.md`
- Frontend routes/pages/components under `frontend/src/`
- Backend API route files under `backend/app/api/v1/`

## Required Structure (Use This Exact Order)

### 1) What NANFO Is (Simple Explanation)
- Explain the product in plain English.
- Explain who should use it.
- Explain core outcomes: monitoring, topology visibility, simulation, intent execution, alerts, plugins, reporting.
- Add a "1-minute summary" and "5-minute summary".

### 2) Big Picture Flow (Beginner Friendly)
- Show a full journey in plain words:
  - Sign in
  - Select/confirm org/workspace
  - Ingest/observe telemetry
  - View topology
  - Run simulation
  - Validate/execute intent
  - Watch alerts
  - Use plugins
  - Generate reports
- Include a dependency chain table: "You must finish A before B".
- Include a Mermaid journey diagram and a simplified step timeline visual.

### 3) Prerequisites and Dependencies (Complete)
- System prerequisites (runtime/services/tools) in plain words.
- Backend dependencies and what happens if missing.
- Frontend dependencies and what happens if missing.
- External services and connectivity assumptions.
- Data/setup prerequisites.
- Explicit dependency maps such as:
  - "Authentication must work before any protected page can be used."
  - "Telemetry data is needed before meaningful topology/alerts views."
  - "Simulation output depends on available topology/runtime state."
  - "Intent execute depends on validate and permission checks."

### 4) UI Navigation Map (Everything a User Clicks)
- Document the app navigation tree in order.
- For each main menu/page:
  - Purpose of the page.
  - What each visible section means.
  - What each button does.
  - What each input field expects.
  - Example values for each field.
  - Common mistakes and how to fix.
  - Success result and failure result.
- Include a navigation diagram and screenshot callouts per major page.

### 5) Detailed Feature Playbooks (Step-by-Step)
Create full playbooks for each major feature:
- Authentication/Login
- Organization and Workspace management
- Telemetry monitoring
- Topology analysis
- Simulation lifecycle
- Intent validation/execution
- Alerts acknowledge/resolve
- Plugins install/enable/disable
- Reports generate/view

For each playbook, include:
- Preconditions (what must already exist)
- Exact UI path (click-by-click)
- Field-by-field entry guidance
- Expected backend/API behavior (simple summary)
- Expected realtime updates (if any)
- Success checks
- Rollback/cancel steps (if applicable)
- Add a visual walkthrough strip (diagram or screenshot sequence) for each playbook.

### 6) Full Testing Guide (Correct Order, End-to-End)
Provide a complete test plan in strict order:
- Smoke test order (fast confidence).
- Functional test order (feature-by-feature).
- Integration journey tests (cross-feature flows).
- Realtime tests (ws channels and reconnect behavior).
- Negative tests (bad input, unauthorized, missing data).
- Accessibility checks.
- Performance and stability checks.

For every test case, include:
- Test ID
- Purpose (simple)
- Preconditions
- Steps
- Input examples
- Expected result
- Failure clues
- Recovery action
- Pass/Fail checklist
- Add a compact visual test-flow diagram per test block (smoke, functional, integration, realtime, negative).

### 7) Dependency-Driven Master Test Sequence
Provide one master sequence from clean start to full validation.
- Include exact order and stop/go gates.
- Mark blocking dependencies clearly:
  - "If this fails, do not continue to next block."
- Include retest loops after fixes.

### 8) API and Realtime Mapping for Testers (Simple)
- Map each UI journey to related API endpoints.
- Map each UI journey to relevant websocket channels.
- Keep language simple: "When you click X, page calls Y".

### 9) Troubleshooting by Symptom
Create beginner-friendly troubleshooting tables:
- "I cannot log in"
- "Page is empty"
- "No telemetry appears"
- "Simulation never finishes"
- "Intent stuck"
- "Alert action fails"
- "Plugin action denied"
- "Report not generated"
- "Realtime not updating"

Add a decision-tree visual (Mermaid) for troubleshooting entry points.

For each symptom include:
- Most likely causes (ordered)
- Quick checks
- Deep checks
- Fix path
- When to escalate

### 10) Operations Runbook Lite (For Non-Experts)
- Daily checks
- Weekly checks
- Before-release checks
- After-change checks
- Evidence to capture for audit

### 11) Glossary (Plain English)
- Explain all important terms in simple words.
- Include networking terms and NANFO-specific terms.

### 12) Final Readiness Checklist
- One printable final checklist for:
  - User onboarding ready
  - Feature walkthrough ready
  - End-to-end testing ready
  - Regression ready
  - Documentation complete

## Quality Gates For This Documentation Task
Before finalizing, verify:
- Coverage includes all delivered VS features through VS21 context.
- Steps are dependency-ordered and non-ambiguous.
- Non-technical reader can follow without prior networking knowledge.
- UI instructions are specific (fields/buttons/examples).
- Testing sequence is complete and executable end-to-end.

## Final Output Requirements
- Create only one final combined doc at:
  - `docs/project/NANFO-User-Manual-and-Full-Testing-Guide.md`
- Ensure it is detailed, structured, and beginner-friendly.
- Include a table of contents.
- Include section anchors for fast navigation.
- Include visuals embedded directly in the doc using Mermaid and markdown images/placeholders.
- Every major section must contain at least one visual element (diagram, screenshot, or table).

Now execute and produce the document end-to-end.
