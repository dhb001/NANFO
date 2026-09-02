# Strathmore Demo - Two-Phase Non-Hallucination Prompt

Last updated: 2026-08-20
Audience: Operator preparing a high-impact demo for Strathmore University context

## Why this approach works

You asked for something very detailed but still easy enough to execute.
This document gives a two-phase prompt you can paste into a coding agent so it:
- stays grounded in real NANFO files,
- avoids inventing APIs/tools,
- builds a realistic Strathmore-focused demo dataset,
- provides full manual navigation and explanation,
- runs tests and reports evidence.

It is intentionally scoped so you can show many buildings/floors/devices without needing a perfect 1:1 physical twin on day one.

## Important migration note (php artisan migrate equivalent)

This repository does not use PHP and does not use a Node ORM migration tool.
The actual migration command here is Alembic on the Python backend:
- from backend folder: poetry run alembic -c alembic/alembic.ini upgrade head

Think of that as the functional equivalent of artisan migrate for this project.
Do not use Prisma/Knex/TypeORM commands unless those tools are first added to the repo.

---

## Copy-Paste Prompt (Two Phases)

Use the full prompt below with your coding agent.

You are working inside the NANFO repository. Execute this in two phases. Do not skip phase boundaries.

Global hard rules:
1. No hallucinations. Only use routes, payload shapes, scripts, and commands that exist in this repository.
2. Before changing anything, read and cite relevant files.
3. Use existing API envelope and contracts exactly as documented.
4. If something is missing from repo contracts, mark it as a gap and propose the smallest safe alternative.
5. No destructive git commands.
6. Keep all changes scoped to Strathmore demo preparation and documentation unless explicitly needed.

Context loading requirements (must do first):
1. Read AGENTS.md and follow instruction precedence.
2. Read these source-of-truth files before planning:
- README.md
- docs/project/CurrentSprint.md
- docs/project/NANFO-User-Manual-and-Full-Testing-Guide.md
- docs/architecture/Frontend.md
- docs/architecture/DigitalTwin.md
- docs/api/WebSocket.md
- docs/project/DigitalTwinScenarioValidationRunbook.md
- backend/app/api/v1/networks.py
- backend/app/api/v1/topology.py
- backend/app/api/v1/simulation.py
- backend/app/api/v1/intents.py
- frontend/src/app/App.tsx
- frontend/src/shared/ui/AppShell.tsx
- frontend/src/shared/types/network.ts
- frontend/src/shared/types/simulation.ts
- frontend/src/shared/types/intent.ts
3. Inspect file inventory with rg --files and summarize relevant files used for this task.
4. State explicit assumptions and unknowns before implementation.

Primary objective:
Prepare a Strathmore University demo package that is highly detailed for presentation but practical to execute quickly.
The digital twin must be presented as one centralized whole-campus operations surface (single campus context), not as isolated building-by-building views.
Target context includes at least these named buildings as zones inside the same centralized campus model:
- Strathmore Business School
- Strathmore Student Center
- Main Library
- Management Sciences Building
- Additional placeholder buildings as needed (Building E, Building F, etc.)

You must deliver a realistic campus model strategy with many floors and many devices without requiring full photorealistic 3D modeling.
All building/floor segments must roll up into one campus-level control plane narrative (single source of truth for operations, telemetry, alerts, simulation, and intent actions).

====================
PHASE 1 - Design and Demo Blueprint (Detailed + Easy)
====================

Goal:
Produce a complete design blueprint and operator runbook for a Strathmore-themed demo that balances detail and execution speed.

Required outputs for Phase 1:
1. A single master markdown document in docs/project containing:
- Demo objective and scope
- Non-goals
- Data model mapping to existing NANFO contracts
- Centralized campus control-plane model (how all buildings appear and operate in one twin)
- Building/floor/device taxonomy
- Telemetry and alert simulation plan
- Digital twin strategy
- Operator navigation walkthrough
- Validation checklist
- Risks and fallback plan

2. Centralized campus modeling strategy (must be detailed but easy):
- Use a Level of Detail (LOD) plan:
  - LOD-0 campus-wide unified scene and building footprints in one view
  - LOD-1 floor-level zoning for core buildings within that same scene
  - LOD-2 device-level detail only for selected showcase floors
- Keep the 80/20 rule: deep detail on key academic/operations zones, lighter detail elsewhere, while preserving one centralized campus experience.

3. Define a Strathmore device blueprint by floor zone:
- Core router
- Distribution/access switches
- Wi-Fi APs
- Firewalls
- Servers
- UPS/power/environment monitors
- CCTV and access-control gateways (as networked endpoints where relevant)
- Printers/lab endpoints (where relevant)

4. Use NANFO-native identity scheme for spatial mapping:
- spatial_ref_id format: campus/building/floor/zone/device
- Example convention only; do not invent unsupported backend fields.

5. ONLY IF NOT ALREADY PRESENT IN THE REPO: design and implement a device-grouping capability so operators can target groups instead of individual devices.
- First, prove whether grouping already exists by citing files/routes/types/tests.
- If it exists, reuse it and document exactly how to use it.
- If it does not exist, add the minimum safe capability with clear boundaries and tests.
- Grouping must support campus-wide operational views (not separate twins) using practical enterprise controller patterns:
  - site hierarchy groups (campus/building/floor)
  - functional groups (core, distribution, access, wireless, security, server)
  - operational groups (critical services, student services, lab segments)
- Prefer existing fields and contracts first (for example tags/metadata-like patterns if already present).
- Do not add speculative endpoints; if an API addition is required, keep it minimal, explicit, and fully documented.
- Ensure group-level actions are governance-safe and traceable (audit visibility, intent/simulation safety alignment).

6. Define the minimum viable but impressive demo dataset:
- Number of buildings
- Floors per building
- Devices per floor by category
- Total counts and complexity band
- Explain why this is feasible in limited prep time.

7. Define operator story flow for presentation:
- Overview -> Tenancy -> Topology Analysis -> Telemetry -> Reliability -> Digital Twin -> Simulation -> Intent -> Audit -> Reports
- Include keyboard shortcuts/hints where available.
- Include a campus-wide group operation moment where one action targets a selected group and its impact is shown across the centralized twin.

8. Define a no-hallucination statement in the document:
- Every endpoint, field, and behavior must be traced to repository files.
- Include a traceability table with file references.

Phase 1 acceptance criteria:
- Blueprint is complete and internally consistent.
- All required fields align to existing type/router contracts.
- No undocumented endpoint/channel additions.
- Clear list of what is real now vs demo placeholder assumptions.

====================
PHASE 2 - Implementation, Validation, and Test Evidence
====================

Goal:
Execute the blueprint using existing NANFO surfaces, produce runnable data setup guidance, and verify with tests.

Required actions for Phase 2:
1. Environment and infra steps (document exact commands):
- Start infra: ./scripts/dev-start.sh
- Backend install and migrations:
  - cd backend
  - poetry install
  - poetry run alembic -c alembic/alembic.ini upgrade head
- Start backend:
  - poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
- Frontend:
  - cd frontend
  - npm install
  - npm run dev -- --host 0.0.0.0 --port 5173

2. Bootstrap/login prerequisites:
- If needed, follow README bootstrap-user flow.
- Confirm login and /auth/me before continuing.

3. Data creation workflow (must use existing APIs/contracts):
- Create org, workspace, network
- Add devices with realistic Strathmore naming + location_hint + optional spatial_ref_id so all buildings appear under one campus model
- Validate topology graph visibility
- Validate Digital Twin scene behavior with available realtime deltas
- If grouping exists, create and validate groups from devices for campus-wide operations.
- If grouping does not exist, implement it in the smallest safe slice (backend/frontend/tests/docs), then validate end-to-end.

4. Simulation and intent workflow:
- Start simulation via existing endpoint
- Validate intent then execute intent
- Observe lifecycle effects in centralized Digital Twin and/or related pages
- Record expected behavior and known residual limitations from CurrentSprint

5. Telemetry and alerts workflow:
- Use existing telemetry and alerts pages/endpoints
- Show how to demonstrate congestion/health narratives even if data volume is synthetic/minimal
- Keep claims bounded to current implemented capabilities

6. Full operator manual section in the same master document:
- Exact click-by-click navigation steps
- What to say during each screen in the live demo
- What success looks like
- Common failure symptoms and quick recovery steps

7. Evidence and test execution (run where possible):
- Backend checks:
  - poetry run pytest tests -q
  - poetry run ruff check app tests
- Frontend checks:
  - npm run lint
  - npm run typecheck
  - npm run test
  - npm run test:e2e
  - npm run build
  - npm run perf:bundle
- If any command is too expensive or blocked locally, report exactly why and provide the nearest scoped alternative.

8. Final report at end of Phase 2:
- Summary of files changed
- Test results with pass/fail counts
- Known limitations
- Demo-day run order (15-minute and 30-minute variants)
- Group-capability status: already existed vs newly implemented, plus proof links

Phase 2 acceptance criteria:
- Manual is complete and executable.
- Commands are accurate for this repo.
- Tests/checks are run and reported when possible.
- No fabricated features or contracts.

====================
Strathmore-specific modeling guidance (use this in implementation)
====================

Use this practical template unless real campus data is available.

1. Centralized campus composition tiers (single twin context):
- Tier A (high detail zones inside one campus):
  - Strathmore Business School
  - Main Library
  - Management Sciences Building
- Tier B (medium detail zone):
  - Strathmore Student Center
- Tier C (light detail campus zones):
  - Building E, Building F, Building G

2. Floor strategy example:
- Tier A buildings: 4 to 6 floors each
- Tier B buildings: 3 to 4 floors
- Tier C buildings: 2 floors each

3. Device density strategy example:
- Tier A showcase floor: 18 to 30 devices
- Non-showcase floor: 8 to 15 devices
- Tier C floor: 4 to 8 devices

4. Naming conventions:
- Building code: SBS, LIB, MSB, SSC, BLD-E, BLD-F
- Floor code: F01, F02, F03
- Device hostnames:
  - RTR-SBS-F01-01
  - SW-ACC-LIB-F03-07
  - AP-MSB-F02-12
  - FW-SSC-F01-01

5. spatial_ref_id convention:
- strathmore/<building>/<floor>/<zone>/<device>
- Example:
  - strathmore/sbs/f01/core/rtr-01
  - strathmore/lib/f03/west/ap-12

6. Demo narrative anchors:
- Academic core resilience (Library + SBS)
- Student experience reliability (Student Center wireless)
- Change safety (Simulation before Intent execute)
- Auditability (Intent and simulation lifecycle traces)
- Central command posture: one campus-wide control surface with group-targeted actions

====================
Required quality bar
====================

You must be explicit about:
- What the platform supports now
- What is approximated for demo realism
- What remains roadmap/deferred

Do not claim:
- Full procedural OSM import is production-delivered if it is not in current implementation.
- Features outside existing API/WebSocket contracts.

At the end, produce:
- The final master manual document
- A concise command checklist for demo day
- A test evidence section with exact outputs summarized

---

## Suggested filename for the generated master manual

Use this filename in Phase 1/2 execution:
- docs/project/Strathmore-Demo-Manual-and-Execution-Guide.md

This keeps everything in one place as requested.
