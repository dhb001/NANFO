# Audit repair — workstream 4: session continuity and durable history

## Published contracts (ADR026)

- `GET /api/v1/simulations` and `GET /api/v1/intents`: required UUID
  `workspace_id`, optional UUID `network_id`, `page=1` (minimum 1),
  `page_size=20` (1–200). Canonical envelope; data is
  `{items,total,page,page_size}`. Order: `created_at DESC`, primary UUID `DESC`.
- Simulation item: `{simulation_id,network_id,workspace_id,scenario_name,status,
  created_at,updated_at}`. UUIDs and timestamps serialize as strings.
- Intent item: `{intent_id,network_id,workspace_id,action,status,created_at,
  updated_at}`. `network_id` is nullable. `action` is a nullable string capped at
  120 characters, projected from the existing payload; full payload is only on
  detail. This is ADR026's approved narrower action projection.
- Both require `read:topology`, current workspace membership via WorkspaceService,
  and claim narrowing before repository access/count/paging. An optional network
  must be active and in that workspace via NetworkService. No cross-owner SQL.
- Histories do not execute actions. Frontend URL parameters `simulation_id` and
  `intent_id` select detail only; `baseline_id` selects simulation comparison.

## Coordination / ownership

This workstream owns auth-session/shared auth utility changes, Simulation/Intent
history routers and owner-local history modules, their frontend pages/hooks/API,
AutonomyPage key/operatorSession, TelemetryPage/hooks/API and associated tests.
Autonomy `hooks.ts` also needed the same small credential-independent query/callback
fix: otherwise STOP receipts after rotation were discarded despite preserving the
page. No autonomy domain/lifecycle policy changed.
InventoryUI supplies `useDevices(token, networkId, page = 1)`; telemetry consumes
its server totals and page controls. Network/Organization/Identity owners remain
responsible for their membership/inventory contracts. Parent owns global tracking,
test profile and final broad quality gates. Existing uncommitted work is retained.

## Continuity design

Feature lifetime and query identity use session generation/user plus tenant scope,
never rotating tokens. Async requests use current credentials within that captured
scope and reject results after scope/session changes. Permission/role changes revoke
approval separately from drafts and immutable retry identities. Only explicit HTTP
401 triggers authentication retry; transport loss/5xx never replays an arbitrary
mutation. History supports recovery when a non-idempotent start response is lost.

## Verification

Implemented owner-local `simulation/history.py` and `intent/history.py`, routers
before UUID detail routes, bounded frontend lists/deep links, atomic profile+token
rotation, stable session/tenant cache identity, authority-specific approval resets,
current-token async request guards, paged telemetry device picker and observation
age/stale stamps. No migrations are required (existing owner tables only).

Early frontend typecheck encountered concurrent Reliability test typing changes;
the owner resolved those. Final check results follow.

Targeted backend:62 passed (new history unit/router plus existing simulation/intent
endpoint suites). Disposable loopback PostgreSQL:2 passed, with41 tied records,
multiple tenants/networks, nullable intent network, bounded action projection,
empty/out-of-range pages and exact server totals. Uses existing0014 simulation
fixture (all required columns); temporary PostgreSQL was stopped and removed.

Final targeted frontend run: **296 passed in33 files**, covering auth, Simulation,
Intent, Autonomy, Telemetry, shared API and auth store. Includes token rotation during
draft edits/pending start/pending execute/unknown-response exact retry/pending STOP;
stable history query keys and next requests using current credentials; authority
change revokes approval; stale tenant results are rejected; transport/5xx/unreadable
success never replays arbitrary mutations; confirmed401 retries exact request only
after refreshed profile verification. History tests reach page3 of41 records, retain
deep-linked selections after remount, clear tenant-bound selection and assert no POST.
Telemetry reaches device41, preserves off-page selection/filters and labels stale age.

- `npm run typecheck`: passed.
- Targeted ESLint for owned auth/session/page/hook/test changes: passed.
- Ruff for history modules, routers and all three new backend test files: passed.
- Scoped `git diff --check`: passed.
- Backend command: `poetry run pytest tests/unit/test_workflow_history.py
  tests/integration/test_workflow_history_endpoints.py
  tests/integration/test_simulation_endpoints.py
  tests/integration/test_intent_endpoints.py -q --no-cov` (62pass).
- PostgreSQL command: `python /tmp/opencode/run_session_history_pg.py` (2pass,
  creates/stops/removes its own loopback server). Reusable test:
  `SIMULATION_TEST_DSN=... poetry run pytest
  tests/integration/test_workflow_history_postgres.py -q --no-cov`.

Initial targeted failures were test-fixture omissions (new history hook mocks,
intent validation_result, typed telemetry tenant fields), Python mock assert-name
guard and conflicting test-role definitions, plus a URL-selection tenant-reset
regression found and repaired. Final results above supersede intermediate runs.
Parent can include this lane in full-suite/browser/build/performance gates; those
broader gates were not rerun by this workstream. Raw telemetry retains existing page
mode; optional cursor conversion is not included. No commit created.
