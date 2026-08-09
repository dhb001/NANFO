# PR Quality Checklist (NANFO)

Use this checklist before opening or merging any PR.

## 1) Scope and Intent
- Change is limited to declared objective.
- Out-of-scope refactors are excluded.
- Decision and trade-off are documented when behavior changes.

## 2) Architecture and Ownership
- Modular boundaries are preserved.
- No forbidden cross-module data access.
- C5 constraint respected for workspace/org boundaries.
- C6 deferred endpoints remain deferred unless explicitly planned.

## 3) API and Contract Integrity
- API responses follow canonical envelope.
- Error codes and status mapping are consistent with standards.
- Event names and payloads follow Event API conventions.
- WebSocket channels and payload schemas remain canonical.

## 4) Security and Access Control
- AuthN/AuthZ paths are covered by tests.
- JWT claims handling follows documented model.
- No secrets hardcoded or leaked in logs.
- Input validation and failure paths are explicit.

## 5) Data and Migration Safety
- Schema changes have an Alembic migration.
- Migration has safe upgrade path and clear downgrade behavior.
- Seed data changes are deterministic and idempotent when required.
- Data ownership rules from ADR and database standards are preserved.

## 6) Test Coverage
- Unit tests added or updated for changed logic.
- Integration tests added or updated for changed routes/flows.
- Existing tests pass for touched scope.
- Regressions around envelope, auth, and event flow are covered.

## 7) Observability and Operations
- Logging uses project logging standard.
- Important branch outcomes are logged at suitable level.
- Error paths produce actionable diagnostics.
- Dev scripts and runbook impact documented if behavior changed.

## 8) Documentation and Handoff
- CurrentSprint updated if milestone state changed.
- DevelopmentJournal updated with implementation notes.
- DecisionLog updated for important non-trivial choices.
- PR description includes risk, rollback, and verification notes.

## Merge Gate
All of the following should be true:
- Lint/static checks pass.
- Unit tests pass.
- Integration tests pass.
- Migration checks pass when applicable.
- At least one architecture/security sanity review completed.
