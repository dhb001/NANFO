# NANFO Agent Entry

This repository uses custom agent rules, workflows, and skills from the `.agents/` directory.

## Academic Proposal and Documentation Source of Truth
- For the NANFO proposal, thesis/report, references, academic figures, or Chapters 1–6, first load `docs/standards/AcademicDocumentationGuide.md`.
- That file records the student's primary course instructions from **How to Write a Research Proposal & Documentation**, author `komondi@strathmore.edu`, and the student's subsequent explicit overrides. Apply these before generic IEEE writing conventions or earlier generated proposal versions.
- The single working document is `ISPR2/Revised/Chapters_1_3_Reviewed/NANFO_Chapters_1_3_Reviewed.odt`; despite its filename, it continues through Chapter 5. Continue edits in that document instead of creating standalone chapter documents or extra revision folders. Chapter 4 contains twelve black-and-white figures; architecture (4.5) and software classes (4.6) use landscape pages. Editable draw.io files and SVG/PNG exports are in the adjacent `Chapter_4_Diagrams/` folder. Free-standing diagram labels must remain transparent and clear of connector strokes; inspect both source images and final document pages. Omit AI-assistance/preparation commentary from the report as explicitly requested; the diagram-stage log is separate. Retain the Chapter 3 methodology lifecycle and original Gantt chart; appendices contain their items and captions only.

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

## Frontend Source Of Truth
- For frontend tasks, always load `docs/architecture/Frontend.md` and apply its structure, contract, performance, and testing gates before implementation.

## Remaining VS Pointer
- Authoritative post-VS8 remaining-work plan: `docs/project/CurrentSprint.md` (`Post-VS8 Plan` and `Remaining Work Master Checklist`).
- Before implementation, load this section to identify the first unfinished planned slice and respect its scope boundaries.
