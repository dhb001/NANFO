# Feature PRD: Intent Engine

## Purpose
Translate administrator or AI intent into validated, executable workflows.

## Business Goal
Enable safe, vendor-neutral change orchestration with rollback confidence.

## Functional Requirements
- Parse and validate UNIL intents.
- Perform capability matching and dependency analysis.
- Trigger simulation/risk checks before execution.

## Non-Functional Requirements
- Idempotent workflow execution.
- Transaction-safe rollback under verification failure.

## API
- `POST /api/v1/intents/validate`
- `POST /api/v1/intents/execute`
- `GET /api/v1/intents/{id}`

## Database
- Intent records, status transitions, execution provenance.

## Events
- `intent.validated`, `intent.execution_started`, `intent.execution_completed`, `intent.execution_failed`

## Risks
- Incorrect capability metadata causing unsafe dispatch.

## Acceptance Criteria
- [ ] Invalid intents fail with explicit reasons.
- [ ] Executed intents include full audit trail and rollback metadata.

## Tests
- Unit: intent validation and policy checks.
- Integration: intent-to-hypervisor workflow.
