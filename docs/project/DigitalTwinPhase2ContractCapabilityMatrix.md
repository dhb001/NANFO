# Digital Twin Phase 2 Contract and Capability Matrix

## Purpose
Document Phase 2 Digital Twin frontend capabilities and show that each capability is implemented on existing approved contracts only.

## Scope Boundaries
- Frontend-only implementation; no backend endpoint/channel/event expansion.
- Canonical REST envelope remains `success/data/meta/errors`.
- Existing WebSocket channel registry and delta payload contracts remain unchanged.

## Matrix

| Capability | Existing Contract Source (no expansion) | Frontend Implementation Evidence | Validation Evidence |
| --- | --- | --- | --- |
| Canonical congestion policy (`v2.0.0`) with deterministic rule priority (`loss > latency > util > cpu`) | `frontend/src/shared/types/ws.ts:26`, `frontend/src/shared/types/ws.ts:38`, `docs/api/WebSocket.md:73`, `docs/api/WebSocket.md:129` | `frontend/src/features/digitalTwin/sceneAdapter.ts:12`, `frontend/src/features/digitalTwin/sceneAdapter.ts:25`, `frontend/src/features/digitalTwin/sceneAdapter.ts:295`, `frontend/src/features/digitalTwin/sceneAdapter.ts:309`, `frontend/src/features/digitalTwin/TwinPage.tsx:413` | `frontend/src/features/digitalTwin/sceneAdapter.test.ts:54`, `frontend/src/features/digitalTwin/sceneAdapter.test.ts:111`, `frontend/src/features/digitalTwin/TwinPage.test.tsx:183` |
| Bounded congestion aggregation and deterministic tie-breaking from newest-first telemetry keys | `docs/architecture/Frontend.md:67`, `docs/api/WebSocket.md:75` | `frontend/src/features/digitalTwin/sceneAdapter.ts:68`, `frontend/src/features/digitalTwin/sceneAdapter.ts:69`, `frontend/src/features/digitalTwin/sceneAdapter.ts:399`, `frontend/src/features/digitalTwin/sceneAdapter.ts:478`, `frontend/src/features/digitalTwin/hooks.ts:18`, `frontend/src/features/digitalTwin/hooks.ts:50` | `frontend/src/features/digitalTwin/sceneAdapter.test.ts:145`, `frontend/src/features/digitalTwin/hooks.test.ts:96` |
| Deterministic overlay ordering with `simulation_state` before `intent_state` and stable overlay keys | `docs/api/WebSocket.md:157`, `docs/api/EventAPI.md:81`, `docs/api/EventAPI.md:86` | `frontend/src/features/digitalTwin/sceneAdapter.ts:578`, `frontend/src/features/digitalTwin/TwinScene.tsx:173` | `frontend/src/features/digitalTwin/hooks.test.ts:128`, `frontend/src/features/digitalTwin/sceneAdapter.test.ts:201` |
| Spatial mapping persistence uses existing device PATCH contract only | `backend/app/api/v1/networks.py:131`, `backend/app/modules/network/schemas.py:53`, `docs/api/API_STANDARD.md:9`, `frontend/src/features/networks/api.ts:51` | `frontend/src/features/digitalTwin/TwinPage.tsx:236`, `frontend/src/features/digitalTwin/TwinPage.tsx:510`, `frontend/src/features/networks/hooks.ts:63`, `frontend/src/features/networks/hooks.ts:81` | `frontend/src/features/digitalTwin/TwinPage.test.tsx:272`, `frontend/tests/e2e/vs5-digital-twin.spec.ts:126`, `frontend/tests/e2e/vs5-digital-twin.spec.ts:207` |
| Intent handoff enrichment reuses existing `/ops/intent` workflow and existing Intent API scope | `docs/features/IntentEngine.md:19`, `docs/features/IntentEngine.md:21`, `docs/api/WebSocket.md:159` | `frontend/src/features/digitalTwin/TwinPage.tsx:105`, `frontend/src/features/digitalTwin/TwinPage.tsx:270`, `frontend/src/features/intent/IntentPage.tsx:170`, `frontend/src/features/intent/IntentPage.tsx:220` | `frontend/src/features/digitalTwin/TwinPage.test.tsx:227`, `frontend/src/features/intent/IntentPage.test.tsx:80`, `frontend/tests/e2e/vs5-digital-twin.spec.ts:84` |
| Route-level lazy loading for Twin scene with unchanged contract behavior | `docs/architecture/Frontend.md:64`, `docs/architecture/Frontend.md:65` | `frontend/src/features/digitalTwin/TwinPage.tsx:36`, `frontend/src/features/digitalTwin/TwinPage.tsx:441` | `frontend/src/features/digitalTwin/TwinPage.test.tsx:59` |
| Session-vs-persisted mapping behavior is explicit and operator-visible | `docs/api/API_STANDARD.md:9`, `docs/features/Topology.md:16`, `backend/app/modules/network/schemas.py:54` | `frontend/src/features/digitalTwin/TwinPage.tsx:431`, `frontend/src/features/digitalTwin/TwinPage.tsx:437`, `frontend/src/features/digitalTwin/TwinPage.tsx:645`, `frontend/src/features/digitalTwin/TwinPage.tsx:649` | `frontend/src/features/digitalTwin/TwinPage.test.tsx:223`, `frontend/tests/e2e/vs5-digital-twin.spec.ts:202` |

## Contract Compliance Notes
- REST envelope compatibility is preserved (`docs/api/API_STANDARD.md:9`).
- WebSocket channel scope remains the canonical set with no new channels (`docs/api/WebSocket.md:15`, `docs/features/Telemetry.md:22`).
- Event naming and routing remain unchanged; existing simulation/intent lifecycle mappings are reused (`docs/api/EventAPI.md:14`, `docs/api/EventAPI.md:74`).

## Gate Evidence (2026-08-18)
- `npm run lint`: PASS
- `npm run typecheck`: PASS
- `npm run test`: PASS (`25` files, `100` tests)
- `npm run test:e2e`: PASS (`19/19`)
- `npm run build`: PASS (existing large `three` chunk warning unchanged)
- `npm run perf:bundle`: PASS (`total_js_gzip_kb=404.85`, `largest_chunk_gzip_kb=248.61`, `largest_non_three_chunk_gzip_kb=52.79`, `three_chunk_gzip_kb=248.61`, `twin_page_chunk_gzip_kb=6.68`; bounded checks true)

## Residuals (Accepted)
- Imported model and sidecar mapping remain session-local until explicitly persisted per node.
- Binary 3D asset persistence remains out-of-scope without approved backend contract/ADR.
