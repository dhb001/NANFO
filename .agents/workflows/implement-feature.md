# Feature Implementation Workflow

**Description:** A structured sequence to implement new NANFO features safely.

1. **Understand Request:** Analyze the request and ask clarifying questions.
2. **Read Design Inputs:** Review relevant architecture docs, the Feature PRD, and relevant ADRs.
3. **Verify Design Handoff:** Confirm design artifacts exist (module impact notes, API contract, database-change notes, and risks). If missing for non-trivial work, run `design-feature` first.
4. **Read Standards:** Load task-relevant standards from `docs/standards/` and API policy from `docs/api/API_STANDARD.md`.
5. **Identify Modules:** List all affected frontend, backend, or AI modules.
6. **Search Existing Code:** Check the codebase to avoid duplicating logic.
7. **List Assumptions:** Document technical assumptions and risks.
8. **Produce Plan:** Generate a step-by-step implementation plan.
9. **Approval Gate:** Ask for approval only when requirements are ambiguous, changes are high-risk, or cross-module impact is unclear. Otherwise, proceed and document assumptions and risks.
10. **Implement:** Write the necessary code adhering to coding standards.
11. **Architecture & Quality Review:** Review against architecture guardrails.
12. **Definition of Done Validation:** Ensure the following checklist is met:
    - [ ] Tests pass
    - [ ] Architecture boundaries remain unbroken
    - [ ] Documentation / API specs updated
    - [ ] ADR updated (if required)
    - [ ] Project Sprint updated
    - [ ] Development Journal updated
    - [ ] No duplicate logic introduced
    - [ ] No leftover TODOs
    - [ ] Security rules validated
13. **Suggest Next Task:** Recommend the next logical roadmap step.