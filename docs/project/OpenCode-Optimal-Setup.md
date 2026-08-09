# OpenCode Optimal Setup for NANFO

This guide helps you run OpenCode with the same discipline as your prior setup, while minimizing context drift and implementation errors.

## 1) Repository Preparation
- Keep AGENTS.md and OPENCODE.md at repository root.
- Keep project state current in docs/project/CurrentSprint.md and docs/project/DevelopmentJournal.md.
- Record non-trivial implementation decisions in docs/project/DecisionLog.md.

Why this matters:
- OpenCode performs best when there is one clear startup contract plus one clear current-state source.

## 2) Session Startup Pattern
At the start of every session, paste the bootstrap from docs/project/Codex-Session-Bootstrap.md.

Required startup outcomes:
- State summary is produced before coding.
- Risks and assumptions are explicit.
- Work is split into small steps.
- Only first step is implemented before re-evaluation.

## 3) Restriction Enforcement Pattern
To keep your .agents restrictions effective in OpenCode:

- Hard-link all important constraints in OPENCODE.md.
- Require ordered context loading.
- Require explicit mention of architecture constraints (C5, C6, ownership, canonical API envelope).
- Require validation gates before completion.

If output starts drifting:
- Stop and ask the model to restate constraints from OPENCODE.md and AGENTS.md before continuing.

## 4) Model Routing for Cost and Quality
Recommended split when using GPT-5.3-Codex:

- Primary model: implementation and refactor tasks.
- Secondary pass: review tasks against PR-Quality-Checklist.md.
- Keep expensive reasoning for design decisions, not repetitive edits.

## 5) PR Gate Workflow
Before every PR merge:
1. Run checklist in docs/project/PR-Quality-Checklist.md.
2. Confirm tests for touched scope pass.
3. Confirm docs/project entries are updated.
4. Confirm rollback or mitigation notes are present for risky changes.

## 6) Vertical Slice 2 Continuity Workflow
Use docs/project/OpenCode-Resume-Template.md in every session:

- End session with section A handoff.
- Start next session with section B prompt.

This prevents losing momentum and reduces repeated rediscovery work.

## 7) Suggested Command Rhythm
- Use small commits scoped to one subtask.
- Run tests right after each subtask.
- Avoid large unvalidated edit batches.

Example rhythm:
1. Implement one scoped change.
2. Run unit tests for touched module.
3. Run integration tests for touched route or flow.
4. Update sprint and journal notes.

## 8) Failure Recovery Protocol
If a session goes off-track:
1. Re-open OPENCODE.md and CurrentSprint.md.
2. Ask for a delta-only summary: what changed, what failed, what remains.
3. Re-plan in 3 to 5 steps.
4. Continue from step 1 only.

## 9) Definition of Ready for Any New Task
- Requirement exists in docs/features or accepted decision artifact.
- Ownership boundaries are clear.
- Acceptance criteria are explicit.
- Required tests are known.

If any item is missing, do a design clarification pass before coding.
