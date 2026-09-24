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
| `EVENT_RECLAIM_IDLE_MS` | 60000 | Minimum pending idle time before reclaim (the redelivery backoff) |
| `EVENT_CONSUMER_BATCH_SIZE` | 10 | Entries per reclaim page and new-message read, maximum 100 |
| `EVENT_MAX_DELIVERIES` | 20 | Deliveries (XPENDING counter) before a pending entry is dead-lettered |
| `EVENT_COMPLETION_TTL_SECONDS` | 3600 | Completion-marker lifetime; must cover the replay horizon below |
| `EVENT_HANDLER_TIMEOUT_SECONDS` | 30 | Time bound per handler attempt |
| `EVENT_CONSUMER_NAME` | `<role>-<hostname>` | Stable consumer name per instance |
| `EVENT_CONSUMER_CONCURRENCY` | 1 | >1 processes entries concurrently, ordered per network/device |
| `EVENT_PUBLISH_MAX_MEMORY_RATIO` | 0.90 | Producers refuse (503) at this `used_memory/maxmemory` |

Contention or Redis acquisition failure fails startup. Renewal retries transient
Redis failures until one IO deadline before local expiry. On loss the deadline is
cleared first (every collector/handler/readiness fence fails closed), domain tasks
are cancelled, and the process receives SIGTERM for a graceful shutdown with a
hard-exit fallback (`API_REALTIME_LEASE_LOSS_EXIT_SECONDS`, exit status 1). Normal
shutdown stops runtime tasks before token-checked lease release. A successor's
lease is never deleted by a stale owner. This assumes a single authoritative Redis
primary, not a consensus fence across independently writable Redis primaries.

## Recovery Semantics (ADR-028 C14)

Each instance uses one stable consumer name, so a restart reclaims its own pending
entries; the leader's janitor removes consumers idle for more than
`max(10 x EVENT_RECLAIM_IDLE_MS, 1 h)` that hold no pending entries (atomic Lua
re-check). Each loop visits one bounded `XAUTOCLAIM` page, advances its cursor, then
reads new entries. Existing `event:seen:*` keys are intentionally ignored.
Individual handler completion is recorded only after success; handlers registered
`idempotent` (audit and telemetry persistence, unique `event_id`) skip markers.

* Transient/unclassified failures (Redis/PostgreSQL/Neo4j outages, timeouts, OS
  errors, unknown exceptions) leave the entry **pending**; reclaim retries it after
  `EVENT_RECLAIM_IDLE_MS`. Later entries of the same network/device are held back,
  a dependency outage pauses the loop with exponential backoff (<= 30 s).
* Deterministic failures (ValueError/KeyError/TypeError/ValidationError/
  `DeterministicEventError`, unsupported envelope major version, missing
  dereferenced fields per `app.events.contracts`) are dead-lettered immediately.
* Entries delivered more than `EVENT_MAX_DELIVERIES` times are dead-lettered
  without running handlers (crash-loop protection).

Replay horizon: `EVENT_MAX_DELIVERIES x (EVENT_RECLAIM_IDLE_MS + handler timeout)`
= 20 x 90 s = 30 min; markers live 60 min (validated at startup).

Dead-letter entries keep the original fields/bytes plus `failed_stream`,
`failed_group`, `failed_entry_id`, `failure_reason`, `failed_handler`,
`delivery_count` and `error_type` (never exception messages). Only a successful,
untrimmed DLQ `XADD` permits ACK. Operate the DLQ with
`python -m scripts.dead_letter {list,replay,purge}`; retention runs continuously
via `python -m scripts.stream_retention schedule` (archive-before-delete, DLQ
included). Configure Redis persistence and backup appropriately: Redis
acknowledgement is not a promise against loss of an unfsynced Redis write.

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
fanout and transition publication failures propagate for reclaim/DLQ; derived alert
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
