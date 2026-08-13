# VS8 Execution Plan: Intent Engine Recommendation + Explainability Baseline

## Purpose
Execute M8 as a finite, contract-governed vertical slice that delivers the first production-safe Intent Engine baseline with explicit validation, lifecycle provenance, explainability metadata, and policy-aligned confidence handling.

## Scope Lock (Authoritative for VS8)
- In scope APIs (from `docs/features/IntentEngine.md` only):
  - `POST /api/v1/intents/validate`
  - `POST /api/v1/intents/execute`
  - `GET /api/v1/intents/{id}`
- In scope events (from `docs/features/IntentEngine.md` only):
  - `intent.validated`
  - `intent.execution_started`
  - `intent.execution_completed`
  - `intent.execution_failed`
- Out of scope for VS8:
  - Any `/api/v1/ai/*` endpoint surface
  - Hypervisor real execution/rollback integration (M9 scope)
  - New websocket channel additions
  - Cross-module SQL joins or non-governed module ownership changes

## Non-Negotiable Guardrails
- Preserve C5 workspace/org boundary enforcement.
- Preserve C6 deferred topology endpoint non-routability.
- Preserve canonical REST envelope (`success/data/meta/errors`).
- Preserve fail-open event-publish degradation semantics where already established.
- Do not introduce undocumented endpoints, channels, event names, or payload fields.
- Keep controller -> service -> repository layering strict in backend changes.

## Migration Classification
- MIG-8.1 (required): intent lifecycle baseline table/model/repository.
- MIG-8.2 (optional): performance indexes if required by measured query paths.
- MIG-8.3 (optional): dedicated lifecycle history table only if Step 7 explainability/audit needs exceed baseline table fit.

## Execution Steps (S1-S7)

### S1 — Contract Lock + Sprint Scaffolding (docs-only)
Deliverables:
- Lock VS8 scope to `IntentEngine.md` API/event surface.
- Record migration classification (MIG-8.1 required, MIG-8.2/8.3 optional).
- Seed sprint checklist and risk register for VS8.

Exit criteria:
- `CurrentSprint.md` contains VS8 section and step checklist.
- This plan file exists and is referenced from sprint tracking.

### S2 — Persistence Baseline (MIG-8.1)
Deliverables:
- Add Intent module with lifecycle baseline ORM model and repository in backend module boundaries.
- Add Alembic migration for baseline intent table with reversible downgrade path.
- Ensure no cross-module SQL FK coupling beyond logical UUID references unless same-module ownership applies.

Exit criteria:
- Migration upgrade/downgrade/upgrade passes.
- Repository unit tests cover create/read/state transition basics.

### S3 — Validation Endpoint Baseline
Deliverables:
- Add `POST /api/v1/intents/validate` request/response contract under canonical envelope.
- Implement explicit invalid-intent reason semantics aligned to PRD AC.
- Persist validation result metadata sufficient for explainability traceability.

Exit criteria:
- Unit tests cover positive/negative validation branches.
- Integration tests cover endpoint envelope/status/error mapping.

### S4 — Execute Endpoint Lifecycle Baseline
Deliverables:
- Add `POST /api/v1/intents/execute` with idempotent execution semantics.
- Persist execution lifecycle state transitions and provenance markers.
- Keep hypervisor side effects out of scope (record lifecycle only).

Exit criteria:
- Unit tests cover idempotent re-execution and non-executable-state conflicts.
- Integration tests verify canonical response contracts.

### S5 — Intent Detail Read Endpoint
Deliverables:
- Add `GET /api/v1/intents/{id}` returning lifecycle/provenance metadata.
- Preserve C5 checks and not-found/error envelope behavior.

Exit criteria:
- Unit/integration tests verify read contract and boundary enforcement.

### S6 — Event Publication + Consumer Coverage
Deliverables:
- Publish governed lifecycle events (`intent.validated`, `intent.execution_started`, `intent.execution_completed`, `intent.execution_failed`) at appropriate lifecycle transitions.
- Add/update audit consumer mapping and tests for intent lifecycle events.
- Add/update ws push consumer behavior only if existing governed channels consume intent lifecycle updates without adding new channels.

Exit criteria:
- Event publish branches are covered, including fail-open degradation behavior.
- Consumer unit/integration coverage passes.

### S7 — Explainability + Confidence Baseline
Deliverables:
- Add explicit explainability metadata fields for recommendations (reasoning summary, evidence pointers, alternatives considered baseline, policy reference).
- Add confidence score + policy-aligned action posture fields consistent with AIOS guardrails.
- Ensure human-approval-required posture is explicit where confidence/policy requires it.

Exit criteria:
- Unit tests verify explainability/confidence contract presence and fallback behavior.
- Integration tests verify API returns explainability metadata under canonical envelope.

## Validation Matrix

Per-step minimum gate:
- Scoped Ruff on changed backend/tests/docs paths.
- Targeted unit tests for touched services/repositories/consumers.
- Targeted integration tests for touched API/event flows.
- Migration check command for schema steps:
  - `poetry run alembic -c alembic/alembic.ini upgrade head`
  - `poetry run alembic -c alembic/alembic.ini downgrade -1`
  - `poetry run alembic -c alembic/alembic.ini upgrade head`

Closure gate (required at VS8 completion):
- `poetry run pytest tests -q`

Environment note:
- Local migration/auth paths may require `POSTGRES_PASSWORD=CHANGE_ME`.

## Step Batching and Commit Discipline
- One executable step per commit (docs-only step can be atomic docs commit).
- Mandatory post-step updates before commit:
  - `docs/project/CurrentSprint.md`
  - `docs/project/DevelopmentJournal.md`
  - `docs/project/DecisionLog.md` when contracts/behavioral decisions change
- Stage only in-scope files for the current step.

## Blocker Protocol
- If authoritative docs conflict, follow precedence from `context-loading.md` and record decision in `DecisionLog.md`.
- If missing contract detail prevents safe implementation, stop after completing non-blocked work and record the assumption/risk.
- Do not invent new API/event names to bypass blockers.

## Risk Register (Initial)
- Contract drift risk: accidental introduction of `/api/v1/ai/*` or undocumented lifecycle events.
  - Control: explicit scope lock, checklist assertion in each step.
- Boundary drift risk: intent implementation querying non-owning module tables via joins.
  - Control: logical references + service boundary checks only.
- Explainability under-specification risk: recommendation outputs lacking evidence/confidence detail.
  - Control: S7 schema contract + targeted assertions.
- Event fanout reliability risk: lifecycle events fail publish and silently lose traceability.
  - Control: preserve fail-open with warning metadata and coverage for degraded paths.

## Definition of Done (VS8)
- S1-S7 complete with required docs updates.
- Required migration (MIG-8.1) implemented and migration gate green.
- All three IntentEngine PRD endpoints implemented and contract-tested.
- All four lifecycle events published with governed consumer coverage.
- Explainability/confidence metadata present in baseline recommendation lifecycle outputs.
- Full backend regression gate green.

## Operator Resume Notes
- Resume from first unchecked VS8 step in `CurrentSprint.md`.
- Re-load `AGENTS.md`, `OPENCODE.md`, core rules, `IntentEngine.md`, relevant ADRs, then sprint/journal state.
- Keep scope finite: do not start M9 execution side effects while VS8 remains open.
