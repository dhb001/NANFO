# ADR023 dimensioned geometry — frontend handoff

## Delivered (2026-09-20)

Authority: `docs/adr/ADR-023-operational-twin-runtime.md`, updated
`docs/api/SpatialScene.md` and `docs/architecture/Frontend.md`.

- Extended `frontend/src/shared/types/spatial.ts` and the Digital Twin boundary
  validator with optional exact box/slab/wall geometry. Dimensions are strict finite
  numbers in [0.000001, 1000000]m; material name/source and nullable 0–100dB attenuation
  follow the owning contract. Wall objects require a direct floor/room parent, cannot
  parent other objects and cannot associate an inventory device.
- `spatialGeometry.ts` maps explicit shapes, world bounds and floor ancestry using
  the existing local `T × Rz × Ry × Rx` convention. Box/slab X/Z are centered and Y
  begins at zero. Wall local X is 0..length, Y is 0..height, thickness centered on Z.
  Missing/null geometry produces no mesh. Removed the old unowned ground disc.
- `CanonicalGeometry.tsx` draws actual dimensions with translucent building/room
  shells; labels include wall material, attenuation unknown/value and supplied source.
  Labels are bounded to24, noninteractive and hidden above the cut plane. Complete
  material metadata also appears in the accessible hierarchy/server JSON view.
- Canonical floor selection isolates floor descendants and associated inventory
  devices/links. The optional cut height is view-only in the selected floor's local
  Y, including tilted floors. Schematic overlays, legacy buildings, asset models,
  measured-path arrows and RF samples are hidden in isolated canonical-floor view
  because they have no canonical floor-containment association. Clear the selection
  to show those layers again. No scene fields are changed by filtering/clipping.
- Camera framing and near/far bounds use transformed canonical size, not legacy
  campus dimensions. Selected-device focus retains a close near plane. Geometry
  cannot intercept device picking; the existing instanced device renderer remains.
  Canonical geometry also displays with an empty successful topology graph.
- Existing permission-aware JSON editing now validates dimensions/materials and has
  exact examples/coordinate guidance. Full-replacement confirmation, expected revision,
  conflict draft retention/rebase and history staging continue through existing routes.
  History diff now detects geometry removed by an older snapshot.
- Validation preserves **omitted geometry versus explicit null**. History restore
  does not manufacture keys. RF hashing already serializes supplied fields; new tests
  pin both the old backend artifact hash and an actual Python geometry-document hash.
  Dimension/material changes invalidate the scene binding without changing RF schemas.

## Verification

Run from `frontend/`:

```sh
npm run typecheck
npm run lint
npm test
npm run perf:bundle
npx playwright test tests/e2e/spatial-geometry.spec.ts tests/e2e/spatial-scene.spec.ts --retries=0 --workers=1
npx playwright test tests/e2e/twin-consistency.spec.ts tests/e2e/vs5-digital-twin.spec.ts --retries=0 --workers=1
```

- Typecheck and full ESLint pass; full Vitest suite **527 passed**, including101
  Digital Twin tests and four new geometry regression cases.
- New Chromium fixture exercises GET → validated JSON edit → PUT → actual WebGL
  mesh dimensions/world position → floor isolation/cut → instanced canvas picking →
  historical shape omission restore. It inspects the real R3F scene, not a duplicate
  test renderer. Screenshot `frontend/test-results/spatial-geometry-*/canonical-geometry.png`
  was inspected. Subsequent runs exposed fixture startup races (visible canvas before
  its R3F root existed, and meshes mounted before their first world-matrix update).
  The fixture now waits for real scene initialization/world transforms; the final
  no-retry Chromium rerun passed, followed by full ESLint.
- Existing five spatial browser cases pass: revision conflict/rebase, registration
  save/restore, history restore, backend-generated RF artifact import/invalidation,
  and1024-device instanced draw/picking benchmark. Six additional Twin import,
  reconnect/backpressure/denial and handoff browser regressions pass without retries.
- Production build and **all original bundle gates pass**: total JS gzip408.36KiB
  ≤410.16KiB; largest/Three209.49KiB ≤253.91KiB; largest non-Three51.67KiB ≤58.59KiB;
  TwinPage0.64KiB ≤6.84KiB. Initial geometry build exceeded the total budget; merging
  small always-used Twin-internal chunks into the already-lazy route content recovered
  headroom. No budget, bundler configuration or dependencies changed. Route-level
  lazy loading and on-demand measured-path panel remain.

## Integration boundary

Only assigned Digital Twin files, spatial shared types, new tests and this handoff
were edited. The backend agent owns schema/persistence/RF implementation and API docs.
No backend/config/dependency edits, migrations, shared-container changes or commits.
The one read-only backend check used the existing Poetry environment's
`spatial_document_hash` to verify the geometry fixture hash
`1d7b22578a26834421588d466ed182fde9bbb9f3e7bbea3d58952c6f9f6c7418`.

Browser fixtures verify UI/contracts, not deployed persistence or physical survey/RF
accuracy. General geometry is currently one mesh per explicit shape (device symbols
remain batched); the1024-device benchmark does not certify a10000-wall rendering rate.
The backend retains final scope and transformed numerical-resolution validation.
Parent integration can incorporate this handoff into shared sprint/journal/decision
tracking and deployed acceptance without conflicting edits to those shared files.
