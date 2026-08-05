# Architecture Review Workflow

**Description:** A structured pre-merge design review for significant features.

1. Read relevant ADRs.
2. Read the target Feature PRD.
3. Read affected architecture documents and domain rules.
4. Identify conflicts with existing architecture decisions.
5. Identify module boundary violations.
6. Check API compatibility against `docs/api/API_STANDARD.md` and related API docs.
7. Check event compatibility against `docs/api/EventAPI.md` and module contracts.
8. Check data model impact and ownership boundaries.
9. Recommend one outcome: approve, approve-with-conditions, or changes-required.

## Output Requirements
- Findings ordered by severity.
- Explicit references to impacted files/contracts.
- Clear decision recommendation with rationale.
