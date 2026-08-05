# ADR-001: Modular Monolith First

- Status: Accepted
- Date: 2026-08-05

## Context
NANFO requires fast iteration, strict module boundaries, and low operational overhead in early stages.

## Decision
Adopt a modular monolith architecture with explicit service boundaries and event-driven module interaction.

## Consequences
- Pros: simpler deployment, easier debugging, strong transactional consistency.
- Cons: requires discipline to preserve boundaries and avoid coupling drift.
