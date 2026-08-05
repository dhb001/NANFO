# ADR-006: Event Bus for Internal Communication

- Status: Accepted
- Date: 2026-08-05

## Problem
Direct module-to-module coupling increases architecture drift and makes future decomposition difficult.

## Context
NANFO modules must remain decoupled while reacting to shared operational state changes.

## Options
1. Direct synchronous service calls for most interactions.
2. Event-driven internal communication with explicit event contracts.

## Decision
Use an internal event bus pattern for cross-module reactions, with documented event names, payload metadata, and correlation IDs.

## Consequences
- Pros: better decoupling, easier observability via event traces, cleaner module boundaries.
- Cons: requires governance for event versioning and consumer idempotency.
