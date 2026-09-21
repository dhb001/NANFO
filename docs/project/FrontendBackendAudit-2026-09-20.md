# Frontend / Backend Workflow Audit — 2026-09-20

## Verdict

**Repair update:** the user subsequently authorized full parallel implementation.
A01–A17 software repairs and requested missing workflows are now implemented; see
`AuditRepair-Completion.md` for the final matrix, regression results and remaining
Redis/deployment/historical-data verification limits. The original findings and
audit-time evidence below are retained as the pre-repair record.

**Changes required.** The tested core has substantial coverage, but passing frontend
tests do not establish workflow completeness. This audit reproduced UI data loss,
incomplete lists, hidden mutation errors, broken membership restoration and audit
record defects. Application code was reviewed, not repaired during this audit.

Scope: all 12 authenticated frontend routes, login/session handling, their API
clients and public backend routers, focused service/repository traces, migration
and deployment checks. Backend/AI experimental work was already uncommitted in the
working tree. Results describe that local source snapshot, not an installed release.

## Verification evidence

| Check | Result | Interpretation |
|---|---|---|
| Frontend full suite immediately preceding this audit, same app source | 527 unit/component tests;54 Chromium tests passed, no retries | Existing contracts/workflows pass; not evidence every workflow is covered |
| Frontend type/lint/build/performance, preceding redesign | Pass;409.70KiB JS gzip versus410.16KiB cap | No frontend app changes during audit |
| Additional browser probes | 6/6 defect-reproduction assertions passed | Inventory truncation, hidden create failure, audit row overlap, refresh data loss, alert filter/scope mismatch, slug typing bug |
| `poetry run pytest tests -q --no-cov` | **3371 passed,1 failed,239 skipped** | Failing current-schema assertion:0028 head versus0027 acceptance constant |
| Additional real PostgreSQL suites,14 files | **210 passed,2 failed,1 skipped** | Two outbox/spatial tests use0021 but current service requires0022 history; report Redis test skipped |
| Fresh full migration chain | **0028 reached successfully** | Real disposable PostgreSQL, not shared stores |
| Additional real DB probes | Confirmed7 behaviors listed below | Actual services/repositories, fakeredis for publication, direct audit-consumer execution |
| Backend Ruff (`app tests scripts`) | **1 E731 finding** | `app/modules/autonomy/experimental/verification.py:341` |
| Deployment tests | **216 passed** | Local operations logic; no live deployment/restore rerun |

DB probe results: inventory audit existed globally but org-filtered count was0;
membership audit actor was the target; remove/re-add member raised IntegrityError;
deleted-slug reuse raised IntegrityError; invalid IP and negative page size raised
DBAPIError after schema acceptance; Operator resolved to read-only permissions.

Temporary probe sources: `/tmp/opencode/nanfo-audit/probes.spec.ts`,
`/tmp/opencode/nanfo-audit/backend_probes.py`, configuration
`/tmp/opencode/nanfo-audit.config.ts`. Browser command:
`npx playwright test --config=/tmp/opencode/nanfo-audit.config.ts` from frontend.
Backend wrapper: `PYTHONPATH=/home/DHB/Documents/NANFO/backend:/home/DHB/Documents/NANFO poetry run python /tmp/opencode/nanfo-audit/backend_probes.py`.
The wrapper creates and removes an isolated loopback PostgreSQL. Owned children
were reaped and directories/ports cleaned. No existing database was migrated.
An initial integration invocation used the wrong DSN driver; the corrected asyncpg
run above supersedes those harness setup errors. A deployment invocation without
repository PYTHONPATH failed collection; the corrected run passed216 tests.

## Prioritized findings

### A01 — High: normal token refresh destroys in-progress workflows

- `frontend/src/features/simulation/SimulationPage.tsx:29–34`
- `frontend/src/features/intent/IntentPage.tsx:33–38`
- `frontend/src/features/telemetry/TelemetryPage.tsx:24–29`
- `frontend/src/features/autonomy/AutonomyPage.tsx:35–40`
- `frontend/src/features/auth/session.ts:48–56`

Components use the access-token string as a React key. Successful refresh replaces
the token without changing the user or tenant; React unmounts the entire feature
and recreates drafts, selected IDs and local mutation tracking. A browser probe
typed an unsaved scenario and triggered401→successful refresh; the scenario reset
to its default and tracked simulation ID became empty. Intent retry identity and
autonomy panel selection have the same remount mechanism; those impacts are traced,
not independently reproduced here.

**Fix:** key by session generation/user/tenant, not rotating credentials. Refresh
queries/auth clients independently. Explicitly invalidate approval when authority
changes while retaining non-authorizing drafts and immutable in-flight identities.
**Regression:** expire a token during editing, start/execute, ambiguous-response
retry and emergency-stop monitoring; assert identity/state continuity.

### A02 — High: inventory creation is still a sample-data action

`frontend/src/features/overview/OverviewPage.tsx:214–238,276–295` creates
`Network-<last4 timestamp>` and `sw-<last4 timestamp>`, always type `switch`, with a
random `campus-a/building-1/floor-1/rack-*` reference. There is no operator entry for
network name/CIDR/description or device hostname/IP/type/vendor/model/location.
Backend supports those creation fields (`network/schemas.py:37–71`), and frontend
API types expose them, but hooks narrow what the screen can submit.

**Impact:** users cannot accurately onboard actual inventory through the UI;
fictional location metadata is persisted as if supplied. Short timestamp names
repeat every10 seconds, and no rename API exists for correcting inventory names.
**Fix:** real creation forms with explicit required inputs and optional spatial
location; preserve unknown location as null. Wire documented optional fields through
hooks. Keep sample generation in an explicitly separate fixture/demo tool.
**Regression:** submit a router/AP with IP and custom name; assert exact request and
persisted values; assert no unsolicited spatial reference is generated.

### A03 — High: inventory and tenancy stop at the first20 records

- `frontend/src/features/networks/api.ts:32–50`, `hooks.ts:20–51`
- `frontend/src/features/organizations/api.ts:44–59`, `hooks.ts:12–42`
- `frontend/src/features/overview/OverviewPage.tsx:237–238`
- `frontend/src/features/telemetry/TelemetryPage.tsx:227–240`

Hooks always request page1, page_size20. Screens provide no pagination. The overview
uses `items.length`, not backend `total`, for capacity. A21-network probe displayed
20, had no next/load-more control and never requested page2. The same pattern limits
devices, organizations, workspaces and members; telemetry's device picker inherits it.

**Fix:** page/search controls or bounded searchable selectors; use authoritative
totals, explicitly distinguish loaded counts. Backend lists also need deterministic
ordering (`network/repository.py:48–54,131–137`, organization repository lists).
**Regression:**21/41 records, select/edit final page, create beyond first page,
selected entity outside current page, concurrent inserts and stable ordering.

### A04 — High: inventory audit records are inaccessible to the audit API

- `backend/app/modules/network/service.py:92–101,234–246,316–326`
- `backend/app/events/consumers/audit_consumer.py:106–122`
- `backend/app/api/v1/audit.py:48–65`
- `backend/app/modules/identity/repository.py:135–136`

Inventory event payloads contain workspace/network but no org_id. The audit
consumer simply copies payload.org_id, yielding NULL. Audit reads require an org
and filter strictly by it. Real DB reproduction: one network-created audit row,
zero rows for the correct organization. Thus successful creation can disappear from
the operator's audit history even when event delivery and persistence work.

**Fix:** resolve/record tenant identity through owning services or a reviewed additive
event contract at publication; keep audit reads scoped. Plan an append-only repair
strategy for existing records rather than weakening scope or rewriting history.
**Regression:** actual inventory mutation→outbox→consumer→authorized audit GET,
including deleted-parent and cross-tenant cases.

### A05 — High: member audit records blame the affected user

`backend/app/events/consumers/audit_consumer.py:76–82` chooses payload.user_id before
payload.actor_id. Membership events provide both (`organization/service.py:494,539`),
where user_id is the added/removed member. Real DB probe confirmed the persisted
actor is the target, not the administrator.

**Fix:** explicit event-specific actor/resource mapping. Workspace events also
select org_id before workspace_id in the generic resource fallback; test that mapping.
**Regression:** different administrator/target UUIDs for add/remove and correct
workspace resource identity.

### A06 — High: removing a member prevents adding that member again

- `backend/app/modules/organization/repository.py:156–181`
- `backend/app/modules/organization/service.py:481–487`
- `backend/app/modules/organization/models.py:48–59`

Remove soft-deletes a row; duplicate lookup ignores deleted rows; add INSERTs the
same `(org_id,user_id)` primary key. Real create→remove→add service reproduction
raised IntegrityError, which the generic HTTP handler maps to500.

**Fix:** transactional membership restore/upsert with current authority, role
validation, concurrency handling and immutable audit of restoration. Do not insert
another row with the same key.
**Regression:** remove/re-add, role changed on restoration, concurrent re-add and
revocation race against restoration.

### A07 — High: alert filtering can hide an older active incident

`frontend/src/features/reliability/ReliabilityPage.tsx:27,34–37,71–72` loads200
alerts without filters and applies Active/Ack/Resolved/search locally. Backend
already supports status/severity/source/search before LIMIT
(`backend/app/api/v1/alerts.py:66–82`, `alert/repository.py:25–90`).

A browser probe verified that Active sends no status query and can say no alerts
match while older server records were never fetched. Because backend caps the
latest200 across all states, many recently resolved incidents can hide unresolved
ones. **Fix:** send existing filters to the server, debounce search, distinguish
loaded counts and server counts; design pagination if history beyond the limit is
required. **Regression:** active incident older than200 resolved records.

### A08 — Medium: REST alert scope differs from realtime/selected network

REST `/alerts` derives accessible workspaces from token/current membership, not UI
selection (`alerts.py:74–85`, `alert/service.py:87–113`). Login creates unscoped
tokens (`identity/service.py:168–176`). UI does not pass or show network scope;
realtime instead filters to selected workspace/network
(`frontend/src/features/realtime/RealtimesBridge.tsx:213–220`). Browser probe with a
different authorized network's alert confirmed it is rendered without a network label.

This is **an operational scope ambiguity, not a demonstrated authorization leak**:
the backend checks the user's actual memberships. **Fix:** explicitly label all-
authorized-scope views and each alert's origin, or approve server-side workspace/
network filters that preserve current authority checks and apply before LIMIT.

### A09 — Medium: Create Network/Add Device errors have no feedback

`frontend/src/features/overview/OverviewPage.tsx:214–229,276–295` awaits mutation
promises in click handlers without catch or rendering mutation.error. Browser503
probe generated an unhandled page error and no visible failure message.

**Fix:** explicit failure states, recovery actions and retained input; communicate
ambiguous outcomes without blindly creating duplicates. **Regression:**403/422/503,
offline, delayed response and lost successful response for both actions.

### A10 — Medium: audit view is incomplete and rows overlap

`frontend/src/features/audit/AuditPage.tsx:35–39,79–100` reserves54px per row but
does not measure rendered rows. Browser measured83.67px height with54px row stride:
about30px overlaps the next entry. Actor/resource IDs and metadata exist in the
response but are never displayed. `audit/hooks.ts:8` loads only first120 entries,
with no paging; search is only local. Input also has no explicit label.

**Fix:** dynamic row measurement or actual fixed-height design; expandable actor,
resource and before/after evidence; backend filters and pagination; accessible label,
zero-filter-result state. **Regression:** long event/UUID, narrow viewport, zoom,
120+ logs, actor search and metadata inspection.

### A11 — Medium: Organization/Workspace edit and delete have no UI controls

Backend routes exist at `backend/app/api/v1/organizations.py:122,144,230,256`.
`frontend/src/features/organizations/api.ts` has no update/delete clients for these
resources, and TenancyPage supports creation, selection and membership only.

**Fix:** wire authorized rename/edit and confirmed deletion workflows with active-
context cleanup. Review descendant/worker behavior before exposing deletion broadly.
**Regression:** current organization Admin versus non-Admin, deleted selected context,
server denial/conflict and dependent-resource outcomes. These are existing backend
capabilities missing UI; inventory rename/delete is a separate full-stack gap.

### A12 — Medium: Operator permissions differ from frontend test fixtures

`backend/app/modules/identity/repository.py:55–68` returns the same two read
permissions for Operator and Read-Only. `frontend/src/test/profile.ts:3–9` assumes
an Operator also has write:config. Actual permission method confirmed read-only.
Organization-role Operator is distinct from global Operator and cannot add a global
capability missing from the backend role map.

**Fix:** agree the intended global/org capability matrix; implement/test it centrally
and derive realistic browser fixtures. Do not make the UI grant permissions or
blindly give Operators all Admin capabilities. Tenancy controls should also reflect
current org Admin requirements, not global write permission alone.

### A13 — Medium: invalid inventory input reaches database as server error

`backend/app/modules/network/schemas.py:37–41,64–75` accepts an invalid IP string,
unvalidated CIDR/device type and unbounded/blank network name; network/org list
routers accept unbounded page/page_size. Devices store IP in PostgreSQL INET.
Real service probes: invalid IP and page_size=-1 caused DBAPIError. No specialized
handler converts these to validation errors (`app/main.py:510–522`).

**Fix:** IP/CIDR validation, sensible string constraints, documented device types,
strict page>=1 and bounded page_size at API boundaries, deterministic ordering.
Keep limits consistent with internal500-sized callers when selecting bounds.
**Regression:**invalid IP/CIDR, blank/oversize fields, negative/zero/huge pagination.

### A14 — Medium: deleted organization slug produces500 on reuse

`organization/repository.py:34–37` ignores deleted organizations in slug lookup,
but `organization/models.py:22` keeps a global unique constraint. Recreating a
deleted slug passed the precheck and raised IntegrityError in real PostgreSQL.
Concurrent same-slug creates also require constraint-error translation.

**Fix:** define whether slugs are permanently reserved, restorable, or reusable;
align lookup/index and return409 for expected conflicts. **Regression:**delete/reuse
and two concurrent creates with same slug.

### A15 — Medium: organization creation auto-fills an invalid one-character slug

`frontend/src/features/organizations/TenancyPage.tsx:182–187` derives slug only while
it is empty. Typing `North Campus` leaves slug `n` after the first keystroke. Browser
probe confirmed this. The backend rejects one character. **Fix:** track whether slug
was explicitly edited; continue deriving until then. Align client/server minimum
length (backend message says3, its regex also accepts2).

### A16 — Medium: organization lifecycle audit publication is not durable

`backend/app/modules/organization/service.py:61–80,116–142,162–182,255–278,486–504`
commits mutations and only then publishes, swallowing publication failure. A Redis
outage after authorization/commit leaves a successful organization/workspace/member
change without its required audit event, with no outbox retry. This is source-traced;
the outage path was not separately exercised by a real Redis process in this audit.

**Fix:** Organization-owned transactional outbox or atomic audit through the existing
Identity service boundary; stable event IDs and dedup. **Regression:** failure after
commit/before publication, restart replay, exactly one audit record.

### A17 — Medium: quality gates and migration fixtures have drifted

- Full-suite failure: `backend/tests/unit/test_verify_measured_twin.py:38–50` treats
 0027 acceptance target as repository head although ADR025 adds0028.
- Real DB failures: `backend/tests/integration/test_network_outbox_postgres.py:179`
 explicitly requests0021 while current SpatialSceneService appends revisions from0022.
- Ruff E731: `backend/app/modules/autonomy/experimental/verification.py:341`.
- Deployment tools intentionally target0027; ADR025 is a separate private CLI lane.
 Do not indiscriminately replace every0027 constant with0028 or rewrite historical
 acceptance evidence.

**Fix:** explicit current-release versus experimental/head migration checks; current
schema for current-service tests, separate historical migration tests; fix lint.
Promote a bounded disposable PostgreSQL/Redis lane into regular CI. Current database
workflow is manual-only and omits experimental-lab PostgreSQL tests.

## UI/backend capability map and improvements

| Area | Connected capabilities | Remaining work |
|---|---|---|
| Authentication | Login, profile, refresh, logout | Draft-preserving rotation; clearer non-JSON/offline errors; account provisioning remains external, no user-create/invite/password-reset API/UI |
| Organizations/workspaces | Create/list/select; add/remove members | Edit/delete UI missing; re-add defect; pagination; slug typing; org-role-aware controls |
| Inventory | Create/list and spatial-reference PATCH | Real forms; paging/totals/error states; hostname/IP/type edits and deletion absent in backend too |
| Topology | Graph, neighbor/impact analysis, reconcile | Surface partial graph/analysis caps consistently; selected-device deletion recovery; real Neo4j integration remains separate |
| Telemetry | Health, time filters, aggregation, main-history paging, device preview | Device selector pagination; raw cursor API available but UI uses page mode; clearer freshness/age on live metric cards; device preview intentionally capped20 |
| Reliability | List, ack, resolve, details/history | Server filters; consistent selected scope; older-incident/history access |
| Digital Twin | Scene/layers, imports, persisted assets, registration, scene JSON/history/restore, modeled RF artifact import, measured path reads | Guided object/geometry editor, asset selection/history beyond latest restore, custom group editor; current JSON editor is functional but specialist-only |
| Simulation | Start, pause, resume, branch, detail, compare | Recoverable history/list and deep-link selected run; currently manual ID/realtime-known records. No public list endpoint; adding a button alone cannot solve it |
| Intent | Validate, exact approval, execute, cancel/compensate, detail/evidence | Durable browsable history/list and deep links; preserve retry identity over refresh; list endpoint absent |
| Autonomy | Modes, stop, configuration, overrides, model diagnostics | Permission fixture parity, refresh continuity; configured/qualified provider availability must stay truthful |
| Plugins | Metadata registration, enable/disable, uninstall | Registry-only is explicit; no runtime plugin engine implied; search before capped retrieval already exists |
| Reports | Generate, history paging, status, verified download | Friendly date/source selectors and discoverable request identity/retry; simulation/intent UUID entry depends on missing history UX |
| Audit | Org-scoped read, local filter | Tenant/event mapping, actor attribution, row measurement, details and pagination |
| Private operations | Fleet, archives/retention, calibration, experimental lab CLI | Not automatically missing UI buttons. ADR025 explicitly forbids a public experimental mode/API/UI until separately approved |

## Recommended repair order

1. **Trust and data retention:** A01,A04,A05,A06; regression tests that reproduce each.
2. **Operator workflow completion:** A02,A03,A07–A11,A15; accurate creation and paging,
   error handling, scope labels and usable audit evidence.
3. **Contract/backend hardening:** A12–A14,A16; role matrix, validation, restoration,
   concurrent conflicts and durable lifecycle audits.
4. **Continuous verification:** A17 plus real authenticated browser→FastAPI→PostgreSQL/
   Redis smoke flows, matching backend-issued role profiles, schema-driven fixtures,
   all-browser pageerror/unhandledrejection collection,21+/200+ records, token expiry,
   multi-tenant membership, concurrent writes and API failure injection.
5. **Broader UX:** run/intent history, guided spatial/custom-group editing and inventory
   lifecycle APIs after their approved contract designs.

## Coverage limits

No assertion that every line or deployed integration is correct. Browser probes use
contract fixtures; database probes use real PostgreSQL and fakeredis, not live
switches. Full remote deployment, real Redis/socket fanout, Neo4j, physical SNMP/RF,
privileged network mutation, and admitted live model/safety execution were not newly
qualified.239 default skipped cases are not passes;210 opt-in PostgreSQL passes
overlap that inventory and must not be added to3371 as an independent suite total.
Current physical/autonomous qualification limits remain in CompletionProgram.
