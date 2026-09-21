# ADR-021 Twin frontend handoff

## ADR-022 history and persisted asset registration (2026-09-20)

Implemented after reading the published extensions in `docs/api/SpatialScene.md`
and `CompletionProgram/Assets.md`, including actual backend registration schema.

- History GET uses documented page/page_size20, descending metadata, origin/actor/
  recorded time. Revision-body GET validates the requested revision. Browse/diff
  compares current→historical additions/removals and changed object fields, with
  both full historical JSON and diff available. Pages are live, not frozen exports.
- Restore is two explicit steps: confirm staging over any local draft at the loaded
  current revision, then confirm the existing full-scene PUT. Historical revision is
  never sent inside `scene`. A concurrent write produces the existing409 retained-
  draft UX; no blind retry, decrement or history rewrite. Server scope validation
  still rejects old device references no longer eligible for the network.
- Registration uses exact persisted version1 translation/rotation/XYZ scale,
  meter/Y-up target and operator-entered source. Bounds mirror backend: translation
  ±1e6, rotation±2π, scale1e-6..1e6, source1..128 without NUL; extra fields reject.
  Nonuniform scale restores exactly. No legacy identity transform is synthesized.
- Apply registration remains local; Persist Model Asset sends the applied value
  (or explicit null if unregistered). Unapplied input edits are labeled local and
  are not silently saved. Saved status requires returned matching network/hash/
  size/registration metadata. Replacement uploads reset registration; restoration
  applies the saved transform only after bytes, size, SHA256 and mapping validation.
- New `local_cas` assets restore through protected binary identity GET. URLs are
  constructed from network/asset identity, never arbitrary download_path. Bearer
  auth/refresh, no redirects/cache, bounded streaming, header checks, current-session/
  context fencing and final SHA256 validation. Failed binary validation never falls
  back to inline bytes. Legacy inline/base64 restore remains compatible. The existing
  asset POST adapter preserves omission vs explicit null for other callers.
- Smaller Twin-owned orbit/pan/zoom controls recovered strict bundle headroom:
  drag orbit, right/shift-drag pan, wheel zoom, pinch+pan and keyboard arrows/±;
  reduced motion consumes deltas immediately, listener teardown is explicit.
  Camera focus now converges once instead of permanently fighting user navigation.

Files: added `SpatialHistoryPanel.tsx`, `spatialHistory.ts`, `modelRegistration.ts`,
`assetDownload.ts` and tests; extended existing spatial API/panel, model controls,
model-byte validator, page and controls. Authorized cross-feature edits are only
`frontend/src/features/networks/api.ts` and `frontend/src/shared/types/network.ts`.
Extended the owned new `frontend/tests/e2e/spatial-scene.spec.ts`.

Final scoped gate: **97 tests/24 files passed**, frontend typecheck and scoped
ESLint pass. Browser **5/5 passed, no retries/page errors**, including history
restore-as-new, protected binary restore and exact nonuniform saved registration,
plus RF and instanced picking. Binary corruption/size/denial/context races, history
conflict and pagination, registration bounds/legacy-null and controls teardown are
covered. Browser fixtures establish frontend behavior, not live backend acceptance.

Fresh production build: **409.77KiB /410.16KiB**, all5 original budgets pass;
no budget/config/lockfile changes. Initial ADR022 total412.87KiB failure was fixed
by the bounded controls replacement. Standard Vite warnings remain.

Integration needs history0022 and asset0023/routes/storage from owning backend
agents. Existing deployments and prior acceptance remain dated snapshots: this
work does not refresh deployed images or backup/restore acceptance. Latest dense
software-renderer fixture:73frames/6002.6ms, median83.3ms,p95100ms,4 instanced draws/
frame; same reference environment below, no hardware-performance claim.

## RF operator artifacts follow-up (2026-09-20)

- Active Twin no longer imports or renders the congestion-driven frontend coverage
  heuristic. Its old pure helper/tests remain historical code, unreachable from the
  view; there is no default synthetic RF layer or misleading coverage switch.
- **Operator RF samples** imports actual `evaluate_twin_physics.py spatial-rf`
  output `{rf_request, provenance, evaluation}`. Direct `rf` results are rejected:
  they lack explicit sample positions and canonical spatial provenance. No public
  endpoint, event or new backend wire contract was added.
- Strict exact-key validation, finite bounds, 1MiB/file,64 samples,256 walls per
  artifact, unique receivers and one RF config per import set. Imports are local,
  atomic per file selection and never save/activate anything.
- Requires current workspace/network, nonzero scene revision, explicit operator
  frame ID, exact axis-conversion version, canonical device/frame associations,
  ancestor accuracy evidence and scene-source hash. Recomputes Python-compatible
  canonical spatial/config/request SHA256 hashes (including float formatting,
  ASCII escapes and sorted object/wall IDs). Known actual Python CLI fixtures test
  interoperability. Unrepresentable/unsupported serialization mismatches fail closed.
- RF positions map back from RF(X,Y,Z) to Network(X,Z,-Y) in meters; purple sample
  symbols show modeled RSSI dBm and explicit assumed ±dB or unknown uncertainty.
  No inferred coverage surface, SINR, congestion, receiver placement or confidence
  interval. All samples have accessible text/provenance; at most24 scene labels.
- Imported samples are hidden immediately when their loaded canonical snapshot
  changes/becomes unavailable; reimport required. Model registration does not move
  canonical RF samples. Hash consistency is **not authenticity**: unsigned operator
  artifacts, external evidence and original adapter inputs cannot be independently
  authenticated from this output alone. `adapter_input_sha256` is retained as
  provenance, not claimed recomputed (the original adapter input is not exported).

### RF files and fresh checks

Added `rfArtifact.ts`, `RFImportPanel.tsx`, their tests and
`rfFixture.test-data.ts` under Digital Twin. Updated Twin page/scene and the new
`tests/e2e/spatial-scene.spec.ts`. To fit the original total bundle limit, added
small `SceneLabel.tsx` and `TwinOrbitControls.tsx` adapters and used them in
`DeviceInstances.tsx`/`CampusBuildings.tsx`/`TwinScene.tsx`. Removed general-purpose
HTML overlay/controls wrapper overhead; labels remain noninteractive, projected,
bounded and cleaned up, and orbit motion still respects reduced-motion preference.
RF is in the already lazy-loaded TwinPageContent route; a separate lazy RF chunk
was tried but increased total compressed bytes through cross-chunk duplication.

- Scoped frontend **87 tests passed /19 files**; typecheck and scoped ESLint pass.
- Browser **4/4 passed, zero retries/page errors**: conflict flow, registration,
  real backend-generated RF fixture import/render/invalidation, instanced picking
  and dense fixture. RF test explicitly sets the fixture workspace/network in the
  browser store to match actual CLI hashes; this is fixture behavior, not auth proof.
- Fresh production `npm run perf:bundle`: **409.90KiB /410.16KiB**, all5 limits pass;
  Three209.55KiB. Budgets/config/dependencies unchanged. Initial RF builds exceeded
  the budget; resolved through scene-helper reduction and route compression sharing.
- New label/controls adapters initially exposed browser lifecycle/Three-version
  differences; corrected DOM root lifecycle and explicit controls DOM assignment.
  All browser flows then passed, including actual RF label visibility.
- Latest bounded browser reference:90 frames/5813.3ms, median66.6ms,p95100ms,
  4 instanced draws/frame on the same Chromium151/SwiftShader/Ryzen environment
  documented below. This is not production-GPU performance acceptance.
- **Deployment acceptance remains the earlier explicitly dated snapshot.** This
  source/build/browser evidence does not refresh deployed-image acceptance; parent
  integration must build/deploy the new artifact and run its acceptance separately.
  No backend edits, deployment operations or shared tracking-doc changes here.

## Delivered

- Canonical GET/PUT integration lives entirely in Digital Twin; shared wire types
  are `frontend/src/shared/types/spatial.ts`. Uses the existing canonical-envelope
  API client, scoped React Query cache and request abort signal. No polling or
  invented spatial websocket event. Reload is explicit.
- Validated scene JSON import/editor, current revision and server JSON comparison,
  explicit confirmed full replacement, read/write permission gates, backend error
  display and retained drafts on conflicts/reload failures. A 409 blocks retry until
  the operator reloads and explicitly rebases (full replacement, not an automatic
  merge) or discards. Import and editing never save automatically.
- Validation follows the delivered backend `spatial_schemas.py`: bounded finite
  vectors, revision safe integers, unique object/device identity, ordered hierarchy,
  direct device parent for interfaces, UUID associations and provenance bounds.
  Unknown fields are ignored at the frontend boundary and omitted from PUT.
  Network/device membership remains a server-owned check.
- World transforms use backend column-vector `T × Rz × Ry × Rx`, composed through
  parents independent of object ordering. Three intrinsic ZYX constructs the local
  matrix; composed device orientation is converted to renderer XYZ. Canonical
  device coordinates override schematic coordinates and update link endpoints.
  Inventory IDs, selected IDs, existing imported spatial references and assets are
  retained. Selected canonical devices can be camera-focused at their actual position.
- Canonical hierarchy/parent IDs/provenance are inspectable with keyboard-accessible
  device selection. V1 has **no dimensions**: no canonical building/floor solids are
  fabricated. Removed inferred node-cloud building geometry from the renderer.
  Existing dimensioned campus imports remain separate; the UI identifies their
  separate frame, schematic device fallbacks and schematic live-overlay positions.
- Imported GLB/glTF has no automatic centering/scaling/vertical offset. Model
  geometry stays hidden until local translation, rotation and scale are explicitly
  applied. Registration is labeled **local, unsaved**; asset persistence does not
  persist it. Replacement/restore requires registration again.
- Owned glTF resources are deduplicated and released: geometry, material arrays,
  material/uniform textures, shared image bitmaps and skeletons. Covers validation
  parses, replacement, unmount and successful loads arriving after cancellation;
  cancelled callbacks cannot publish stale roots. Loader-owned primitives disable
  R3F automatic disposal to avoid competing ownership.
- Topology links now use one native line-segment buffer with explicit disposal and
  refreshed bounds rather than one fat-line helper per edge. Device bodies, congestion
  rings and alert outlines are instanced in compatible visual batches; batch-local
  instance indices map to canonical device IDs. No package, lockfile or budget changes.
- Selection radius/emissive, status emissive, alert outlines and congestion colors
  preserve `resolveDeviceVisual` exactly. Noninteractive rings/outlines cannot intercept
  picking. Bounds refresh on movement, filtering, regrouping and deletion.
- Distance-aware labels exclude ordinary devices beyond65m; selected and alerting
  devices retain priority within the24-label cap (selected label retains the existing
  zero-budget exception). Camera sampling is at most4Hz and only after2m movement.
  Geometry/picking remain stable at every distance; no animated LOD transitions.
- Removed both adapter-side global240-key truncation and the independent12-series
  cutoff. The store owns resource/series bounds; flow history is excluded from
  congestion so it cannot obscure valid retained metrics. Regression includes271
  resources,300 newer flow records and15 noncongestion series ahead of the quiet
  device's recognized metric.

## Files

Under `frontend/src/features/digitalTwin/`:

- Added `spatialScene.ts`, `spatialApi.ts`, `spatialHooks.ts`,
  `SpatialScenePanel.tsx`, `ModelRegistration.tsx`, `modelResources.ts`.
- Added tests `spatialScene.test.ts`, `spatialApi.test.ts`,
  `SpatialScenePanel.test.tsx`, `modelResources.test.ts`.
- Follow-up adds `DeviceInstances.tsx`, `deviceInstances.ts`,
  `deviceInstances.test.ts`; updates `deviceVisuals.ts`, `hooks.test.ts` and
  `SpatialScenePanel.tsx`. New browser file:
  `frontend/tests/e2e/spatial-scene.spec.ts`.
- Updated `TwinPageContent.tsx`, `TwinScene.tsx`, `sceneAdapter.ts`,
  `modelAsset.ts`, `TwinPage.test.tsx`.

Also added `frontend/src/shared/types/spatial.ts` and this handoff. Shared realtime
store/bridge/hooks, other feature implementations and central tracking docs belong
to the other workstreams and were not edited here.

## Verification (2026-09-19)

- `npm test -- src/features/digitalTwin`: **82 passed**, 17 files. Tests exercise
  multi-axis/nested transforms, exact envelope/request, malformed inputs, conflict
  retention/rebase, role revocation, import/reload failures, selected-ID/import
  preservation, registration reset, GPU deduplication and cancelled/late loads,
  real Three raycasts after reorder/deletion/movement, rotated ring transforms,
  visual batching parity, label distance policy and telemetry fairness.
- `npm run typecheck`: **passed** on final rerun. A test-only unsupported Testing
  Library `exact` option was corrected; affected TwinPage tests reran **13/13 passed**.
- `npx eslint src/features/digitalTwin tests/e2e/spatial-scene.spec.ts`: **passed**.
- Scoped `git diff --check`: **passed**.
- `npm run perf:bundle`: **all five original limits pass**, total JS gzip
  **409.72 KiB / 410.16 KiB**, Three **216.18 KiB / 253.91 KiB**.
  Initial total-budget failure (414.08 KiB) was resolved by the link-buffer change,
  not by loosening limits. Standard Vite large-chunk/static+dynamic-import warnings
  remain. Budget includes concurrently edited realtime code at the time of build.
- An initial API test reused an already consumed mock Response; corrected to return
  a fresh Response per request. Final scoped test run has no failures/warnings.
- `npx playwright test tests/e2e/spatial-scene.spec.ts --workers=1 --retries=0`:
  **3 passed**, no page errors. Canonical GET/PUT409→reload→explicit rebase→save,
  retained selected ID, keyboard registration and replacement reset, actual instanced
  canvas picking, paginated1024-node fixture, bounded labels and runtime sampling.
  These validate browser fixture correctness, not backend concurrency/authorization.
- Initial browser runs exposed a real link-buffer cleanup crash: `dispose={null}`
  on a raw BufferGeometry primitive overwrote its dispose method. Removed that
  property (primitives are already exempt from R3F disposal); explicit ownership
  remains. Browser rerender/save/import flows now guard against page errors.
  Added explicit textarea aria-label for consistent browser naming.
- No commits, live infrastructure or live backend acceptance were performed.

### Dense-scene reference measurement

Final serialized browser run, Vite development build, headless Chromium151.0.7922.34,
Linux7.2.6-arch2-1, AMD Ryzen5 5625U,12 logical CPUs,1440×1000 viewport,DPR1,
ANGLE Vulkan1.3 SwiftShader (software renderer), reduced-motion enabled.

Fixture:1024 switch symbols, congestion rings enabled,24-label budget/65m ordinary
label cutoff, selected origin device, no links/AP coverage/imported models. Benchmark
wraps WebGL2 `drawElementsInstanced` only in the test; no production instrumentation.
Sampling stops at90 frames or6s (one terminal frame may exceed6s).

| Observation | Final run |
| --- | ---: |
| Sampled frames / elapsed | 84 / 6060.4ms |
| Median / p95 frame interval | 66.7ms / 100.1ms |
| Instanced draws / frame | 336 / 84 = 4 |
| Submitted instances | 172032 (2048/frame:1024 bodies +1024 rings) |

Reference JSON is emitted to the Playwright log and attached as
`dense-scene-reference.json`. No baseline-speedup or60-FPS claim: software rendering
is slow, development overhead remains, and CPU picking still iterates instances.
Real-GPU production-build acceptance and varied geometry/alert/coverage loads remain.

## Integration and remaining performance work

1. Parent integration must mount the spatial router and migrate Network0021 before
   live GET/PUT acceptance. The delivered router returns the validated scene snapshot
   on both methods, matching this client. Verify real membership denial and competing
   writes in the isolated lab; frontend tests use fixture responses.
2. No asset-registration API extension exists. Registration intentionally resets on
   reload/model replacement; persisting it needs a separately specified asset field
   or endpoint extension. Existing GeoJSON frame/georegistration remains distinct.
3. Dimensions/footprints and their transform convention need a future canonical
   schema before building/floor solids can be rendered from canonical objects.
4. Device instancing and distance-label LOD are delivered. Remaining: spatially
   partitioned batches (current frustum culling is per visual batch), geometry LOD,
   accelerated picking, occlusion, hierarchy-list virtualization and real-GPU
   frame/GPU-memory acceptance. No60-FPS claim is made. Bundle headroom is about
   0.44KiB; retain the existing limit during parent integration.
5. Successful late loads are disposed immediately, but GLTFLoader has no public
   complete cancellation/partial-parser-resource interface. Browser acceptance should
   include malformed asset failures and repeated textured imports; pending fetch/decode
   work may finish before cleanup. Bitmap closure is covered by deterministic spies.
6. Parent agent owns realtime malformed/disconnect/unauthorized regression gates and
   final aggregate checks. Canonical scenes remain explicit snapshot/reload data;
   telemetry and simulation/intent deltas retain existing contracts.
