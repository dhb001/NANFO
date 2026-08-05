# Event API

## Purpose
Define internal domain event contract conventions.

## Scope
- Event type naming
- Required metadata (`event_id`, `timestamp`, `source`, `correlation_id`)
- Payload schema governance and versioning
- Delivery and retry expectations

## Dependency
- Architecture boundaries are governed by `.agents/rules/architecture-guardrails.md`.
