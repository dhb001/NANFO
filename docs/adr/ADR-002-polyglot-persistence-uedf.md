# ADR-002: Polyglot Persistence for UEDF

- Status: Accepted
- Date: 2026-08-05

## Context
Operational data includes relational metadata, high-frequency telemetry, and graph dependencies with different access patterns.

## Decision
Use PostgreSQL, TimescaleDB, Neo4j, Redis, and object storage in a unified data fabric.

## Consequences
- Pros: fit-for-purpose performance and query capability per data domain.
- Cons: additional operational complexity across multiple stores.
