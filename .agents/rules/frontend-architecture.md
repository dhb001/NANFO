---
match: "frontend/**"
---
# Frontend Architecture

## Scope
Frontend composition, state management, routing, and presentation structure.

## Rules
- Use feature-oriented folders; avoid large generic shared buckets that hide ownership.
- Keep global state minimal and explicit; prefer local state unless cross-feature coordination is required.
- Keep API interaction logic separated from view components.
- Enforce consistent error/loading/empty states for all async views.
- Preserve accessibility and keyboard navigation baselines for core workflows.

## Boundaries
- Do not encode backend business logic in UI components.
- Do not introduce alternate API envelope formats.
- Do not duplicate digital-twin-specific simulation semantics outside Digital Twin modules.
