# Feature Design Workflow

**Description:** A structured sequence to design the architecture of a new feature before implementation begins.

1. **Read Constitution:** Review core engineering philosophy.
2. **Read Architecture:** Load the relevant domain architecture rules (e.g., backend, digital-twin).
3. **Read Feature PRD:** Ingest the specific requirements for the feature being designed.
4. **Read Standards:** Load task-relevant standards from `docs/standards/` and API conventions from `docs/api/API_STANDARD.md`.
5. **Identify Affected Modules:** List all components, services, and databases that will be impacted.
6. **Produce Architecture Diagram (If Needed):** Generate a PlantUML component diagram when structural communication or boundaries are changing.
7. **Produce API Contract:** Define the exact request/response JSON schemas needed.
8. **Produce Database Changes:** List required schema migrations or new tables.
9. **Identify Risks:** Document potential security, performance, or architectural risks.
10. **Wait for Approval:** Halt and request explicit approval before implementation begins.