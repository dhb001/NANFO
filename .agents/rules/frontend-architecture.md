---
match: "frontend/**"
---
# Frontend Architecture

## Scope
Frontend composition, state management, routing, presentation structure, and realtime/Digital Twin UI integration.

## Canonical Reference
- `docs/architecture/Frontend.md` is the authoritative frontend architecture baseline.
- `docs/standards/UIDesignStandard.md` and `docs/standards/AccessibilityStandard.md` define mandatory UI quality bars.

## Rules
- Use feature-oriented folders; avoid large generic shared buckets that hide ownership.
- Keep global state minimal and explicit; prefer local state unless cross-feature coordination is required.
- Keep API interaction logic separated from view components.
- Enforce consistent error/loading/empty states for all async views.
- Preserve accessibility and keyboard navigation baselines for core workflows.
- Do not invent undocumented API/Event/WebSocket fields, channels, or lifecycle states.
- Keep Digital Twin scene data mapping separate from 3D rendering components.
- Use deterministic adapters/selectors for backend contract mapping.
- Enforce route-level code splitting and performance-safe rendering for dense engineer dashboards.

## Boundaries
- Do not encode backend business logic in UI components.
- Do not introduce alternate API envelope formats.
- Do not duplicate digital-twin-specific simulation semantics outside Digital Twin modules.
- Do not bypass documented auth/revocation checks for websocket channels.

## Completion Gate
Before closing any frontend step:
1. Contracts verified against docs/api and docs/features.
2. Lint/type checks pass for touched scope.
3. Targeted tests pass for state, components, and critical flows.
4. Realtime failure paths covered (disconnect, malformed payload, unauthorized).
5. Project tracking docs updated (CurrentSprint, DevelopmentJournal, DecisionLog).
