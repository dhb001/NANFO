# P1 Realtime reliability — ADR-021 handoff

## Delivered scope

- `backend/app/websocket/manager.py` and new `delivery.py`: shared bounded
  connection-local delivery for the four existing channels, preserving their
  delta envelopes, subscription signatures and singleton managers.
- New `backend/tests/unit/test_websocket_delivery.py`: slow-client, ordering,
  revocation, overflow and cleanup failure gates using real JWT/session/RBAC
  validation with mocked external services.
- `frontend/src/features/realtime/store.ts`, `RealtimesBridge.tsx` and their
  tests: fair bounded metric retention, separate flow-history eviction, and
  explicit epoch/token/scope protection for telemetry callbacks.

No digitalTwin feature files, `useManagedWebSocket`, main, configuration,
dependencies, Compose or lease implementation were edited by this workstream.
Concurrent agents' changes are outside this handoff. No Docker or commits.

## Backend architecture and integration

`push_delta` serializes the existing envelope once and enqueues it for each
matching subscriber under the manager lock. Alerts first route against the
subscription's known allowed workspace set; foreign and unscoped alerts never
allocate a writer or consume that subscriber's queue/byte capacity. It yields
one event-loop turn but does **not**
wait for delivery. Producers/consumers need no signature changes; return now
means admitted/best-effort queued, never a browser delivery acknowledgement.

Each connection has one FIFO deque and at most one lazy writer task. Idle writers
exit; there are no per-message tasks or accumulating task/waiter lists. All delta
sends, terminal error frames and delivery-triggered closes use that writer.
The endpoint retains ownership of the initial subscription ACK and receive loop.
Ordering is enqueue order within each connection; there is no cross-channel or
distributed ordering claim.

### Limits and failure policy

`DeliveryLimits` is a validated constructor-injection hook:

| Limit | Default |
| --- | --- |
| Pending deltas per connection | 64 |
| Pending serialized UTF-8 bytes per connection | 1 MiB |
| Authorization plus delta send deadline | 5 seconds |
| Terminal error send / close deadline | 5 seconds each, independently |

The one in-flight delta is additional to the pending limits and cannot exceed
1 MiB itself. Thus a connection retains at most 65 deltas / 2 MiB serialized
payload, excluding Python/container overhead. Payload strings can be shared
between queues. Oversized individual frames also trigger overflow.

Overflow cancels the in-flight await, discards all queued deltas and stops
admission on that connection. A send deadline follows the same recovery path.
After current authorization is checked again, the writer sends exactly the
existing documented frame:

```json
{"event":"error","data":{"code":"WS_BACKPRESSURE","message":"Delta queue capacity exceeded. Reconnect and re-fetch full state from REST endpoint."}}
```

It then attempts close **1013**. No new acknowledgment protocol is introduced.
Error delivery is best effort: a blocked transport cannot be guaranteed to carry
the frame, but the separate close deadline still runs. Queue state/auth/subscriber
references are removed after termination. Unsubscribe clears pending data,
cancels and awaits the writer, and is idempotent. Ordinary transport exceptions
remove the connection as before. External writer cancellation drops its backlog.

### Authorization invariants

- Every queued delta is revalidated **when dequeued**, using the unchanged
  `authorized_workspaces` implementation: live session, active user, current
  roles/capabilities, organization/workspace membership and network ownership.
- JWT expiry is checked both before and after asynchronous authorization.
- Network workspace matching retains the existing optional event-workspace
  behavior. Alerts require an explicit event workspace in the freshly revalidated
  workspace set; removing one membership does not authorize its queued alerts.
- Alert admission uses the subscription's validated workspace set, subsequently
  refreshed by dequeue authorization, only as a routing filter. It is never a
  delivery grant. Direct manager callers omitting this set resolve it with bounded
  current authorization before subscription; failed resolution closes with 1008.
  The endpoint already supplies the set. Newly granted workspaces become routable
  after reconnect or a successful revalidation triggered by a known workspace;
  foreign traffic cannot trigger authorization work merely to discover new grants.
- Denial clears all remaining deltas, sends `WS_UNAUTHORIZED` and attempts close
  **1008** with independently bounded IO. Digital-twin security-close counters
  remain best effort and bounded. Auth timeout fails closed; revocation wins over
  an overflow recovery signal.
- A send already authorized and handed to the transport may finish after a
  concurrent revocation; bytes already sent cannot be recalled. No queued delta
  begins sending after its authorization check detects revocation. There is no
  cached enqueue-time grant or bypass for recovery.

The single-API Redis fencing lease is unchanged and its regression tests pass.
This remains process-local fanout. Multi-process delivery and durable websocket
replay are not provided. Total resource usage scales with admitted connections;
global connection admission belongs to deployment/integration. Async deadlines
assume cooperative cancellation by the ASGI transport and authorization clients.

Parent integration may inject `DeliveryLimits` when composing managers if
deployment-specific limits are needed. No configuration wiring is required for
the defaults. Endpoint `finally` already awaits `unsubscribe`. If a future host
stops managers independently of endpoint shutdown, it must await unsubscribe for
its active sockets before closing authorization dependencies.

## Frontend retention and reconciliation

Existing `telemetryByDeviceMetric`, `telemetryKeysNewestFirst` and synchronous
`applyTelemetryDelta` contracts remain available, including flow entries for
existing consumers. Retention policy is independent by data kind:

- **Latest metric state:** at most **300 resources**, identified by
  `(workspace_id, network_id, device_id)`, with at most **16 metric identities per
  resource**. The existing identity includes metric/unit/source/run/port/peer.
  Updating a noisy device can evict only its own excess identities. New resources
  beyond 300 evict the least recently updated resource and its series.
- **Flow history:** a separate **300-entry**, newest-arrival-first history,
  retaining existing snapshot-local timestamp/table/cookie/priority/index/event
  identity. It never consumes latest-metric slots or pretends to provide durable
  per-flow identity.
- **Maximum cardinality:** 4,800 latest metrics + 300 flow observations = 5,100
  entries in the compatibility map/list. There are no persistent unbounded
  resource indexes or eviction tombstones. Reset clears both kinds of data.
- Duplicate/older observations cannot replace retained newer values. Invalid
  timestamps/nonfinite values/malformed tags or scope fields are rejected.
  Identity ordering guards last only while the identity is retained; REST remains
  authoritative for history and eviction recovery.

Retention currently scans a bounded list and copies the bounded map per accepted
observation. Frame batching was deliberately not introduced: ingestion remains
synchronous and no second pending telemetry buffer or scheduler is created.
This increases retained latest-state capacity over the previous 300-entry global
budget; large-scale browser throughput remains an integrated load-test concern.

Bridge `isCurrent` includes store epoch as well as token/session/scope, and the
telemetry callback checks it before ingesting. Reset invalidates old callbacks
and pending reconciliation timers even when tenant selection is unchanged.
The existing socket hook reconnects on 1013, reconciles on subscription ACK, and
the bridge coalesces `WS_BACKPRESSURE` invalidations with its existing bounded
500 ms channel set. If the error frame cannot arrive, successful reconnect still
triggers REST reconciliation. Scope-filtered telemetry history/device query
invalidation, alert/topology and known-scene reconciliation hooks are preserved.

## Verification (2026-09-19)

All commands run locally without Docker or external-service mutation:

- Backend scoped gate after security-review routing fix: **190 passed**. Covers new delivery tests, existing
  websocket authorization/envelope tests, all four endpoint suites, simulation
  and intent event-to-WS integration, consumer translation and API lease tests.
  The review reproduction in `/tmp/opencode/test_adr021_readonly_review.py` was
  inspected. Added idle and blocked-authorization/blocked-send foreign-flood
  regressions: 70 foreign + 70 unscoped events allocate no idle writer and consume
  zero occupied queue slots/bytes; own-tenant overflow still signals backpressure
  and closes only the matching subscriber. Existing seven-case revocation tests
  across all channels pass; membership-removal coverage also verifies subsequent
  removed-tenant floods no longer start a writer.
- Frontend realtime + managed-websocket suites: **41 passed**.
- Frontend telemetry and affected intent/topology/reliability consumer suites:
  **61 passed**.
- Backend scoped Ruff, frontend scoped ESLint, frontend `npm run typecheck`, and
  owned-file `git diff --check`: passed.
- Production build to `/tmp/opencode/realtime-dist`: passed. Existing bundle
  evaluator run against that isolated output: all five unchanged limits passed;
  total JS gzip **408.98 KiB / 410.16 KiB**. This is a combined-worktree snapshot
  including concurrent digitalTwin changes, not isolated bundle attribution.

Backend reproduction (from `backend/`):

```sh
poetry run pytest tests/unit/test_websocket_delivery.py tests/unit/test_websocket_auth_revalidation.py tests/unit/test_websocket_alerts.py tests/unit/test_websocket_digital_twin.py tests/unit/test_websocket_digital_twin_auth.py tests/unit/test_api_realtime_lease.py tests/unit/test_ws_push_consumer.py tests/integration/test_topology_ws_endpoint.py tests/integration/test_telemetry_ws_endpoint.py tests/integration/test_alerts_ws_endpoint.py tests/integration/test_digital_twin_ws_endpoint.py tests/integration/test_simulation_event_ws_flow.py tests/integration/test_intent_event_ws_flow.py -q --no-cov
poetry run ruff check app/websocket/manager.py app/websocket/delivery.py tests/unit/test_websocket_delivery.py
```

Frontend reproduction (from `frontend/`):

```sh
npm run test -- src/features/realtime src/shared/realtime
npm run test -- src/features/telemetry src/features/intent/IntentPage.test.tsx src/features/topology/TopologyAnalysisPage.test.tsx src/features/reliability/ReliabilityPage.test.tsx
npm run typecheck
npx eslint src/features/realtime/store.ts src/features/realtime/store.test.ts src/features/realtime/RealtimesBridge.tsx src/features/realtime/RealtimesBridge.test.tsx
npx vite build --mode production --outDir /tmp/opencode/realtime-dist
```

Parent acceptance remains: serialized browser/live-ASGI slow-client campaign,
combined full-suite gates, deployment memory/connection-limit tuning, and program
status/journal integration. Unit fake transports exercise cancellation/timeout
semantics; they do not certify a particular proxy's buffering behavior.
