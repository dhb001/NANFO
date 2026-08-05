# ADR-005: Backend Technology Stack Baseline

- Status: Accepted
- Date: 2026-08-05

## Problem
Backend stack choices must be stable enough to support long-term architecture without frequent foundational rewrites.

## Context
NANFO requires async APIs, WebSockets, worker orchestration, and strong Python ecosystem support.

## Options
1. Python FastAPI + Celery + Redis.
2. Alternate stacks requiring major ecosystem/context shifts.

## Decision
Adopt FastAPI for API/WebSocket gateway, Celery for async workloads, and Redis as broker/cache/event infrastructure baseline.

## Consequences
- Pros: high iteration speed, strong async capabilities, established ecosystem.
- Cons: requires careful worker/queue operations and runtime observability.
