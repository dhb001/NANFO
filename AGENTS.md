# NANFO Agent Entry

This repository uses custom agent rules, workflows, and skills from the `.agents/` directory.

## Load Order
1. `.agents/rules/constitution.md`
2. `.agents/rules/architecture-guardrails.md`
3. Relevant domain rule files in `.agents/rules/`
4. Relevant feature PRD in `docs/features/`
5. Relevant ADR (when present)
6. Relevant standards files in `docs/standards/` (only when task-relevant)
7. `docs/project/CurrentSprint.md`
8. `docs/project/DevelopmentJournal.md`

## Behavior Requirements
- Follow architecture guardrails in `.agents/rules/architecture-guardrails.md`.
- Use context priority and conflict resolution from `.agents/rules/context-loading.md`.
- If instruction sources disagree, resolve conflicts using the precedence chain defined in `.agents/rules/context-loading.md`.
- Use workflow guidance from `.agents/workflows/design-feature.md`, `.agents/workflows/architecture-review.md`, and `.agents/workflows/implement-feature.md`.
- Apply execution quality rules from `docs/standards/AgentExecutionStandard.md` for context safety and hallucination reduction.
- Apply coding conventions from `.agents/rules/coding-standards.md`.
- Use testing and security rules from `.agents/rules/testing.md` and `.agents/rules/security.md`.

## Scope
- Backend: `.agents/rules/backend-architecture.md`
- Database/UEDF: `.agents/rules/database.md`
- AIOS: `.agents/rules/aios.md`
- Hypervisor: `.agents/rules/hypervisor.md`
- Simulation/Physics: `.agents/rules/physics-engine.md`
- Frontend: `.agents/rules/frontend-architecture.md`
- Digital Twin: `.agents/rules/digital-twin.md`
