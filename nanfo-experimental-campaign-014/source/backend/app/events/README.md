# ADR-010 Event Recovery

## Deployment

Run exactly one API worker per Redis database, for example:

```sh
poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

The mandatory `nanfo:api:realtime:lease` key is acquired with `SET NX PX` before
Neo4j startup, telemetry collection, backfill, or event consumer provisioning.
There is no environment switch to disable this guard. All APIs sharing the event
streams must use the same Redis database. The independent intent execution worker
does not acquire the API lease.

| Setting | Default | Meaning |
| --- | --- | --- |
| `API_REALTIME_LEASE_TTL_SECONDS` | 30 | Lease expiry; renewal every TTL/3, Redis calls bounded to TTL/6 |
| `EVENT_RECLAIM_IDLE_MS` | 60000 | Minimum pending idle time before reclaim |
| `EVENT_CONSUMER_BATCH_SIZE` | 10 | Entries per reclaim page and new-message read, maximum 100 |
| `EVENT_COMPLETION_TTL_SECONDS` | 86400 | Per-stream/group/handler completion cache lifetime |
| `EVENT_HANDLER_TIMEOUT_SECONDS` | 30 | Time bound per handler attempt |

Contention or Redis acquisition failure fails startup. Token-checked Lua renewal
failure, timeout, or expiry invokes `os._exit(1)` to close the process's existing
WebSockets, consumers, and collector, rather than leaving a degraded realtime
process serving. Use a supervisor with restart backoff. Normal shutdown stops
runtime tasks before token-checked lease release. A successor's lease is never
deleted by a stale owner. This assumes a single authoritative Redis primary,
not a consensus fence across independently writable Redis primaries.

## Recovery Semantics

Consumer identities include a fresh UUID on every start. Each loop visits one
bounded `XAUTOCLAIM` page, advances its cursor, then reads new entries. Existing
`event:seen:*` keys are intentionally ignored. Individual handler completion is
recorded only after success. A later handler's failure does not repeat previously
completed handlers while their markers remain available. Unknown valid event
types are ACKed and ignored, as before.

Malformed identity/JSON/object payloads and exhausted handler retries are appended
to `stream:dead_letter` with original fields and stream/group/entry provenance.
Only a successful, untrimmed DLQ `XADD` permits ACK. DLQ failures leave pending
entries recoverable. Configure Redis persistence and backup appropriately: Redis
acknowledgement is not a promise against loss of an unfsynced Redis write. Do not
trim or delete the DLQ before operator inspection/recovery.

Apply migration `0012` after `0011` before starting these consumers. Identity owns
the nullable unique `audit_logs.event_id` and uses `INSERT ON CONFLICT DO NOTHING`
in the audit transaction. Historical rows are not rewritten/deleted. AuthService's
direct synchronous append remains authoritative for the four existing auth event
types; their bus audit subscriptions are removed to avoid duplicate auth rows.
No auth/session implementation or publisher signature is changed.

This is at-least-once delivery, not universal exactly-once. A side effect may finish
before its completion marker is recorded. Audit and telemetry database identity
constraints protect their durable inserts; ephemeral WebSocket deliveries can
repeat. Metrics counters remain best-effort. Telemetry persistence/validation,
fanout and transition publication failures propagate for retry/DLQ; derived alert
publication reuses an event ID deterministically derived from the source identity.

Outbox work remains Intent-owned. Existing Report and Simulation services still
have internal commit/publication gaps and swallowed publication failures; wrappers
cannot repair those without changing the owning services. This change does not
claim durable delivery for those derived lifecycle notifications, historical
producer crash windows, or telemetry source sampling.

## Verification

Unit/integration tests inject infrastructure, not auth/RBAC bypasses.
`ApiRealtimeLease(redis, key=..., on_lost=...)` allows tests to supply isolated Redis
and observe fatal decisions without killing pytest. Main's production composition
always uses the fixed key and real fatal callback; integration fixtures patch its
lease factory along with the existing mocked runtime connections.

```sh
poetry run pytest tests/unit/test_event_recovery.py tests/unit/test_api_realtime_lease.py -q --no-cov
NANFO_STEP6_LIVE=1 poetry run pytest tests/live/test_step6_recovery.py -q --no-cov
```

Live tests use credentials from `backend/.env`, existing services only, randomized
Redis streams/groups/keys, and a newly created disposable PostgreSQL database
(requires `CREATEDB`). They never start the application/global consumer loops or
drain live backlog. They migrate through `0011 -> 0012`, check rollback/concurrent
audit replay and historical preservation, and round-trip `0012`. Only their own
keys/database are removed in cleanup; credentials are not printed.
