# Agent Execution Standard (Context Safety)

## Goal
Reduce context loss, hallucination risk, and architecture drift during implementation.

## Rules
- Do not invent APIs, events, schemas, or capabilities not documented in active PRD/API/ADR context.
- If required context is missing, state assumptions explicitly and mark them for confirmation.
- Prefer loading only task-relevant docs to preserve context window quality.
- Preserve module boundaries: no cross-module table joins.
- Keep design and implementation workflows separated for non-trivial tasks.

## Pre-Implementation Checklist
- Read constitution and architecture guardrails.
- Read relevant feature PRD.
- Read relevant ADRs.
- Confirm API contract alignment with `docs/api/API_STANDARD.md`.
- Log assumptions and risks.

## Output Quality
- Every recommendation includes rationale and risk notes.
- Every API change includes envelope-compliant request/response definitions.
- Every data change references owning module and migration intent.
