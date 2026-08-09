# OPENCODE Runtime Contract for NANFO

This file is the authoritative startup contract when working in OpenCode on this repository.

## Required Context Load Order
Read these files in this exact order before proposing code changes:

1. AGENTS.md
2. .agents/rules/constitution.md
3. .agents/rules/architecture-guardrails.md
4. Task-relevant rules under .agents/rules/
5. Task-relevant feature PRD under docs/features/
6. Task-relevant ADR under docs/adr/
7. Task-relevant standards under docs/standards/
8. docs/project/CurrentSprint.md
9. docs/project/DevelopmentJournal.md
10. docs/project/KnownIssues.md

If two instruction sources conflict, follow the precedence rules from .agents/rules/context-loading.md.

## Non-Negotiable Execution Rules
- Preserve modular monolith boundaries and domain ownership.
- Respect C5 and C6 constraints from architecture and test rules.
- Do not invent APIs, events, claims, tables, or fields not defined in source-of-truth docs.
- Treat docs/api/API_STANDARD.md as canonical for response envelopes and error shape.
- Keep changes minimal and task-scoped.
- Never skip tests for touched scope.

## Required Session Flow
1. Summarize current state from CurrentSprint + DevelopmentJournal.
2. State assumptions and risks.
3. Propose step-by-step plan with explicit stop points.
4. Implement only the first approved step.
5. Run validation gates.
6. Produce handoff notes in DevelopmentJournal format.

## Validation Gate (Must Pass)
- Lint and static checks for touched modules.
- Unit tests for touched modules.
- Integration tests for touched endpoints or cross-module behavior.
- Migration checks if schema changed.
- Contract checks for API envelope/event payloads if relevant.

## Response Format Expectations
Always include:
- What changed
- Why it changed
- Files touched
- Tests run and results
- Follow-up risks

## Vertical Slice Continuity
Current milestone context:
- Vertical Slice 1: complete.
- Next milestone: Vertical Slice 2 (telemetry ingestion, topology deltas, digital twin baseline).

At session start, identify the first unfinished VS2 task from docs/project/CurrentSprint.md and proceed in narrow increments.
