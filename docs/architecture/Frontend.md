# Frontend Architecture

## Purpose
Define the canonical frontend architecture, implementation boundaries, and quality gates for NANFO.

## Scope
Applies to all UI work across Vertical Slices, including application shell, dashboards, forms, realtime channels, and Digital Twin 3D views.

## Frontend Principles
- Keep UI logic deterministic and testable.
- Treat backend contracts as source of truth; do not invent fields or alternate envelope formats.
- Keep state ownership explicit and minimal.
- Preserve performance and accessibility as first-class requirements.

## Canonical Structure

### App Layers
1. Presentation Layer
- Route views, feature pages, and visual components.

2. Feature Layer
- Feature-specific state selectors, orchestrators, and UI-level policies.

3. Data Layer
- API/WebSocket clients, request adapters, contract mapping, and cache invalidation logic.

4. Shared Layer
- Reusable primitives only (design tokens, base components, utility helpers).

### Folder Guidance
- Use feature-oriented grouping. Avoid large misc/shared buckets that blur ownership.
- Keep API/WebSocket clients out of visual components.
- Keep 3D scene composition isolated under Digital Twin feature modules.

## State Ownership Rules
- Local component state by default.
- Shared/global state only when cross-route or cross-feature coordination is required.
- Server state must be isolated from local UI state and synchronized through explicit cache/query mechanisms.

## Contract Rules (Anti-Hallucination)
- API envelope remains exactly `success`, `data`, `meta`, `errors`.
- Frontend must consume documented API/Event/WebSocket contracts only.
- Unknown fields from backend are ignored unless contract docs are updated.
- Do not create frontend-only domain enums for backend-owned workflow states.

## Realtime Rules
- WebSocket handlers must fail open: isolate malformed payloads and continue processing valid messages.
- Connection lifecycle must include reconnect/backoff, auth-expiry handling, and denial/revocation handling where required by API docs.
- Keep channel-specific mapping logic near the owning feature.

## Digital Twin 3D Rules
- Separate scene data mapping from rendering.
- Keep frame-loop work minimal and avoid expensive allocations in hot paths.
- Use level-of-detail and progressive rendering strategies for dense topology views.
- Do not place backend business rules in rendering components.

## UX and Accessibility Requirements
- Every async view must provide loading, empty, error, retry, and success states.
- Keyboard navigation is required for core operator workflows.
- Severity/risk states must be explicit and visually unambiguous.
- Layout must remain usable on desktop and laptop-class resolutions used by network engineers.

## Performance Baseline
- Route-level code splitting for major feature surfaces.
- Avoid unnecessary re-renders through memoization and stable selectors.
- Virtualize long lists and dense tables.
- Treat websocket bursts as backpressure-sensitive paths with bounded per-frame UI updates.

## Testing Baseline
- Unit tests: feature logic, selectors, adapters, and guards.
- Component tests: render-state transitions and interaction behavior.
- Integration/E2E tests: cross-feature flows, auth boundaries, realtime updates, and critical operator workflows.

## Implementation Safety Checklist
Before marking a frontend step complete:
1. Contract verification against docs/api and docs/features completed; `npm run api:check` shows the committed generated OpenAPI types match the backend schema (ADR-028).
2. Scoped lint/type checks pass.
3. Targeted unit/component/integration tests pass.
4. Realtime failure paths covered (malformed payload, disconnect, unauthorized).
5. CurrentSprint, DevelopmentJournal, and DecisionLog updated.
