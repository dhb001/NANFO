# ADR-026 — frontend performance integration

Date: 2026-09-20. Owner: performance integration workstream.

## Owned files and plan

- `frontend/vite.config.ts`: inspect explicit vendor roots, tree shaking and safe
  minifier settings; retain route-level splitting and production safeguards.
- `frontend/src/features/digitalTwin/threeCatalogue.ts` and `.test.ts`: explicit
  JSX constructor registration for Fiber Canvas plus completeness/vendor-contract
  regression. GLTF imports and Fiber lifecycle remain intact.
- `frontend/tests/e2e/production-twin.spec.ts`: browser regression using public UI
  only, runnable against either dev or production preview (no dev-module imports).
- `docs/project/AuditRepair-Performance.md`: coordination and validation evidence.

The aggregate JS gzip cap remains the original **420,000 bytes (410.16 KiB)**.
Other continuity limits and their checker remain authoritative. Start by measuring
the integrated feature work, then remove unused build roots and verify the emitted
module graph. No API or feature behavior changes are planned. The main risk is
vendor chunk initialization/loading, so validate the production build as well as
types, lint and retained feature regressions. Shared tracking is handed to the
parent integrator through this note.

## Result — bundle gate PASS

Local integrated baseline: **419.77 KiB** (reported upstream: 419.34 KiB).
Final repeated production build: **385.76 KiB**, saving **34.01 KiB**, with
**24.40 KiB** headroom below the original cap. All five continuity checks pass:

| Check | Observed KiB | Original maximum KiB |
| --- | ---: | ---: |
| Aggregate JS gzip | 385.76 | 410.16 |
| Largest chunk | 188.06 | 253.91 |
| Largest non-Three chunk | 51.67 | 58.59 |
| Three chunk | 188.06 | 253.91 |
| Twin page entry | 0.66 | 6.84 |

36 JS chunks remain, including every feature route. Build output identifies
`three-BojFpM74.js`, `react-g7Mixs3q.js`, and `TwinPageContent-DM-RptOe.js`.

## Implementation rationale

- Removed the unused Drei manual-chunk root. No application imports use Drei.
- Co-located the retained GLTFLoader with Three, improving compression and removing
  its conflicting static/dynamic-import chunk warning.
- Fiber8 Canvas calls `extend(THREE)`, retaining the entire Three export namespace.
  A build-only, importer-specific Vite resolver gives **only that Canvas entry**
  the 18 constructors actually used by scene JSX. Fiber's other Three imports,
  application imports and GLTFLoader all resolve the original package. Canvas's
  lifecycle, context bridge, resizing, error boundaries and event handling remain
  the original library implementation. No duplicated renderer or new dependency.
- Catalogue tests parse all Digital Twin TSX, require every non-DOM JSX constructor
  to be registered with its original Three identity, and verify the installed Fiber
  entry only uses its namespace for `extend(THREE)`. Future JSX/library changes
  therefore require explicit review instead of silently losing scene elements.
- Compression experiments (extra Terser passes/module settings, hoisting and Three
  source alias) were insufficient or larger and were reverted. Original ES2022,
  Terser two-pass settings, source maps and warnings are retained. Continuity checker,
  limits, package dependencies, feature implementations and existing tests unchanged.

## Verification and retained-feature evidence

Commands from `frontend/`:

- `npm run perf:bundle`: PASS, final result above reproduced after all owned edits.
- `npm run typecheck`: PASS (application and Node/build configuration).
- `npm run lint`: PASS (whole frontend).
- `npm test`: **92 files / 559 tests passed**. This includes all557 existing tests
  plus2 catalogue regressions. Coverage includes guided geometry/groups, asset
  verification/cleanup, inventory, tenancy, histories, token rotation, revocation,
  intent approvals, STOP dominance, realtime and the original bundle-limit tests.
  Initial catalogue test development had2 failures (DOM detection and test environment),
  corrected before the full green rerun.
- `git diff --check -- frontend/vite.config.ts`: PASS.
- Production browser command:
  `npx playwright test --config /tmp/opencode/performance-playwright.config.ts production-twin.spec.ts`:
  **1 passed**, no retries. Uses actual emitted production assets via an owned Vite
  preview on127.0.0.1:4189, automatically stopped after tests. Canonical floor/wall
  rendering, clipping, instanced device selection, real self-contained triangle
  glTF parsing/material creation, local model registration and route cleanup pass
  with zero page errors. Uses public UI, no dev-only module imports.
- Production inventory/tenancy and alert/audit tests: **13 passed** in the broader
 23-case run below. Real CRUD UI/pagination,403/422/503 errors, ambiguous outcomes,
  org-authority restrictions, audit details and server-side alert filtering retained.
  These are browser contract fixtures, not live backend acceptance.

## Parent integration handoff

The broader production-preview attempt was:

`npx playwright test --config /tmp/opencode/performance-playwright.config.ts twin-consistency.spec.ts spatial-scene.spec.ts inventory-tenancy.spec.ts alert-audit-repair.spec.ts scenario-operator.spec.ts`

Result: **13 passed / 10 failed**. Every failure stopped before entering the feature:
the pre-existing `getByRole("button", { name: /Network A/ })` now matches the network
choice plus newly implemented Edit/Delete buttons. Parent test integration should
scope these selectors to the network-choice control (e.g. `pressed: true` for the
selected fixture network). Files: `scenario-operator.spec.ts`, `spatial-scene.spec.ts`,
`twin-consistency.spec.ts`. Also some spatial specs explicitly import `/src/...`
or `/node_modules/.vite/...` and need their existing dev-server lane; those are not
production-preview compatible. The new owned Twin test provides production coverage
without changing or dropping these existing tests. The later successful focused
run replaced the earlier output directory; the failure details remain in the
captured command output, rather than in retained trace files.

Parent owns mobile CSS/shared project tracking and full integrated E2E closure.
This workstream edited only the five owned repository files listed above; no commit.
