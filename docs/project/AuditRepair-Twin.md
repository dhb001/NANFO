# ADR-026 workstream 6 — guided Digital Twin editing

## Scope and contracts

Implemented within `frontend/src/features/digitalTwin` using the existing Network
inventory, device-group, asset and canonical spatial-scene contracts. Reviewed
ADR-026, the audit capability map, Frontend.md, Network PRD and SpatialScene.md.
Existing uncommitted Twin rendering, geometry, RF, registration, history and asset
validation work is preserved. No dependencies, backend/schema changes or shared
inventory/type/style/tracking edits are part of this workstream.

## Operator workflows

- `GuidedSceneEditor.tsx`: object creation/edit/removal; explicit IDs, parent/type,
  local position/rotation, provenance/unknown accuracy, box/slab/wall dimensions,
  wall material/source/unknown attenuation and actual inventory association.
  New transforms/dimensions are blank until supplied. Existing omitted geometry
  remains absent; explicit null stays null. Existing validation checks hierarchy,
  duplicate IDs/device references, type/geometry compatibility and numeric bounds.
- Stage objects into the same full-replacement draft used by the advanced JSON
  editor. Unstaged guided fields block saving. Save still requires confirmation and
  the original expected revision;409 retains the draft and requires explicit
  reconciliation/rebase. History imports and server JSON comparison remain available.
- `TwinInventoryPicker.tsx`: explicit20-item inventory pages using existing
  `listDevices(token, networkId, page, 20)`, authoritative totals, loading/error/retry
  and empty states. Selection survives paging; this does not use a partial topology
  graph or silently treat the first20 devices as the complete inventory.
- `CustomGroupEditor.tsx`: create or select existing custom groups, stable immutable
  keys during editing, names/descriptions and explicit membership. Saves one group
  with `replaceExisting:false`, preserving unrelated groups and off-page members.
  Existing selectors are preserved and displayed; a confirmed local action can
  clear them to use explicit membership only. No implicit selector inference.
  Save requires current write permission/scope and confirmation; failures retain
  inputs and explain that the outcome should be checked before retrying.
- Persisted asset selector exposes all records returned by the existing list API,
  identity/date/source/hash/size metadata, reload and explicit chosen restore.
  Restore re-fetches and resolves that exact asset ID (never a latest fallback),
  confirms replacement and retains prior local imports on cancel/validation failure.
  Existing size/SHA-256/registration/network/mapping validation and URL cleanup apply.
  New asset saves use `replace_existing:false` so other available assets survive.
  This is available-asset history; the API does not expose previously soft-replaced
  assets or immutable versions of an upserted asset record.
- Existing route-level lazy loading and generation/user/org/workspace/network reset
  key remain. Token rotation does not remount editors; local guided and JSON drafts
  remain. Collapsing an opened editor retains its draft. Scope changes still reset.

## Verification

- Full owned Twin suite:107 tests passed across26 files. After the final selector
  control and exact-wire regression,34 targeted tests passed across6 files
  (`GuidedEditing`, `groupPersistence`, `TwinPage`, `SpatialScenePanel`, `modelAsset`,
  `assetDownload`). Final typecheck, touched-file ESLint and whitespace checks passed.
- `npm run typecheck`: passed. Initial concurrent Reliability test type errors were
  resolved by that workstream; this workstream did not edit those files.
- ESLint on touched Twin implementation/tests: passed.
- Production build succeeded. `npm run perf:bundle` **failed aggregate budget**:
  shared-tree419.34KiB JS gzip versus unchanged410.16KiB limit. Largest non-Three
  chunk49.48KiB, Three209.49KiB, Twin route0.66KiB all pass individual caps.
  This measurement includes concurrent workstreams and is not an isolated Twin
  delta. Parent integration must optimize aggregate size; no limits were increased
  and extra lazy chunks are not claimed as a total-size solution.
- Regression coverage: guided box/slab/wall/material validation, invalid parent,
  unknown/omitted fidelity, device selection on page2, retained revision through
  token rotation/conflict/reload, route scope reset, older selected asset restore,
  local replacement cancellation/URL cleanup, custom membership across pages,
  exact stable-key non-destructive payloads and failed-draft retention.

Browser end-to-end and aggregate performance closure remain parent integration gates.

## Deletion-usability follow-up

- Read `AuditRepair-Network.md` restrictions and ADR-026's approved asset retirement
  clarification. `assetLifecycle.ts` owns the new DELETE client, uses the existing
  no-content/auth-refresh client and expects204. No shared Network API edits.
- `TwinLifecycleControls.tsx` is outside the topology data gate so even an empty
  topology can select/retire blocking assets or clear active groups/buildings.
  Selected retirement confirms name/ID/network, preserves selection on errors,
  rechecks identity/scope/authority, refreshes persisted metadata and reports
  ambiguous failure without claiming deletion. Late responses cannot act in a new
  network/session. An unchanged local restore of that exact asset is cleared;
  unrelated imports, edited registrations/mappings and historical evidence remain.
- Explicit clear-all controls send exactly `{replace_existing:true,groups:[]}` or
  `{replace_existing:true,buildings:[]}` through approved upsert clients. Confirmation
  states that all active records, including unrelated records of that kind, are
  cleared; no cascading inventory/model action is initiated.
- Selected group editing now includes noncustom groups while preserving their type.
  Final-member/selector removal remains a local draft action. Empty group definitions
  are rejected by the backend, so “Remove selected persisted group” reads a complete
  fresh list, reviews retained keys and replaces it without the chosen key. Other
  definitions/selectors/members are copied exactly. Confirmation explicitly states
  the existing endpoint's lack of CAS and concurrent-replacement risk.
- New `twin-guided-lifecycle.spec.ts` exercises the real UI using HTTP contract
  fixtures: guided box→confirmed scene PUT,21st inventory member→exact group POST,
  older chosen asset restore/retire, unrelated local import preservation, retiring
  the currently restored model, and exact empty group/building replacement requests.
  Chromium passed with `--retries=0 --workers=1` (1 test; no page errors). Initial
  locator failures were corrected for the inventory edit/delete buttons and native
  select accessible names; the passing run used no force clicks or hidden state edits.
- No edits to TwinScene, performance imports/catalog or Vite configuration. Parent
  retains full-suite, deployed backend and final aggregate performance checks.
- Final follow-up gates:27 targeted tests passed across `TwinLifecycleControls`,
  `GuidedEditing`, `TwinPage`, and `groupPersistence`; full TypeScript check,
  touched-file/browser-spec ESLint and whitespace checks passed.

## P2 authority-contention retry correction

- Verified `backend/app/modules/organization/service.py` returns HTTP409 with exact
  code `ORG_AUTHORITY_BUSY` and message “Organization authority is changing. Retry
  the operation.” Spatial CAS uses `SPATIAL_REVISION_CONFLICT` in
  `backend/app/modules/network/spatial_service.py`.
- `SpatialScenePanel` now enters revision-conflict mode only for409 with
  `SPATIAL_REVISION_CONFLICT`. Authority contention displays the backend error and
  retains the exact draft and expected revision with saving still available;
  it never automatically retries or rebases.
- Added a component regression: busy save → reload unchanged revision3 → explicit
  confirmed retry sends the identical nonempty scene at expected_revision3 and
  succeeds as revision4. Genuine CAS conflict remains blocked even after a
  same-revision reload, then requires explicit rebase when a newer revision loads.
- Verification:12 component tests passed (`SpatialScenePanel`, `GuidedEditing`),
  full typecheck and touched-file ESLint passed. No performance files changed.
