# Workstream 3 — inventory / tenancy UI handoff

## Parent UX review follow-up — automatic authority and selected hero

Implemented automatic own-membership resolution (including actor41) without changing
backend contracts. Fast-path a loaded actor; otherwise sequential20-row reads, abort
on org/session change, initial-total bound, early stop, no aggregate member list.
Query identity includes generation/org/actor/token; rotation revalidates last-found
page first. Only verified current results enable controls; loading/unknown/error/
denied states are explicit, with retry. Global-write gating remains mandatory.
Removed manual membership-discovery instructions from Overview and Tenancy.

The bounded feature navigation cache is now reactive (`useSyncExternalStore`), so
Overview uses the selected network record's real name off-page and after edits.

Verification:14 scoped unit/component tests pass (6 authority tests including
actor41, rotation, cancellation/late response, revoked membership, offline retry,
initial-count termination, global permission and replacement-user isolation).
Inventory/tenancy Chromium11/11 pass, including actor41 automatically enabled while
the visible membership page remains1 and off-page hero name assertion. Typecheck,
scoped lint and whitespace pass.

Follow-up full run:69/70 passed with two workers/zero retries (2.4min). The newly
arrived parallel `session-history-realtime.spec.ts` failed its `Page 2 | 41 devices`
assertion; source was changing during the run (stack line mapped to another step).
All pre-existing69 tests pass; that new spec was left to its author. This supersedes
the earlier69/69 result only for the expanded70-test suite.

## E2E integration ownership — completed

Parent assigned all existing E2E selector/mock integration to this workstream.
Final full run: **69/69 Chromium tests passed**, zero retries, two workers,2.8min:
`npx playwright test --retries=0 --workers=2` (300000ms tool timeout).

- Replaced ambiguous Network A button selectors with `.network-choice` filtered by
  network text; device text assertions use exact matches. Read-only creation test
  opens the disclosure and asserts the real form mutation remains disabled.
- Legacy Twin tests explicitly select a persisted asset, assert restore initially
  disabled, and confirm the exact restore. Cancellation, registration persistence,
  SHA verification, unrelated group retention and URL cleanup remain asserted.
- Scoped revision-conflict alert selection prevents unrelated asset-read alerts
  from making the conflict assertion ambiguous; retained-draft safety is asserted.
- `support/session.ts` now provides typed bounded simulation/intent history mocks:
  authorized workspace/network checks, filtering before deterministic sorting and
  slicing, full totals/page metadata. Optional fixture arrays default empty;
  domain-specific action/detail route mocks retain precedence.
- `support/runtime-errors.ts` installs shared before/after hooks through session
  support. Context web errors and explicit `unhandledrejection` events must remain
  empty, including reloads, popups and independent tabs. All69 tests passed with
  this guard enabled.
- `npx eslint tests/e2e`, `npm run typecheck`, and scoped `git diff --check`: pass.
- Intermediate full runs66/68 and65/69 were superseded after selector integration
  fixes and the Twin owner's new spec correction. Focused Twin regression8/8 also
  passed. New `twin-guided-lifecycle.spec.ts` was included in final69 and never
  edited by this workstream; no Twin app, CSS, or profile changes made here.
- No commits or production builds.

## Hook API (integration contract)

- `useNetworks(token, workspaceId, page = 1, pageSize = 20)`
- `useDevices(token, networkId, page = 1, pageSize = 20)`
- `useOrganizations(token, page = 1, pageSize = 20)`
- `useWorkspaces(token, orgId, page = 1, pageSize = 20)`
- `useOrgMembers(token, orgId, page = 1, pageSize = 20)`

All return normal TanStack queries whose `data` is the server paginated result
(`items`, `total`, `page`, `page_size`). Existing two-argument device/network callers
remain first-page/20 callers. Page arguments enter query keys after existing scope
prefixes. No eager all-page fetch. Telemetry owner: maintain page state, pass it as
third argument to `useDevices`, preserve selected device ID across page changes.

Shared UI primitive implemented: `@/shared/ui/Pagination`, props `label`, `page`,
`pageSize`, `total`, `onPageChange`, optional `pending`. It renders bounded previous/
next controls and authoritative total. No base stylesheet changes.

Inventory create hooks accept complete snake_case documented input objects;
legacy string network creation and camelCase device input remain compatible.
New mutation hooks: `useUpdateNetwork(token, workspaceId)` with
`{networkId, changes}`, `useDeleteNetwork(token, workspaceId)` with network ID;
`useUpdateDevice(token, networkId)` with `{deviceId, changes}` and
`useDeleteDevice(token, networkId)` with device ID.

Tenancy list wire contracts currently return `items,total`; their hooks add the
requested `page,page_size` to query data. Inventory wire contracts supply all four.

Current-membership gating now resolves the actor automatically using the existing
member-list contract. An already loaded actor is a fast path; otherwise a cancellable
query reads one20-row page at a time, stops at the actor, and retains only role/page.
The initial server total bounds the scan, so concurrent inserts cannot extend it
indefinitely. Rotation revalidates the previously found page first and automatically
rescans if membership moved. No manual membership paging or new endpoint is needed.
Controls are disabled while unknown/loading/error/denied, with explicit status and
retry for read errors. Global permissions and backend mutation checks remain required.

AppShell currently keys its whole Outlet by session+org+workspace+network. Feature-
owned `useScopeState` retains at most50 navigation values keyed by session generation
and owning scope (page and selected entity summary). Its external-store subscription
keeps the off-page selected network's real name in the overview hero, including
renames. Membership is held separately in the scoped query cache. Drafts
stay local and reset on context remount; token rotation does not reset drafts.

## Completed implementation

- Real network and device forms with all documented fields, backend-aligned string
  limits, explicit unknown/null optional values, and changed-field-only PATCH.
- Confirmed network/device deletion, visible409/403/422 and transport/server errors,
  retained drafts, pending double-submit prevention. Ambiguous mutations disable
  resubmission until the operator explicitly reviews records; refresh is read-only.
- Organization rename/delete, workspace edit/delete, member removal confirmation,
  active descendant scope cleanup, global-write plus observed current-org Admin gate.
- Slug follows name until explicit editing; manual keyboard input is not normalized
  on every keystroke. Native3..63/character validation before submission.
- All five list kinds use bounded20-row pagination and server totals; off-page
  selected IDs and newly created entity selection are preserved. Shrinking final
  inventory/tenancy pages clamp to the new last page.
- Preserved atlas hero, overview grid, inventory choices, panels and input styling.
  Shared addition is only `Pagination.tsx`; no shared CSS or shell changes.
- Updated owned legacy browser tests `vs1-overview.spec.ts` and
  `vs6-spatial-ref.spec.ts` to use the full device editor and assert spatial PATCH.

## Verification (final)

- `npm run typecheck`: pass (earlier transient parallel reliability/telemetry test
  fixture errors were fixed by their owners).
- Scoped ESLint: pass, no warnings.
- `npx vitest run src/features/overview src/features/organizations`:8 passed.
- Scoped Chromium:13 passed, zero retries (11 new inventory/tenancy scenarios plus
  two existing overview/spatial scenarios). Real sliced21-row fixtures; exact
  creation and subset PATCH bodies; create/edit/delete; current-scope cleanup;
  permission/validation/conflict failures; pending/offline/lost response; member
  remove/re-add; org role gating; keyboard slug; token-rotation component regression.
- Browser command: `npx playwright test --config=/tmp/opencode/inventory-playwright.config.ts`.
  Dedicated dev port4183 avoids shared parallel port4173 lifecycle collisions.
  Config uses the repository tests and Vite dev server; no production build.
- Whitespace check: pass. No commits.

Browser fixtures establish frontend contract behavior; backend integration remains
with the backend owner. This handoff is the workstream-owned tracking file; global
tracking remains parent-owned.
