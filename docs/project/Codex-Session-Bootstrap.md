# GPT-5.3-Codex Session Bootstrap (OpenCode + Zed)

Use this at the start of every new OpenCode session when using GPT-5.3-Codex.

## Prompt
    You are implementing NANFO in this repository using OpenCode as the primary coding tool.

    Load and follow context in this order:
    1) AGENTS.md
    2) OPENCODE.md
    3) .agents/rules/constitution.md
    4) .agents/rules/architecture-guardrails.md
    5) docs/project/CurrentSprint.md
    6) docs/project/DevelopmentJournal.md
    7) docs/project/DecisionLog.md
    8) docs/project/KnownIssues.md

    Current project state:
    - Vertical Slice 1 is complete.
    - We are starting Vertical Slice 2.

    Before writing code:
    1) Summarize where we left off in 8 to 12 bullets.
    2) List assumptions and risks.
    3) Propose a step-by-step implementation plan for VS2.
    4) Implement only step 1.

    Implementation constraints:
    - Follow modular boundaries and ownership rules.
    - Keep changes minimal and reversible.
    - Do not invent APIs or schema fields.
    - Preserve canonical API response envelope.

    Validation requirements before completion:
    - Run lint/static checks for changed scope.
    - Run unit tests for touched modules.
    - Run integration tests for touched routes/flows.
    - If schema changed, run migration checks.

    At end of session:
    Return:
    1) Files changed
    2) Why
    3) Tests and outcomes
    4) Remaining tasks
    5) Exact next step for next session

## Mandatory Post-Step Checklist (Before Commit)

For every completed step, do all items below in the same run before creating a commit:

1) Update docs/project/CurrentSprint.md with current slice/step status.
2) Add a concise implementation + validation entry to docs/project/DevelopmentJournal.md.
3) Add or update decision/contract notes in docs/project/DecisionLog.md when behavior contracts, reliability semantics, or event flow changed.
4) Run scoped Ruff + targeted tests + full backend pytest.
5) Stage only step-related files (including required docs updates) and create one atomic commit.

If any of the three project docs are not updated when required, do not commit yet.
