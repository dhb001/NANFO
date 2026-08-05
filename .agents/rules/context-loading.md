# Context Loading Priority & Conflict Resolution

## Loading Order
Always load and process context in this strict order:
1. `constitution.md`
2. `architecture-guardrails.md`
3. Relevant domain rule (backend / aios / hypervisor / physics)
4. Relevant Feature PRD (Product Requirements Document)
5. Relevant ADR (Architecture Decision Record)
6. Relevant standards file(s) when task touches API style, documentation quality, logging, monitoring, accessibility, or error handling.
7. `docs/project/CurrentSprint.md`
8. `docs/project/DevelopmentJournal.md`
9. Load only the minimum documentation required for the current task to preserve context window efficiency.

Only load documents relevant to the current task. Do not load unrelated architectural domains.

## Conflict Resolution
If documentation conflicts, follow this exact chain of authority:
1. ADR (Highest Priority)
2. Constitution
3. Architecture Rules
4. Feature PRD
5. Coding Standards
6. Workflow (Lowest Priority)