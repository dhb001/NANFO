# ADR-004: Domain-Driven Design Module Ownership

- Status: Accepted
- Date: 2026-08-05

## Problem
Without explicit domain ownership, modules tend to leak responsibilities and create cross-domain coupling.

## Context
NANFO is a modular monolith with strict boundaries and event-driven module communication.

## Options
1. Generic utility-driven architecture with shared tables across domains.
2. Domain-driven module ownership with explicit service boundaries and domain events.

## Decision
Adopt domain-driven module ownership. Each module owns its data and behavior. Cross-module interactions occur through explicit contracts/events.

## Consequences
- Pros: clearer ownership, reduced accidental coupling, easier future service decomposition.
- Cons: requires discipline in contract design and event governance.
