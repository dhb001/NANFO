---
name: backend
description: Backend module boundaries, service/repository layering, and event-driven integration checks.
---
# Backend Skill

## When to use
- Backend feature implementation or review.
- Service boundary and dependency-injection decisions.

## Checklist
- Controller -> Service -> Repository separation preserved.
- No cross-module table joins.
- API contracts follow `docs/api/API_STANDARD.md`.
- Events and side effects are explicit and documented.
