# ADR027 R02 / R08 — asset download and metadata pagination

Implemented and verified 2026-09-21. Authority: ADR027 contracts 1 and 3,
`docs/architecture/Frontend.md`, Network PRD and the ADR022 Assets handoff.

## Delivered contract

- Binary GET remains
  `/api/v1/networks/{network_id}/campus-model-assets/{asset_id}/download`.
  The client now accepts its actual `Content-Type: application/octet-stream`
  and quoted `ETag: "sha256:<digest>"`. It constructs the URL from scoped IDs,
  uses bearer authentication, rejects redirects, bounds streaming reads to the
  declared size (at most 8 MiB), and checks the actual final byte count.
- Restore still computes SHA-256 over the actual bytes in `decodePersistedModel`.
  The stored MIME is used only for local format validation/interpretation after
  size/hash verification. A matching ETag never substitutes for hashing the body.
  Compatibility inline payloads are validated when present; metadata-only legacy
  inline rows use the same authenticated binary endpoint as CAS assets.
- Existing GET `/api/v1/networks/{network_id}/campus/model-assets` accepts
  `include_data=false&page=1&page_size=20`. Bounds: `page >= 1`,
  `1 <= page_size <= 100`; invalid parameters return the canonical 422 envelope.
  Metadata mode returns the canonical envelope with
  `data: {items,total,page,page_size}`. `model_data_base64` is **omitted**, while
  nullable metadata such as `registration`/`source` retains its existing meaning.
- Repository scope (`network_id`, active rows) precedes counting/offset/limit.
  Ordering is `created_at ASC, campus_model_asset_id ASC`. The SQL projection
  excludes the inline payload column; metadata mode neither loads inline bytes
  nor opens CAS objects. Missing/corrupt bodies consequently do not prevent
  browsing metadata; binary download and legacy full-body listing still fail closed.
- The default (`include_data` omitted or true) retains legacy `{items,total}` and
  verified reconstructed base64 bodies. POST retains that response shape and its
  existing input/identity semantics. Page arguments do not paginate legacy mode.
  No migration is required.
  **Superseded by ADR-028 C4 (2026-09-24, BREAKING default):** the list now defaults to
  `include_data=false` metadata pages. `include_data=true` needs `page_size <= 10` and at
  most 32 MiB of bodies per page, and POST responses are metadata only. Downloads
  additionally answer a matching `If-None-Match` with 304. See
  `docs/api/ADR028-ContractChanges.md`.
- Read permission, current Organization membership, token workspace/org narrowing,
  final authority recheck and scoped download/retirement rules remain enforced.

## Frontend behavior

- Asset API/hooks always request explicit 20-row metadata pages. Query identity
  includes stable session/tenant authority and page parameters rather than the
  rotating credential; requests obtain the current token, forward query aborts,
  and reject stale context/authority results. Saving invalidates asset page queries.
- Twin offers Previous/Next controls, total/page status, loading/error/retry and
  empty-page recovery. One selected asset is retained in addition to the current
  page, keeping both restore and exact-ID retirement available off-page.
- Restore refreshes the selected asset's source page and complete topology, then
  downloads only that asset. Session/tenant checks surround asynchronous reads and
  model validation; existing operation/epoch/topology checks also remain in place.
  Token rotation preserves selection and page. Session/tenant changes remount the
  existing keyed Twin content, resetting selection/page and disposing model URLs.
- If concurrent retirement shifts an asset off its remembered source page, restore
  stops and asks the operator to refresh/reselect. It does not scan all pages or
  restore stale mapping/registration metadata. Offset pagination is not a snapshot.

## Cross-contract regression

`frontend/src/test/fixtures/asset-download.json` is the shared body/header fixture.
`test_real_download_matches_shared_frontend_contract_fixture` obtains an actual
authenticated FastAPI response through the real download service and inline-body
integrity path, then asserts the body and every fixture header. Repository/session
dependencies use the existing endpoint test harness.

Frontend `assetDownload.test.ts` imports that exact fixture, streams its response,
then performs actual WebCrypto SHA-256 and glTF validation. Same-length corruption,
short bodies, wrong MIME/ETag/length, canonical denial, context changes and token
refresh/session replacement are covered. Previously incorrect browser headers are
updated to the backend contract, and browser asset lists omit compatibility bytes.

## Executed checks

Backend (from `backend/`):

```bash
poetry run pytest tests/unit/test_asset_service.py tests/unit/test_asset_pagination.py tests/unit/test_network_schemas.py tests/unit/test_network_service.py tests/integration/test_asset_endpoints.py tests/integration/test_network_endpoints.py -q --no-cov
poetry run ruff check app/api/v1/networks.py app/modules/network/schemas.py app/modules/network/repository.py app/modules/network/service.py tests/unit/test_asset_service.py tests/unit/test_asset_pagination.py tests/integration/test_asset_endpoints.py tests/integration/test_asset_postgres.py
ASSET_TEST_DSN='<owned disposable PostgreSQL DSN>' poetry run pytest tests/integration/test_asset_postgres.py -q --no-cov
```

- **168 passed**, scoped Ruff passed.
- **9 real PostgreSQL tests passed**. New paging case inserts 23 same-timestamp
  mixed inline/CAS assets in reverse UUID order plus foreign/deleted records,
  verifies 10/10/3/0 pages and stable scoped total/order, and reads missing-CAS
  metadata successfully. Existing immutable identity, transaction, migration and
  authority-race tests also pass.
- Disposable non-root cluster: `/tmp/opencode/adr027-assets-pg-1cCXj8`, private
  socket only, port55587; test schemas dropped and cluster stopped by EXIT trap.
  No shared database or container was changed.

Frontend (from `frontend/`):

```bash
npm run typecheck
npm test -- src/features/digitalTwin/assetDownload.test.ts src/features/digitalTwin/assetApi.test.ts src/features/digitalTwin/assetHooks.test.tsx src/features/digitalTwin/modelAsset.test.ts src/features/digitalTwin/TwinPage.test.tsx src/features/digitalTwin/TwinLifecycleControls.test.tsx
npx playwright test tests/e2e/spatial-scene.spec.ts tests/e2e/twin-consistency.spec.ts tests/e2e/twin-guided-lifecycle.spec.ts --workers=2 --retries=0
```

- Typecheck passed; **40 unit/component/hook tests passed**; ESLint passed on all
  touched frontend source/tests. Hook tests exercise cancellation, stable cache
  identity on token rotation, latest-token reads and all-page save invalidation.
- **9 browser tests passed without retries**. After adding the 21-asset paging
  scenario, `twin-guided-lifecycle.spec.ts` was rerun with one worker/no retries and
  passed: page2 retains the page1 selection, restore refreshes page1, off-page
  retirement targets the chosen UUID, empty last-page navigation recovers.
- Initial test-only failures were corrected: nullable-field TypeScript assertions,
  a scope fixture expected403 where its absent Organization yields404, and two
  component fixtures used an empty graph while awaiting a scene that is not rendered
  for empty topology. Final checks above passed. Dependency deprecation warnings
  appeared in backend tests; no test failures remain in the executed asset scope.

## Integration handoff / ownership

Changes are limited to asset routes in `networks.py`, asset schema/repository/service
code, frontend asset download/API/hooks/types/paging UI and related tests, plus this
handoff. Shared header JSON and new asset paging/hook tests must be included when
integrating the change. Concurrent owners' other worktree edits were preserved.
No commits were created.

This closes the source-level R02 mismatch and R08 bounded metadata mode. Browser
runs above use Vite development serving and mocked HTTP responses; the shared
fixture is checked against actual FastAPI headers, and PostgreSQL checks use real
storage transactions, but these are not production-build full-stack acceptance.
The coordinating integration owner still needs the ADR027 actual authenticated
HTTP/store/worker upload/reload/restore run against the final frozen build and
current0029 backup/fresh-restore evidence. Existing asset-volume provisioning and
backup requirements in `CompletionProgram/Assets.md` continue to apply. Global
tracking and CI integration belong to the coordinator.

## Integration follow-up: canonical geometry browser inspection (2026-09-21)

User expanded this owner's scope to investigate `spatial-geometry.spec.ts` and
rerun all70 browser tests plus assets under the upgraded frontend.

**Root cause reproduced:** the original test imported
`/node_modules/.vite/deps/@react-three_fiber.js`, whereas the application had loaded
`/node_modules/.vite/deps/@react-three_fiber.js?v=610534e2`. Browser ESM identity
includes the query, so the inspection created a second R3F instance with an empty
`_roots` registry. Diagnostic observation was one Canvas, five geometry labels,
and zero roots in the newly imported unversioned module. This was a test inspection
bug, not missing application geometry.

**Fix:** `frontend/tests/e2e/spatial-geometry.spec.ts` locates the exact loaded R3F
resource URL (including its Vite version) and imports that module. It requires one
unambiguous loaded module and the actual Canvas-owned root; root registration is
awaited for at most5s because canvas visibility precedes R3F initialization. Failure
to obtain a root throws instead of returning fabricated empty geometry. All original
assertions remain: five shapes, exact wall dimensions/world position, transparent
shell, unknown-shape omission, floor shape sets, clipping planes/labels, actual canvas
device picking, edited dimensions and final zero shapes after historical restoration.
No application rendering changes or weaker geometry assertions were introduced.

### Executed follow-up results

1. Original geometry test reproduced **0 versus5**. Exact-module fix passed the
   single geometry test; the first full run exposed the asynchronous root-readiness
   race, which was then corrected as above.
2. Initial full no-retry run: **55 passed /15 failed**, while installed dependencies
   were stale (Router6.30.4/Vitest3.2.7 despite upgraded manifest/lock). This run does
   not qualify the upgraded frontend. `npm ci --no-audit --no-fund` encountered a
   registry timeout; `npm ci --offline --no-audit --no-fund` then installed373
   packages successfully from the cache without changing the manifest/lock.
3. Confirmed installed versions: **React Router7.18.4, Vitest4.1.11, Vite6.4.3,
   R3F8.18.0**. Under these versions, `npm run typecheck` passed, the same six asset
   suites above plus `spatialGeometry.test.ts` passed **44 tests /7 files**, and
   scoped ESLint passed (including the repaired browser test).
4. Full upgraded browser command `npx playwright test --workers=2 --retries=0`:
   **54 passed /16 failed**. The corrected geometry test and every Twin/asset browser
   test passed. **The global70-test gate is not green.** Remaining failures:
   - `alert-audit-repair.spec.ts`: both cases;
   - `inventory-tenancy.spec.ts`: first21-row inventory case (dynamic overview
     module fetch failure);
   - `manual-lab-intent.spec.ts`: both cases;
   - `telemetry-history.spec.ts`;
   - `vs11-alerts-lifecycle.spec.ts`: first lifecycle case;
   - `vs13-reporting.spec.ts`: PDF, CSV and failed-job retry cases;
   - `vs19-frontend-continuity.spec.ts`, `vs2-telemetry.spec.ts`;
   - `vs3-reliability.spec.ts`: both cases;
   - `vs4-simulation.spec.ts`, `vs8-intent.spec.ts`.
5. Current backend focused asset rerun: **48 passed** using
   `poetry run pytest tests/unit/test_asset_service.py tests/unit/test_asset_pagination.py tests/integration/test_asset_endpoints.py -q --no-cov`.
   Scoped whitespace check passed.

**Coordinator finding:** several non-Twin failures have no selected workspace/network;
the reporting snapshot explicitly says `Workspace: not selected` and disables
generation. `tests/e2e/support/session.ts:1531`'s `loginFromUi` waits only for the
overview URL, then callers immediately navigate away before asynchronous ScopePicker/
InventoryPanel initialization can finish. That shared fixture/readiness path and the
overview dynamic-import failure require integration-owner investigation; this owner
did not edit shared login, unrelated feature tests, global configuration or UI.

**Source-stability notification:** owned Twin/asset source and the corrected geometry
test are stable for the coordinator's full-stack run. This handoff explicitly records
the remaining global browser failures rather than claiming70/70. No commits created.

## Release fixture and shared login closure — final green rerun (2026-09-21)

The user authorized this owner to fix the frontend-context fixture import and shared
`tests/e2e/support/session.ts` readiness race. This section supersedes the preceding
global-browser blocker status; the failed runs above remain as the investigation record.

- Moved the **single** cross-contract fixture to
  `frontend/src/test/fixtures/asset-download.json`. `assetDownload.test.ts` imports
  it through `@/test/fixtures/asset-download.json`; the backend endpoint regression
  resolves that same file from the repository root. The former backend fixture
  location is removed. Body/hash/header bytes are unchanged.
- Verified release inclusion: `deploy/manage.py`'s frontend tar-context allowlist
  accepts `.json` files below `frontend/` and does not exclude `src/test/fixtures`.
  `deploy/Dockerfile.frontend.dockerignore` includes `frontend/**`; the Dockerfile
  copies `frontend/` into `/build`. Thus frontend typecheck no longer needs any
  sibling backend directory. No deployment allowlist change was necessary.
- `loginFromUi` now waits for nonempty Organization and Workspace combobox values
  **and exactly one `button.network-choice[aria-pressed='true']`** after the overview
  URL. These are actual public UI scope-readiness assertions, not a delay, direct
  store injection, or an implicit click changing selection. They prevent callers
  from unmounting overview scope-initialization effects prematurely. No existing
  workflow/geometry assertions were removed or relaxed.

Final executed gates with the current lock installed (Router7.18.4, Vitest4.1.11,
Vite6.4.3, R3F8.18.0):

| Check | Actual result |
| --- | --- |
| `npx playwright test --workers=2 --retries=0` | **70 passed, 0 failed, 0 retries**, about2minutes |
| Six asset suites plus `spatialGeometry.test.ts` (command in follow-up above) | **44 passed /7 files** |
| `npm run typecheck` | Passed, including the relocated JSON import |
| `npm run lint` | Passed across the entire frontend |
| `npm run build` | Production build passed; existing chunk-size/mixed-import advisory warnings remain |
| Backend `tests/integration/test_asset_endpoints.py -q --no-cov` | **26 passed**, including actual-header comparison against the relocated fixture |
| Backend Ruff on the fixture reader and scoped `git diff --check` | Passed |

**Ready for deployment/full-stack rerun:** owned source, shared login readiness and
fixture layout are now stable; the previously failing16 browser cases all passed
in the complete zero-retry run. This is browser-fixture/source/build validation,
not a claim that a new Docker deployment or live full-stack acceptance already ran.
The coordinator must include the new frontend fixture when freezing source and
rerun the previously blocked frontend Docker build/deployment. No commits created.
