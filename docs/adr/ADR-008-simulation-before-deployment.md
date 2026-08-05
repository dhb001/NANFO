# ADR-008: Simulation Before Deployment

- Status: Accepted
- Date: 2026-08-05

## Problem
Pushing high-impact network changes directly to production creates unacceptable operational risk.

## Context
NANFO aims for safe autonomy with explainability and reversible actions.

## Options
1. Permit direct execution of approved intents in production.
2. Require simulation/risk validation before high-impact deployment.

## Decision
Adopt simulation-before-deployment as a default policy for high-impact changes, with risk/approval gates and rollback readiness.

## Consequences
- Pros: reduced outage risk, stronger confidence in change execution.
- Cons: additional pre-deployment runtime and process overhead.
