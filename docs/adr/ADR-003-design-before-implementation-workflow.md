# ADR-003: Design Before Implementation Workflow

- Status: Accepted
- Date: 2026-08-05

## Context
To reduce hallucinations, rework, and architecture drift, implementation must be grounded in explicit design artifacts.

## Decision
Require a design pass (`design-feature`) before implementation (`implement-feature`) for non-trivial changes.

## Consequences
- Pros: clearer contracts, reduced ambiguity, better cross-team alignment.
- Cons: slightly longer lead time before coding starts.
