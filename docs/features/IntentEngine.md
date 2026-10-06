# Feature PRD: Intent Engine

## Foundation Capability Boundary

No learned model is installed in the current foundation. Basic validation is
not learned confidence; score zero explicitly denotes unavailable model confidence.
Unconfigured, demo or production execution returns `execution_failed`, verification `not_performed`, and
`executor_unavailable`, with no rollback. Historical deterministic baseline
success metadata is not evidence of execution. Cross-workspace network references
are rejected before persistence/publication. Mode selection never enables a driver.

## Manual Lab Execution (ADR-010)

Explicitly configured isolated emulation supports reroute, SELECT multipath,
shaping, meter policing and restore. Execute requires `manual_approval=true`,
current capabilities/membership and a trusted fresh binding. `cancel=true` uses
the existing execute route for cancellation/compensation. Acceptance returns 202
and `execution_started`, not completion. A separate worker reconciles durable
execution/outbox state with the lab's journal, readback and reachability evidence.
Completed configuration does not imply measured performance improvement; workload
effects are separately tested. Provenance exposes phase, execution ID, hashes,
deadline, explicit verification/rollback, cancellation actor and uncertainty.
Read ADR-010, `backend/app/modules/intent/README.md`, and
`docs/project/ManualExecution-Step5-Step6.md` for scope and verification limits.

## ADR-028 contract changes (C3, C18)

Contract index: `docs/api/ADR028-ContractChanges.md`. Module detail:
`backend/app/modules/intent/README.md` ("ADR-028 contract changes").

- **Idempotent validate (C3, BREAKING for duplicate keys).** `Idempotency-Key` is unique
  per workspace. A replay of the same network and normalized intent returns the stored
  intent with `meta.idempotent_replay=true`; any other reuse is 409
  `IDEMPOTENCY_KEY_REUSED`. Execute and cancel use the intent's stored key; a different
  key is 409 `INTENT_IDEMPOTENCY_CONFLICT`. A concurrent execute loses with 409
  `INTENT_ALREADY_EXECUTING`.
- **Simulation before execution (C18).** High-impact lab actions (`reroute_path`,
  `isolate_vlan`) require a completed, passing simulation of the same network. Its limits
  must respect the server policy floors, and its evidence and plan hash are bound into the
  execution record. Otherwise 409 `SIMULATION_REQUIRED`, `SIMULATION_POLICY_VIOLATION` or
  `SIMULATION_EVIDENCE_REJECTED`.
- **Approval.** Manual lab execution must send the current `approval_binding` (else 409
  `APPROVAL_BINDING_MISMATCH`). With `INTENT_REQUIRE_DISTINCT_APPROVER` (default true),
  the requester cannot execute their own intent (409 `DISTINCT_APPROVER_REQUIRED`).
- **Payloads.** Intent documents are bounded (64 KiB, depth 10, 128 keys per object, 1024
  items per array, finite numbers), else 422. State commits before publication with
  stable event IDs; outbox payloads add `phase` and `sequence`.
- ADR-028 removed the unused `intent/autonomous.py` wrapper. Autonomous execution is owned
  by the Autonomy module (`docs/project/CompletionProgram/AutonomousExecution.md`).

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
- `GET /api/v1/intents?workspace_id=UUID&network_id=UUID&page=1&page_size=20`
  (ADR026): authorized durable summary history; optional network filter and bounded
  action projection. Exact schema: `docs/api/WorkflowHistory.md`. UI `intent_id`
  deep links load detail without approval/execution. Successful token rotation keeps
  drafts and immutable execution/retry identity; changed roles/permissions revoke
  local approval. Lost responses require detail reconciliation or an explicit retry
  with the same identity, never automatic transport-error replay.

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
