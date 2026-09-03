# Strathmore Demo Manual and Execution Guide

## Phase Boundary

This document now contains **Phase 1 (Design Blueprint)** plus **Phase 2 (Implementation, Validation, and Operator Execution Package)** for a Strathmore University demo using current NANFO capabilities only.

Current status:

- Phase 1 blueprint: complete.
- Phase 2 implementation artifacts: complete (dataset prep script, unit tests, command checklist, operator manual sections, evidence log).
- Phase 2 live apply evidence: historical run complete (`/tmp/opencode/strathmore-apply-context.json`, pre-materialization topology snapshot) and refreshed run complete (`/tmp/opencode/strathmore-apply-context-20260902.json`, synthetic topology materialization confirmed with topology re-check `edges=338`).
- Status refresh (2026-09-02): native network-scoped device-group and campus-model-asset persistence endpoints are now available under the Network module (`GET|POST /api/v1/networks/{network_id}/device-groups`, `GET|POST /api/v1/networks/{network_id}/campus/model-assets`).

---

## 1) Demo Objective and Scope

### Objective

Deliver a high-detail but fast-to-execute Strathmore University operations demo where the Digital Twin is presented as **one centralized campus control plane** (single campus context), not separate building twins.

### In-Scope

- One tenancy and one network context representing the campus operations surface.
- Multi-building campus zoning inside the same Digital Twin model using `spatial_ref_id`.
- End-to-end operator narrative across:
  - Overview -> Tenancy -> Topology Analysis -> Telemetry -> Reliability -> Digital Twin -> Simulation -> Intent -> Audit -> Reports.
- Group-targeted operations using existing NANFO contracts only.

### Required Strathmore Buildings (same centralized model)

- Strathmore Business School
- Strathmore Student Center
- Main Library
- Management Sciences Building
- Placeholder buildings: Building E, Building F, Building G

---

## 2) Non-Goals

- No new REST endpoints, no new WebSocket channels, no new event names.
- No schema migrations for Phase 1.
- No photorealistic 3D campus modeling requirement.
- No backend business-logic change for group fan-out execution semantics.
- No departure from canonical API envelope `success/data/meta/errors`.

---

## 3) Loaded Context and Repository Inventory Summary

### Mandatory Source-of-Truth Files Loaded

- `README.md`
- `docs/project/CurrentSprint.md`
- `docs/project/NANFO-User-Manual-and-Full-Testing-Guide.md`
- `docs/architecture/Frontend.md`
- `docs/architecture/DigitalTwin.md`
- `docs/api/WebSocket.md`
- `docs/project/DigitalTwinScenarioValidationRunbook.md`
- `backend/app/api/v1/networks.py`
- `backend/app/api/v1/topology.py`
- `backend/app/api/v1/simulation.py`
- `backend/app/api/v1/intents.py`
- `frontend/src/app/App.tsx`
- `frontend/src/shared/ui/AppShell.tsx`
- `frontend/src/shared/types/network.ts`
- `frontend/src/shared/types/simulation.ts`
- `frontend/src/shared/types/intent.ts`

### Additional Relevant Contracts Read

- `docs/api/API_STANDARD.md`
- `docs/api/EventAPI.md`
- `docs/features/Topology.md`
- `docs/features/Simulation.md`
- `docs/features/IntentEngine.md`
- `docs/features/Telemetry.md`
- `backend/app/modules/network/schemas.py`
- `backend/app/modules/intent/schemas.py`
- `backend/app/modules/simulation/service.py`
- `backend/app/events/consumers/ws_push_consumer.py`
- `frontend/src/features/digitalTwin/TwinPage.tsx`
- `frontend/src/features/digitalTwin/sceneAdapter.ts`
- `frontend/src/shared/lib/hotkeys.ts`

### `rg --files` Inventory Summary (Task-Relevant)

The repository inventory includes all required implementation surfaces for this demo plan:

- Backend API routers under `backend/app/api/v1/` for tenancy, network/device, topology, telemetry, alerts, simulation, intent, reports, and audit.
- Backend event and websocket routing under `backend/app/events/consumers/` and `backend/app/websocket/`.
- Frontend operator routes and feature pages under `frontend/src/features/` and `frontend/src/app/`.
- Frontend contract types under `frontend/src/shared/types/`.
- Existing runbooks and sprint artifacts under `docs/project/`.

---

## 4) Assumptions and Unknowns (Before Implementation)

### Assumptions

1. The campus demo uses one organization, one workspace, and one network as a centralized operational context.
2. Device placement and zoning are represented by existing `spatial_ref_id` and optional `location_hint` fields only.
3. Group-target intent targeting can be encoded inside `intent.scope` because intent request schema accepts structured objects.
4. Digital Twin value is conveyed through existing topology + telemetry + intent/simulation overlays, with optional session-only model import.

### Unknowns / Gaps

1. **Historical note (resolved):** During initial Phase 1 drafting, no explicit device-group contract existed; this is now closed by native network group endpoints (`GET|POST /api/v1/networks/{network_id}/device-groups`).
2. **Historical note (resolved):** During initial Phase 1 drafting, simulation terminal-event producer parity was still open; this is now closed in current sprint tracking and backend implementation.
3. **Historical note (resolved):** During initial Phase 1 drafting, there was no documented backend persistence contract for binary 3D campus assets; this is now closed by network-scoped campus model asset persistence (`GET|POST /api/v1/networks/{network_id}/campus/model-assets`).
4. No documented bulk device-create endpoint exists; high-volume dataset creation must use repeated existing device-create calls.

---

## 5) Data Model Mapping to Existing NANFO Contracts

| Demo Layer | Existing Contract Shape | Source |
| --- | --- | --- |
| API envelope | `success`, `data`, `meta`, `errors` | `docs/api/API_STANDARD.md:8` |
| Organization | `org_id`, `name`, `slug`, `created_at` | `backend/app/modules/organization/schemas.py:40`, `frontend/src/shared/types/organization.ts:1` |
| Workspace | `workspace_id`, `org_id`, `name`, `description` | `backend/app/modules/organization/schemas.py:66`, `frontend/src/shared/types/organization.ts:13` |
| Network | `network_id`, `workspace_id`, `name`, `description`, `cidr` | `backend/app/modules/network/schemas.py:23`, `frontend/src/shared/types/network.ts:1` |
| Device | `device_id`, `hostname`, `device_type`, `location_hint`, `spatial_ref_id`, `status` | `backend/app/modules/network/schemas.py:57`, `frontend/src/shared/types/network.ts:17` |
| Topology graph | `nodes[]`, `edges[]` with node `spatial_ref_id` | `backend/app/api/v1/topology.py:118`, `frontend/src/shared/types/network.ts:53` |
| Telemetry | metric records with `tags` | `backend/app/modules/telemetry/schemas.py:11`, `frontend/src/shared/types/telemetry.ts:1` |
| Alerts | lifecycle records + `queue_status` action responses | `backend/app/modules/alert/schemas.py:12`, `frontend/src/shared/types/alerts.ts:1` |
| Simulation | handoff/detail/compare fields (`simulation_id`, `state`, `risk_gate`, `validation`) | `backend/app/api/v1/simulation.py:141`, `frontend/src/shared/types/simulation.ts:10` |
| Intent | validate/execute/detail with `intent`, `validation`, `confidence`, provenance | `backend/app/api/v1/intents.py:36`, `backend/app/modules/intent/schemas.py:45`, `frontend/src/shared/types/intent.ts:34` |
| Realtime channels | `/ws/topology`, `/ws/telemetry`, `/ws/alerts`, `/ws/digital-twin` | `docs/api/WebSocket.md:17`, `backend/app/main.py:379` |
| Twin scene mapping | deterministic placement from `spatial_ref_id`; overlay from scene deltas | `frontend/src/features/digitalTwin/sceneAdapter.ts:198`, `frontend/src/features/digitalTwin/TwinPage.tsx:163` |

---

## 6) Centralized Campus Control-Plane Model

### Single Campus Context Pattern

Use one campus operations context:

- Organization: `Strathmore University`
- Workspace: `Main Campus Operations`
- Network: `strathmore-main-campus`

All buildings/floors/devices are represented inside this single network context using `spatial_ref_id` paths. This guarantees one operational source of truth for topology, telemetry, alerts, simulation, intent, audit, and reports.

### Why This Aligns with Current NANFO

- Topology graph and Digital Twin both consume the same device IDs and node structures.
- Twin scene placement can deterministically parse hierarchical spatial paths.
- Simulation/intent lifecycle overlays already fan out to `/ws/digital-twin` as scene-object deltas.

---

## 7) Building / Floor / Device Taxonomy

### Building Taxonomy (Campus Zones)

| Building | Code | Floors | LOD Emphasis |
| --- | --- | --- | --- |
| Strathmore Business School | `sbs` | 6 | High (core showcase) |
| Main Library | `lib` | 6 | High (core showcase) |
| Management Sciences Building | `msb` | 5 | High (core showcase) |
| Strathmore Student Center | `ssc` | 4 | Medium/High |
| Building E | `bld-e` | 2 | Light |
| Building F | `bld-f` | 2 | Light |
| Building G | `bld-g` | 2 | Light |

### Floor-Zone Taxonomy

- `core` (MDF/NOC)
- `distribution` (IDF / aggregation)
- `wireless` (high-density AP zones)
- `security` (CCTV/access-control gateways)
- `lab` (teaching/lab endpoint blocks)
- `services` (student/operations shared services)

### Spatial Identity Convention (Contract-Safe)

Use existing `spatial_ref_id` only, with this convention:

`campus/building/floor/zone/device`

Examples:

- `strathmore/sbs/f01/core/rtr-sbs-f01-01`
- `strathmore/ssc/f02/wireless/ap-ssc-f02-12`
- `strathmore/lib/f03/services/sw-acc-lib-f03-04`
- `strathmore/msb/f04/lab/prn-msb-f04-02`

No unsupported backend fields are introduced.

---

## 8) Centralized LOD Strategy (80/20)

### LOD-0 (Campus-Wide Unified Scene)

- One scene containing all 7 building footprints and all topology nodes in one camera context.
- Distant zones remain lightweight in geometry/detail but stay addressable and visible.

### LOD-1 (Floor-Level Zoning in Same Scene)

- Core buildings (`sbs`, `lib`, `msb`, `ssc`) expose floor-aware zoning through spatial path and inspector context.
- Remaining buildings stay simplified but are still part of the same graph and operations surface.

### LOD-2 (Selective Deep Detail)

- Showcase floors only (8 floors) get dense device granularity and richer operator narrative.
- Non-showcase floors keep practical counts for fast dataset creation.

### 80/20 Execution Rule

- 20% floors (showcase set) carry most visual and operational detail.
- 80% of campus still present in same control plane with lighter fidelity.

---

## 9) Strathmore Device Blueprint by Floor Zone

### Category Set (Required)

- Core routers
- Distribution/access switches
- Wi-Fi APs
- Firewalls
- Servers
- UPS/power/environment monitors
- CCTV/access-control gateways
- Printers/lab endpoints

### Floor Template Types

| Floor Type | Typical Use | Device Mix |
| --- | --- | --- |
| MDF Showcase (2 floors) | Campus backbone resilience demo | 1 core router, 1 firewall, 2 distribution, 4 access, 6 AP, 3 servers, 2 UPS, 2 security gateways, 2 printer/lab |
| Academic Showcase (6 floors) | Student experience and learning-critical zones | 1 distribution, 4 access, 8 AP, 1 server, 1 UPS, 2 security gateways, 2 printer/lab |
| Standard Core (13 floors) | Normal operations floors | 1 distribution, 2 access, 4 AP, 1 server, 1 UPS, 1 security gateway, 1 printer/lab |
| Light Placeholder (6 floors) | Peripheral campus zones | 1 access, 3 AP, 1 UPS, 1 printer/lab |

---

## 10) Device Grouping Capability Assessment (Required)

### Evidence Review: Current Native Grouping Status

Current repository contracts now include an explicit native network-scoped device-group primitive:

- Network routes include native group lifecycle endpoints (`backend/app/api/v1/networks.py:277`, `backend/app/api/v1/networks.py:300`).
- Network schemas include group request/response contracts (`backend/app/modules/network/schemas.py:291`, `backend/app/modules/network/schemas.py:378`).
- Frontend network contracts include group types and payloads (`frontend/src/shared/types/network.ts:181`, `frontend/src/shared/types/network.ts:201`).
- Frontend network API/hook surfaces include list/upsert group support (`frontend/src/features/networks/api.ts:117`, `frontend/src/features/networks/hooks.ts:170`).

### Historical Phase 1 Gap (Now Closed)

At original Phase 1 authoring time, native groups were not yet implemented; this document used a scope-selector fallback. That fallback remains contract-safe and backward-compatible.

### Contract-Safe Grouping Patterns (Still Valid)

Use scope selectors inside `intent.scope` for targeting semantics (with or without persisted native group definitions):

1. **Site hierarchy groups** from `spatial_ref_id` prefixes:
   - Campus: `strathmore/*`
   - Building: `strathmore/sbs/*`
   - Floor: `strathmore/sbs/f02/*`
2. **Functional groups** from `device_type` naming policy:
   - `core`, `distribution`, `access`, `wireless`, `security`, `server`
3. **Operational groups** encoded in `intent.scope` selectors and optional `location_hint` text.

### Group-Target Action Pattern (Existing Intent Contract)

Use current intent validate/execute endpoints with scope object selectors:

```json
{
  "workspace_id": "<workspace_uuid>",
  "network_id": "<network_uuid>",
  "intent": {
    "action": "optimize_wireless_capacity",
    "scope": {
      "target": "group",
      "site_prefix": "strathmore/ssc/f02",
      "functional_group": "wireless",
      "operational_group": "student_services"
    },
    "constraints": {
      "max_downtime": 0,
      "simulation_required": true
    }
  }
}
```

This remains contract-valid because intent `scope` is an object and action is from supported baseline actions. It is auditable via existing intent and audit event flows.

### Governance Safety and Traceability

- Safety gate remains simulation-before-deployment aligned (`ADR-008`).
- Intent lifecycle remains visible on `/ws/digital-twin` and in intent detail.
- Audit records remain queryable via `GET /api/v1/audit/logs`.

---

## 11) Minimum Viable but Impressive Demo Dataset

### Campus Size Target

- Buildings: **7**
- Floors: **27**
- Devices: **339**

### Per-Building Device Targets

| Building | Floors | Device Target |
| --- | --- | --- |
| Strathmore Business School (`sbs`) | 6 | 86 |
| Main Library (`lib`) | 6 | 86 |
| Management Sciences Building (`msb`) | 5 | 71 |
| Strathmore Student Center (`ssc`) | 4 | 60 |
| Building E (`bld-e`) | 2 | 12 |
| Building F (`bld-f`) | 2 | 12 |
| Building G (`bld-g`) | 2 | 12 |
| **Total** | **27** | **339** |

### Category Totals (Approximate)

- Core routers: 2
- Firewalls: 2
- Distribution switches: 23
- Access switches: 64
- Wi-Fi APs: 130
- Servers: 25
- UPS/power/environment: 29
- CCTV/access-control gateways: 29
- Printers/lab endpoints: 35

### Complexity Band

- **Visual complexity:** High
- **Execution complexity:** Medium (repeat existing device-create API calls; no contract changes)

### Why Feasible in Limited Prep Time

1. Single network context avoids multi-network reconciliation overhead.
2. Device records are lightweight (`hostname`, `device_type`, optional `location_hint`, optional `spatial_ref_id`).
3. Twin positioning can run deterministically from spatial strings; no full 3D modeling required.
4. Existing realtime and lifecycle pages already render this data without new APIs.

---

## 12) Telemetry and Alert Simulation Plan

### Telemetry Plan (Existing Surfaces)

- Use `GET /api/v1/telemetry/health`, `/history`, and `/device/{id}` for baseline visibility.
- Use existing websocket channel `/ws/telemetry` for live metric deltas.
- For burst/demo conditioning, use existing tooling script in backend:
  - `scripts/run_vs17_external_load.py` with `--profile local-smoke` and optional `--skip-k6` path.

### Alert Plan (Existing Surfaces)

- Use `GET /api/v1/alerts` for lifecycle list.
- Use existing actions `POST /api/v1/alerts/{id}/ack` and `/resolve`.
- Use `/ws/alerts` to demonstrate realtime lifecycle transitions.

### Congestion Narrative in Twin

- Twin congestion uses existing telemetry metrics and optional telemetry `tags` policy hints.
- Scene adapter policy and thresholds are deterministic and already documented in implementation.

---

## 13) Digital Twin Strategy (Detailed but Easy)

### Core Approach

1. Seed campus devices with normalized `spatial_ref_id` paths.
2. Let Twin adapter derive deterministic placement from spatial hierarchy.
3. Keep optional `.glb/.gltf` model import as enhancement, not dependency.

### Session Model Import Rules

- Model import and sidecar mapping are session-local by default.
- Persist mapping only through existing device update API (`PATCH /api/v1/networks/{network_id}/devices/{device_id}`).
- No backend binary model persistence is assumed.

### Centralized Whole-Campus Experience

- Keep all building/floor segments in one twin route (`/ops/digital-twin`).
- Use layer toggles and inspector context to zoom from campus view to floor and device narratives.

---

## 14) Operator Navigation Walkthrough (Presentation Story)

### Keyboard / Navigation Hints

- Command palette: `Ctrl/Cmd+K`
- Direct route keys: `O`, `W`, `P`, `T`, `R`, `L`, `U`, `Y`, `D`, `S`, `I`, `A`
- Chords: `G O`, `G W`, `G P`, `G T`, `G R`, `G L`, `G U`, `G Y`, `G D`, `G S`, `G I`, `G A`

### Flow Script (Required Order)

1. **Overview (`/ops/overview`)**
   - Confirm websocket status tiles and active campus context.
2. **Tenancy (`/ops/tenancy`)**
   - Show single operations tenant for centralized campus control.
3. **Topology Analysis (`/ops/topology-analysis`)**
   - Prove graph continuity across campus zones and run reconcile.
4. **Telemetry (`/ops/telemetry`)**
   - Show live metrics and device drilldown.
5. **Reliability (`/ops/reliability`)**
   - Show alert lifecycle and source breakdown.
6. **Digital Twin (`/ops/digital-twin`)**
   - Show one whole-campus surface with floor/device overlays.
7. **Simulation (`/ops/simulation`)**
   - Start scenario and show lifecycle detail plus compare path.
8. **Intent (`/ops/intent`)**
   - Validate then execute group-target scope using existing intent contract.
9. **Audit (`/ops/audit`)**
   - Show traceability via correlation IDs and lifecycle events.
10. **Reports (`/ops/reports`)**
   - Show executive summary generation and lifecycle status.

### Campus-Wide Group Operation Moment (Required)

- In Intent, submit a group-targeted scope object (site + function + operational selector).
- Execute through existing intent flow.
- Show impact as:
  - intent lifecycle overlay in centralized Twin (`intent_state` scene object),
  - intent detail payload/provenance in Intent page,
  - audit evidence in Audit page.

Note: per-device automatic fan-out mutations are not a current documented backend contract; this is a control-plane and governance visibility demonstration.

---

## 15) Validation Checklist

- [ ] Uses only documented routes/channels/events.
- [ ] Uses canonical API envelope assumptions only.
- [ ] Uses only documented request/response fields.
- [ ] Keeps one campus context (single org/workspace/network narrative).
- [ ] Uses `spatial_ref_id` convention without adding schema fields.
- [ ] Distinguishes real behavior vs demo assumptions.
- [ ] Includes native device-group status plus scope-selector compatibility guidance.
- [ ] Includes traceability table with file references.

---

## 16) Risks and Fallback Plan

| Risk | Impact | Fallback |
| --- | --- | --- |
| Sparse telemetry in live demo window | Weak congestion/alert story | Use existing synthetic load tooling and pre-warm telemetry health/history before demo start |
| Device-group definition drift from campus conventions | Inconsistent targeting behavior across demo runs | Reconcile native groups via `POST /api/v1/networks/{network_id}/device-groups` and keep intent scope selectors explicit in demo payloads |
| Terminal simulation event parity uncertainty in sprint notes | Possible inconsistency in completed/cancelled showcase | Prioritize deterministic `simulation.started`, pause/branch/compare, and verify terminal behavior in rehearsal |
| 3D model import mismatch | Visual inconsistency | Use deterministic spatial placement from `spatial_ref_id` with no external model dependency |
| High device volume prep pressure | Time overrun | Keep 80/20 detail split; seed showcase floors first, then add light floors |

---

## 17) Real Now vs Demo Placeholder Assumptions

### Real in Current Repo

- Full `/ops/*` route flow exists for the required demo sequence.
- Network/device lifecycle, topology analysis, telemetry, alerts, simulation, intent, audit, and reports APIs exist.
- Digital Twin scene supports spatial mapping, realtime overlays, session model import, and per-device mapping persistence through existing PATCH route.

### Demo Assumptions / Approximations

- Native network device groups exist, but intent execution targeting remains scope-selector based in current demo payload patterns.
- Campus geometry can be simplified; photorealistic building modeling is not required.
- Intent execution impact is shown through lifecycle/audit/twin overlay visibility, not documented per-device mutation fan-out.

---

## 18) No-Hallucination Statement and Traceability Matrix

### No-Hallucination Statement

All routes, fields, channels, scripts, and behaviors in this manual are traced to repository files. Historical contract gaps from the original Phase 1 authoring are explicitly marked and superseded by current repository status where those gaps have since been closed.

### Traceability Matrix

| Claim / Behavior | Evidence |
| --- | --- |
| Canonical API envelope is mandatory | `docs/api/API_STANDARD.md:8` |
| Operator route sequence exists under `/ops/*` | `frontend/src/app/App.tsx:53`, `frontend/src/app/App.tsx:63` |
| App shell navigation and route hints | `frontend/src/shared/ui/AppShell.tsx:9`, `frontend/src/shared/ui/AppShell.tsx:19` |
| Keyboard navigation keys/chords | `frontend/src/shared/lib/hotkeys.ts:6`, `frontend/src/shared/lib/hotkeys.ts:34` |
| Command palette trigger path | `frontend/src/shared/ui/HotkeyLayer.tsx:32` |
| Org/workspace/member APIs | `backend/app/api/v1/organizations.py:44`, `backend/app/api/v1/organizations.py:217` |
| Network/device create/list/update APIs | `backend/app/api/v1/networks.py:43`, `backend/app/api/v1/networks.py:131` |
| Device model includes `location_hint` and `spatial_ref_id` | `backend/app/modules/network/schemas.py:49`, `backend/app/modules/network/schemas.py:50` |
| Topology graph/neighbors/impact/reconcile APIs | `backend/app/api/v1/topology.py:118`, `backend/app/api/v1/topology.py:184`, `backend/app/api/v1/topology.py:212`, `backend/app/api/v1/topology.py:240` |
| Telemetry APIs | `backend/app/api/v1/telemetry.py:35`, `backend/app/api/v1/telemetry.py:80` |
| Alerts APIs | `backend/app/api/v1/alerts.py:29`, `backend/app/api/v1/alerts.py:54`, `backend/app/api/v1/alerts.py:71` |
| Simulation APIs | `backend/app/api/v1/simulation.py:141`, `backend/app/api/v1/simulation.py:223` |
| Intent APIs | `backend/app/api/v1/intents.py:36`, `backend/app/api/v1/intents.py:61`, `backend/app/api/v1/intents.py:87` |
| Intent payload accepts scope object (group selector convention-safe) | `backend/app/modules/intent/schemas.py:45`, `backend/app/modules/intent/schemas.py:48` |
| Supported intent actions include wireless/capacity operations | `backend/app/modules/intent/service.py:28` |
| Audit API for trace visibility | `backend/app/api/v1/audit.py:29` |
| Reports APIs | `backend/app/api/v1/reports.py:34`, `backend/app/api/v1/reports.py:69` |
| WebSocket channel registry (topology/telemetry/alerts/digital-twin) | `docs/api/WebSocket.md:17` |
| WebSocket endpoints mounted in app | `backend/app/main.py:379`, `backend/app/main.py:382` |
| Simulation and intent events routed to digital twin deltas | `backend/app/events/consumers/ws_push_consumer.py:44`, `backend/app/events/consumers/ws_push_consumer.py:52` |
| Twin scene derives placement from `spatial_ref_id` hierarchy | `frontend/src/features/digitalTwin/sceneAdapter.ts:198`, `frontend/src/features/digitalTwin/sceneAdapter.ts:230` |
| Twin supports session-only import + optional mapping persistence via existing device PATCH | `frontend/src/features/digitalTwin/TwinPage.tsx:592`, `frontend/src/features/digitalTwin/TwinPage.tsx:236` |
| Existing local flow check script validates route/websocket baseline | `backend/scripts/run_local_flow_check.py:101` |
| Existing synthetic load script exists for telemetry demo conditioning | `backend/scripts/run_vs17_external_load.py:35` |
| Native device-group lifecycle exists in current contracts | `backend/app/api/v1/networks.py:277`, `backend/app/api/v1/networks.py:300`, `backend/app/modules/network/schemas.py:291`, `frontend/src/shared/types/network.ts:181`, `frontend/src/features/networks/api.ts:117`, `frontend/src/features/networks/hooks.ts:170` |
| Strathmore dataset bootstrap uses existing org/workspace/network/device/simulation/intent routes only | `backend/scripts/prepare_strathmore_demo.py:464`, `backend/scripts/prepare_strathmore_demo.py:703` |
| Strathmore dataset totals are regression-checked by deterministic unit coverage | `backend/tests/unit/test_prepare_strathmore_demo.py:10` |

---

## Phase 1 Acceptance Check

- Blueprint completeness: **met**.
- Contract alignment to existing routes/types/channels: **met**.
- Undocumented endpoint/channel additions: **none**.
- Real vs placeholder assumptions explicitly separated: **met**.

---

## 19) Phase 2 Implementation Package (Delivered)

### Implemented Artifacts

- Added `backend/scripts/prepare_strathmore_demo.py` to generate and optionally apply the centralized Strathmore dataset using existing APIs only.
- Added `backend/tests/unit/test_prepare_strathmore_demo.py` to verify deterministic dataset totals and group-scope intent payload shape.
- Added this Phase 2 manual content (environment steps, runbook-style operator flow, validation evidence, and demo-day command checklist) in the same master document.

### What the Script Does (Contract-Safe)

- Builds deterministic device payloads for all 7 buildings, 27 floors, and 339 devices with `spatial_ref_id` in `campus/building/floor/zone/device` format.
- Uses existing API endpoints for login, organization/workspace/network/device creation, topology read, telemetry health read, alerts list, simulation start/detail, and intent validate/execute/detail.
- Supports dry-run mode by default (no writes) and apply mode via `--apply`.
- Supports optional control-plane checks via `--run-control-plane-check` to execute one simulation and one group-scope intent cycle.

---

## 20) Environment and Infra Commands (Exact)

Use these commands exactly for local demo prep.

```bash
# from repo root
./scripts/dev-start.sh
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

```bash
# terminal 1 - backend
cd backend
poetry install
poetry run alembic -c alembic/alembic.ini upgrade head
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
# terminal 2 - frontend
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

---

## 21) Bootstrap and Login Prerequisites

### Required Checks Before Data Setup

1. Confirm backend health:

```bash
curl http://127.0.0.1:8000/health
```

Expected: HTTP 200 with `{ "status": "ok" }`.

2. Ensure bootstrap user exists (use README bootstrap-user flow).
3. Confirm login and profile path:
   - `POST /api/v1/auth/login`
   - `GET /api/v1/auth/me`

### Fast Integrated Baseline Check

```bash
cd backend
poetry run python scripts/run_local_flow_check.py --report-path /tmp/opencode/nanfo-flow-report.json
```

This validates health, auth, org/workspace/network/device lifecycle, telemetry/alerts reads, and websocket subscribe handshake.

---

## 22) Data Creation Workflow (Existing APIs Only)

### A. Dry-Run (No Writes, Executed in This Session)

```bash
cd backend
poetry run python scripts/prepare_strathmore_demo.py --output-path /tmp/opencode/strathmore-dry-run-full.json
```

Observed output in this session confirms:

- `total_devices: 339`
- Building split: `sbs=86`, `lib=86`, `msb=71`, `ssc=60`, `bld-e=12`, `bld-f=12`, `bld-g=12`
- Device type split aligns with Phase 1 blueprint totals.

### B. Apply Mode (Writes Data Through Existing Endpoints)

```bash
cd backend
poetry run python scripts/prepare_strathmore_demo.py \
  --apply \
  --run-control-plane-check \
  --output-path /tmp/opencode/strathmore-apply-context-latest.json
```

What this performs:

1. Login using existing auth route.
2. Create org/workspace/network.
3. Create all devices via repeated `POST /api/v1/networks/{network_id}/devices`.
4. Verify with `GET /api/v1/networks/{network_id}/devices` and `GET /api/v1/topology/graph`.
5. Run one simulation (`POST /api/v1/simulations/start`).
6. Run one group-scope intent validate+execute cycle using existing intent routes.

### C. Optional Smoke Apply (Small Slice)

```bash
cd backend
poetry run python scripts/prepare_strathmore_demo.py \
  --apply \
  --max-devices 40 \
  --run-control-plane-check \
  --output-path /tmp/opencode/strathmore-apply-smoke.json
```

---

## 23) Group Targeting, Simulation, and Intent Workflow

### Group Capability Status

- Native backend `device_group` resource: **present** in current contracts (`GET|POST /api/v1/networks/{network_id}/device-groups`).
- Compatible targeting approach for demo operations: `intent.scope` selectors using:
  - `site_prefix` (spatial hierarchy)
  - `functional_group` (device-type convention)
  - `operational_group` (operator policy label)

### Group-Scope Intent Payload (Contract-Safe)

```json
{
  "workspace_id": "<workspace_uuid>",
  "network_id": "<network_uuid>",
  "intent": {
    "action": "optimize_wireless_capacity",
    "scope": {
      "target": "group",
      "site_prefix": "strathmore/ssc/f02",
      "functional_group": "wireless",
      "operational_group": "student_services"
    },
    "constraints": {
      "max_downtime": 0,
      "simulation_required": true
    }
  }
}
```

### Expected Validation Path

1. `POST /api/v1/intents/validate`
2. `POST /api/v1/intents/execute`
3. `GET /api/v1/intents/{id}`
4. Visual confirmation in:
   - `/ops/intent` lifecycle timeline
   - `/ops/digital-twin` intent overlay delta
   - `/ops/audit` trace entries

---

## 24) Telemetry and Alerts Demo Conditioning

### Baseline Visibility

- Telemetry: `/ops/telemetry` plus `GET /api/v1/telemetry/health`.
- Alerts: `/ops/reliability` plus `GET /api/v1/alerts`.

### Optional Synthetic Conditioning

```bash
cd backend
poetry run python scripts/run_vs17_external_load.py --profile local-smoke --base-url http://127.0.0.1:8000
```

If external k6 path is not available locally:

```bash
cd backend
poetry run python scripts/run_vs17_external_load.py --profile local-smoke --base-url http://127.0.0.1:8000 --skip-k6
```

---

## 25) Full Operator Manual (Click-by-Click + Talk Track)

Use this exact route order in live demo:

`/ops/overview` -> `/ops/tenancy` -> `/ops/topology-analysis` -> `/ops/telemetry` -> `/ops/reliability` -> `/ops/digital-twin` -> `/ops/simulation` -> `/ops/intent` -> `/ops/audit` -> `/ops/reports`

### Screen Script Table

| Screen | Click-by-click | What to say | Success signal | Fast recovery if failure |
| --- | --- | --- | --- | --- |
| Overview | Confirm org/workspace selectors and WS status tiles. | "This is one campus control plane for every building zone." | WS tiles connected, selected context visible. | Re-login, reselect workspace, refresh WS state. |
| Tenancy | Open tenant, verify one org + workspace + network narrative. | "We operate a single centralized Strathmore operations context." | Org/workspace IDs resolve and lists render. | Recreate workspace if missing, then reselect. |
| Topology Analysis | Select device, run neighbours/impact/reconcile. | "Topology analysis shows blast radius and dependencies before change." | Neighbour/impact cards render; reconcile returns status. | Re-run reconcile; verify network context and node existence. |
| Telemetry | Open health/history/device drilldown panels. | "Live telemetry drives congestion and reliability evidence." | Health and history populate, realtime metrics update. | Run load-conditioning script, then refresh telemetry panel. |
| Reliability | Filter Active, ack one alert, resolve one alert. | "Alert lifecycle is controlled and traceable in real time." | Status transitions Active -> Acknowledged -> Resolved. | Clear filters; verify alerts endpoint and websocket state. |
| Digital Twin | Open centralized campus scene; inspect nodes by spatial path. | "All buildings are represented in one twin, not split twins." | `spatial_ref_id` hierarchy visible; overlays update. | Toggle overlays on, reload topology graph, verify spatial strings. |
| Simulation | Start simulation scenario and open detail. | "Simulation-before-deployment is our safety gate." | Simulation handoff visible with risk-gate metadata. | Retry with valid network context; verify simulation endpoint response. |
| Intent | Validate then execute group-scope payload. | "We can target campus groups safely through intent scope selectors." | Intent lifecycle advances and confidence/explainability render. | Use new idempotency key and revalidate intent JSON. |
| Audit | Filter by intent/simulation event names. | "Every operational action is auditable with correlation IDs." | Matching events appear with timestamps and IDs. | Remove filter, rerun one action, then refresh. |
| Reports | Generate executive summary and poll status. | "Leadership gets the same operational truth in report form." | Report reaches terminal status and artifact metadata appears. | Retry failed report with new idempotency key. |

### Keyboard Hints During Demo

- Command palette: `Ctrl/Cmd+K`
- Chords: `G O`, `G W`, `G P`, `G T`, `G R`, `G D`, `G S`, `G I`, `G A`, `G Y`

---

## 26) Validation Evidence and Command Results

### Backend

- `poetry run ruff check app tests` -> **FAIL** (existing repo-wide legacy lint debt; not introduced by this slice).
- `poetry run ruff check scripts/prepare_strathmore_demo.py tests/unit/test_prepare_strathmore_demo.py` -> **PASS**.
- `poetry run pytest tests/unit/test_prepare_strathmore_demo.py -q` -> **PASS** (`3 passed`).
- `poetry run pytest tests -q` -> **PASS** (`572 passed`).
- `poetry run pytest tests/unit/test_intent_execution_service.py tests/integration/test_intent_endpoints.py tests/unit/test_prepare_strathmore_demo.py -q` -> **PASS** (`31 passed`) after intent execute serialization safety fix.
- `poetry run python scripts/prepare_strathmore_demo.py --apply --run-control-plane-check --output-path /tmp/opencode/strathmore-apply-context.json` -> **PASS** (historical 2026-08-20 run; `339/339` devices, pre-materialization topology snapshot `nodes=339 edges=0`, simulation + intent checks succeeded, artifact written).
- `poetry run python scripts/prepare_strathmore_demo.py --apply --run-control-plane-check --output-path /tmp/opencode/strathmore-apply-context-20260902.json` -> **PASS** (refreshed 2026-09-02 run; `339/339` devices, projection settle `283 -> 339`, synthetic topology `planned_edges=338`, materialization `written=338`, topology graph re-check `edges=338`, simulation + intent checks succeeded, artifact written).

### Frontend

- `npm run lint` -> **PASS**.
- `npm run typecheck` -> **PASS**.
- `npm run test` -> **PASS** (`25 files, 100 tests`).
- `npm run test:e2e` -> **PASS** (`19/19`).
- `npm run build` -> **PASS** (existing large `three` chunk warning unchanged).
- `npm run perf:bundle` -> **PASS** (bounded continuity checks true).

### Runtime and Live Apply Note (This Session)

- `curl http://127.0.0.1:8000/health` returned `200` after runtime restart.
- Initial live apply attempts surfaced `POST /api/v1/intents/execute` `500` with `MissingGreenlet` during intent response serialization.
- Applied bounded backend fix in `backend/app/modules/intent/service.py` (refresh ORM state before serialization) and reran apply successfully.
- Final refreshed live apply evidence artifact: `/tmp/opencode/strathmore-apply-context-20260902.json`.

---

## 27) Final Phase 2 Report

### Files Added/Updated in This Slice

- Added: `backend/scripts/prepare_strathmore_demo.py`
- Added: `backend/tests/unit/test_prepare_strathmore_demo.py`
- Updated: `docs/project/Strathmore-Demo-Manual-and-Execution-Guide.md`

### Known Limitations (Explicit)

1. Intent payload contracts are still selector-based; there is no dedicated `device_group_id` binding field in current intent schema.
2. This Phase 2 script package does not upload binary 3D campus model assets; optional model-asset persistence now exists in current Network contracts and Twin UI.
3. Topology edge richness depends on existing graph relationships; dataset seeding guarantees nodes and spatial mapping, not full physical cabling semantics.
4. Intent targeting payloads remain selector-based (`intent.scope`) and do not bind directly to a dedicated `device_group_id` field in current intent schemas.

### Demo-Day Command Checklist (Concise)

```bash
# infra
./scripts/dev-start.sh

# backend
cd backend
poetry install
poetry run alembic -c alembic/alembic.ini upgrade head
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# frontend (new terminal)
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173

# baseline validation
cd backend
poetry run python scripts/run_local_flow_check.py --report-path /tmp/opencode/nanfo-flow-report.json

# full Strathmore data apply + control-plane checks
poetry run python scripts/prepare_strathmore_demo.py --apply --run-control-plane-check --output-path /tmp/opencode/strathmore-apply-context-latest.json

# optional telemetry conditioning
poetry run python scripts/run_vs17_external_load.py --profile local-smoke --base-url http://127.0.0.1:8000
```

### Demo-Day Run Order Variants

#### 15-minute variant

1. Overview (1.5m)
2. Topology Analysis (2m)
3. Telemetry + Reliability (3m)
4. Digital Twin centralized view (3m)
5. Simulation + Intent group action (3.5m)
6. Audit + Reports closeout (2m)

#### 30-minute variant

1. Overview + Tenancy context setup (4m)
2. Topology analysis deep-dive (4m)
3. Telemetry trends + alert lifecycle operations (6m)
4. Digital Twin campus walkthrough (6m)
5. Simulation branch + compare narrative (4m)
6. Intent validate/execute group-scope + audit proof (4m)
7. Reports and Q&A buffer (2m)

### Group Capability Status (Proof)

- Status: native backend group entity now exists and is exposed via the approved Network contract surface.
- Compatible demo approach: group selectors in `intent.scope` remain valid with existing intent contracts.
- Proof pointers:
  - `backend/app/modules/network/schemas.py:291`
  - `backend/app/api/v1/networks.py:277`
  - `frontend/src/shared/types/network.ts:181`
  - `frontend/src/features/networks/api.ts:117`
  - `backend/app/modules/intent/schemas.py:45`
  - `backend/scripts/prepare_strathmore_demo.py:332`

---

## 28) Phase 2 Acceptance Check

- Manual completeness and executable sequence: **met**.
- Repo-accurate commands and contracts: **met**.
- Tests/checks run and reported where possible: **met**.
- No fabricated endpoints/channels/contracts: **met**.
- Live apply execution and topology materialization evidence: **met** (historical `/tmp/opencode/strathmore-apply-context.json` pre-materialization snapshot and refreshed `/tmp/opencode/strathmore-apply-context-20260902.json` with topology re-check `edges=338`).
