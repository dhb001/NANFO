# ADR023 distributed realtime

## Review-fix ownership coordination

Realtime owns ADR023Review findings1/6: fanout permanent-poison quarantine and
Telemetry consumer replay. Network `schemas.py` changes are restricted to the
`CreateDeviceRequest.hostname` field (1–253 characters); no geometry edits.
Telemetry replay implementation is a new owning `modules/telemetry/replay.py`
helper plus a minimal `TelemetryPersistenceService.replay_event` accessor. Retention
archive/service logic is not replaced. Replay uses the existing event advisory lock
and tombstone repository, so archival and replay share owning exclusion. This is the
coordination handoff for retention/geometry agents; detailed results follow below.

### ADR023Review findings1 and6 resolved (2026-09-20)

**Finding1:** permanent validation/serialization/size failures now take a terminal
quarantine path. `CreateDeviceRequest.hostname` rejects empty or >253-character
inputs, including the review's300000-character request. Historical/internal poison
is handled even if it already reached owning persistence. `FanoutPublisher` detects
schema/size/unsupported JSON/NaN failures separately from IO/lease failure. Lua's
post-encoding size rejection has a distinct permanent result.

The lease-fenced quarantine operation appends a bounded diagnostic receipt to
`<fanout stream>:quarantine` and an ordered version1 `reset` control envelope to the
broadcast stream before the handler can complete/ACK. Receipt fields are `version`,
`delivery_sha256`, `reason`, `quarantined_at`; no raw payload, exception message or
tenant data is copied. Exact MAXLEN equals configured `max_entries`; receipt size
is constant-bounded (under512bytes for current reasons). This is an intentionally
bounded diagnostic quarantine, not an unbounded second copy of durable domain data.
Operators use source domain records/event IDs to repair offending projections.
The reset closes all current local sockets with WS_BACKPRESSURE on every API and
keeps new admission closed until the next fresh frame, requiring scoped REST
reconciliation. Missing/trimmed resets are also covered by sequence/freshness loss.

Confirmed quarantine+reset is terminal success for the WS handler; existing
completion markers and ACK prevent reclaim from cycling leadership. Lost/failed
quarantine confirmation, transient append errors and fencing still cancel the
consumer without a completion marker/ACK. Retry may append another small receipt
or reset after an uncertain reply; bounds hold and unnecessary reconciliation is
safe. Ordinary valid domain-work exceptions retain the existing durable DLQ behavior.

**Finding6:** `TelemetryPersistenceService.replay_event(event)` returns the public
owning `TelemetryReplay(status, event=None)` contract:

* `active_exact`: all normalized persisted payload fields and correlation agree;
  `event` is rebuilt solely from the active stored record. Envelope timestamp uses
  stored `observed_at` (the original transport timestamp is not persisted), and
  envelope source is Telemetry. Candidate envelope fields cannot redirect replay.
* `active_conflict`: changed scope/device/value/unit/metric/time/source/tags/correlation
  or malformed candidate; no replay event is returned. The consumer raises a bounded
  error through existing retry/DLQ, never invoking alert detection or socket fanout.
* `tombstone`: the event was archived; the consumer suppresses detector/fanout and
  acknowledges the deliberate no-op. It never resurrects archived measurements.

The accessor takes the existing Telemetry event advisory lock, consults tombstones
before the active record, and keeps the caller's transaction alive through recovery.
No cross-owner SQL or retention/archive edits. Exact committed-active retries still
run idempotent measured detection and fanout, preserving the commit-before-publish
crash recovery path. Missing active state is an explicit error, never a fallback to
incoming bytes. The existing boolean persistence contract is unchanged.

**Validation:**175 tests passed in57.89s across quarantine, genuine replay conflicts,
tombstone suppression, canonical exact retry, transient publish/noACK, persistence,
consumer/recovery/startup/readiness and real socket campaigns. Actual `app.main`
two-process Redis/Neo4j acceptance now injects the old oversized domain event,
observes both sockets reconnect, verifies its PEL ACK plus one bounded receipt,
delivers the next healthy delta and confirms the leader token remains unchanged
past reclaim eligibility. Both existing socket campaigns also passed. Scoped Ruff
passed; only existing Neo4j/Python3.14 deprecation warnings. The review reproductions
are preserved in `/tmp/opencode/adr023_review_repros.py`; their old vulnerability
assertions are superseded by these regression tests, not relabeled as passing tests.

## Source integration update (2026-09-20)

**Integrated in actual `app.main`**, following the subsequent ownership delegation.
This section supersedes the original parent-pending handoff below. Main/config/
readiness are now wired; deployment composition remains parent-owned. `SCHEMA_HEAD`
is the parent's **0027** and was not edited by this workstream.

### Deployment-agent coordination: exact environment

Set the same values on every serving API:

| Setting | Default | Validation |
|---|---:|---|
| `API_REALTIME_DISTRIBUTED` | `false` | Explicit opt-in; false retains singleton |
| `API_REALTIME_LEASE_TTL_SECONDS` |30| integer3–300 |
| `API_REALTIME_FANOUT_MAX_ENTRIES` |4096| integer16–65536 |
| `API_REALTIME_FANOUT_MAX_PAYLOAD_BYTES` |262144| integer1024–1048576 |
| `API_REALTIME_FANOUT_BATCH_SIZE` |32| integer1–100 |
| `API_REALTIME_FANOUT_DEDUP_ENTRIES` |4096| integer16–65536 |
| `API_REALTIME_FANOUT_HEARTBEAT_SECONDS` |1| finite0.1–10 |
| `API_REALTIME_FANOUT_STALE_SECONDS` |5| finite0.5–60; greater than heartbeat+IO |
| `API_REALTIME_FANOUT_IO_TIMEOUT_SECONDS` |2| finite0.1–10; greater than heartbeat/2 |
| `API_REALTIME_FANOUT_RETRY_SECONDS` |1| finite0.05–10 |
| `API_REALTIME_FANOUT_SHUTDOWN_SECONDS` |5| finite0.1–30 |
| `API_REALTIME_COLLECTOR_WATCHDOG_SECONDS` |1| finite0.1–10; below stale deadline |
| `TELEMETRY_FLEET_ENABLED` |`false`| independent of distributed flag |

Numeric booleans, NaN/infinity and conflicting timing budgets are rejected by
`Settings` before startup. `Settings.realtime_fanout_settings()` maps these values
to the helper; internal Redis keys remain the documented constants.

**Fleet ownership guard:** when deploying `scripts.run_fleet_collector`, explicitly
set `TELEMETRY_FLEET_ENABLED=true` and `TELEMETRY_RUNTIME_ADAPTER_MODE=stub` on APIs.
The guard works with either singleton or distributed serving and prevents creating
an API collector at all. Any non-stub API adapter with fleet enabled fails config
validation, preventing duplicate measured/emulation/demo polling. Fleet provisioning
continues to use its independent `NANFO_FLEET_*` settings and protected manifests
documented in `Fleet.md`; main does not import/start the fleet worker. Deployment
must validate/monitor the fleet worker separately. No deploy files changed here.

Main initializes Redis/Neo4j per API. Distributed startup establishes the subscriber
before leadership, then `_runtime_lifespan(app, *, lease=...)` allocates a **new local
exit stack for every acquisition**. Only the leader provisions domain groups, starts
the non-fleet collector, runs backfill and starts the nine domain consumers. All
handlers retain stable completion identities and are fenced; collector polling is
fenced before/after the actual poll. The supervised watchdog detects collector loss
even while consumers remain alive. Consumer/watchdog failure cancels all leader
work and stops the collector before release/reacquisition. Partial startup cleanup
is registered before any effects and shielded from supervisor cancellation; an
independent startup deadline and bounded teardown enforce fail-stop if cleanup hangs.
App-state references are cleared on teardown. Subscriber/socket drain precedes
Redis/Neo4j closure. Legacy startup behavior and tests remain compatible.

Readiness now exposes additive `data.realtime` diagnostics: `mode`, `role`,
`local_consumer_count`, `local_collector`, `collection_owner`. Followers verify their
own subscription and freshness, report `api_consumers=delegated`, and have zero local
consumer tasks/no collector. Unexpected local work on a follower fails readiness.
Leaders check their consumer tasks and watchdog. Required database/schema/Redis/
Neo4j/storage checks remain. Configured follower telemetry reports `delegated`,
and fleet telemetry reports `external_unverified`, never invented local/measured
collector health. Those capability diagnostics do not block socket serving; stale
fanout still does. External fleet freshness remains its worker's separate check.

### Actual app.main acceptance

`tests/integration/test_distributed_main_sockets.py` spawns the unmodified main app
object with its real lifespan/routes/readiness. Disposable authenticated Redis and
Neo4j run on unique Docker-assigned localhost ports; SQL owner reads/readiness schema
results alone are fixtures. Production JWT/session/current RBAC checks remain active.
The actual collector runner, group provisioning, all consumer loops, topology
projection, fanout, readiness and supervisor execute. It verifies leader/follower
readiness with no follower collector, Neo4j projection and both sockets, session
revocation, actual consumer cancellation and collector health failure/reacquisition,
killed-leader promotion and fresh API follower restart. No emulation or physical
collection claim.

Images use `--pull=never` and exact locally installed IDs:

* Redis: `sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2`
* Neo4j: `sha256:9f75e8df4325a24f00fdd7a8c0bcce650a58375049b1058e496e8b43d6c36b37`

Cleanup terminates/joins only owned spawned processes, kills stragglers, closes bound
API sockets and driver pools, and removes exact UUID-owned containers with `docker
rm -fv` (including Neo4j anonymous volumes). No existing databases/containers are
modified. The fixture asserts exact-name containers are absent after cleanup.

Final combined startup/config/readiness/distributed/socket/auth/event regression
gate: **333 passed in72.14s**, including the independent-startup-timer regression
and all three real multi-process campaigns. Scoped Ruff and whitespace checks
passed. Neo4j emits existing Python3.14 `asyncio.iscoroutinefunction` deprecation
warnings. All fixture cleanup assertions passed.

Run all startup and distributed acceptance from `backend/` with
`RUN_DISTRIBUTED_REALTIME=1 poetry run pytest` and these files:
`tests/integration/test_startup_{telemetry,backfill,distributed}.py`,
`tests/integration/test_readiness.py`,
`tests/integration/test_distributed_{main,realtime}_sockets.py`,
`tests/unit/test_distributed_{config,realtime}.py`,
`tests/unit/test_api_realtime_lease.py` (plus the existing auth/event/socket gates).

## Internal contract and design

Domain Redis Streams retain their existing shared consumer groups and owning,
durably idempotent effects. Only the elected domain leader starts those consumers,
the topology backfill and collector. Every serving API, including the leader, reads
the **broadcast** stream independently with XREAD (no group, no XACK).

Internal `nanfo:{realtime}:v1:fanout` entries contain a strict version-1 JSON
envelope: `version`, `kind` (`delta`/`heartbeat`/`reset`), `epoch` (leader token), `sequence`
(positive integer), `published_at` (Unix seconds), `delivery_id`, `channel`, and
`kwargs`. Delta kwargs are the existing manager push_delta arguments; channel is
topology/telemetry/digital-twin/alerts. This does not change the public WS contract.
The producer validates schema and bytes before publishing. Lua checks the current
lease token, increments sequence and XADDs with exact MAXLEN atomically. Publication
failure cancels durable consumption, rather than allowing its retry/DLQ path to ACK
unpublished work. Telemetry persistence and alert detection remain leader-only;
retry after commit republishes the same delivery identity.

Each subscriber captures the current stream tail **before** sockets are admitted,
then reads forward. New connections reconcile from REST as already required.
Sequence gaps, leader epoch changes, stale heartbeats, Redis disconnection,
malformed entries and local dispatch failure invalidate all local sockets using
WS_BACKPRESSURE/1013 (best effort), discard queued deltas and require reconnect plus
scoped REST reconciliation. Unavailable subscribers reject new subscriptions with
the same signal. A fresh baseline is established only after loss has been signalled.
Bounded broadcast retention is recovery detection, not durable client replay.
Dedup is bounded per-process LRU; duplicates outside that window may recur and
clients must retain their existing timestamp/idempotent delta handling. There is
no claim of exactly-once network delivery. Stream order is publish order, not a
global business-time order across independent domain streams.

No migrations or new public routes. Default ApiRealtimeLease singleton behavior is
retained. The following original handoff records the initial scope; the source
integration update above is authoritative for current main/config/readiness wiring.

## Exact parent integration

New helpers (all in `app.events`):

```python
# fanout_contract.py
FanoutSettings(
    stream_key="nanfo:{realtime}:v1:fanout",
    sequence_key="nanfo:{realtime}:v1:sequence",
    lease_key="nanfo:api:realtime:lease",
    max_entries=4096, max_payload_bytes=262144, batch_size=32, dedup_entries=4096,
    heartbeat_seconds=1.0, stale_seconds=5.0, io_timeout_seconds=2.0,
    lease_ttl_seconds=30.0, retry_seconds=1.0, shutdown_seconds=5.0,
)
# distributed_realtime.py
DistributedRealtime(redis, *, leader_factory, settings=None, managers=None,
                    on_lost=terminate_api)
fenced_handlers(handlers: dict, lease: ApiRealtimeLease) -> dict
await require_leadership(lease: ApiRealtimeLease) -> None
# leader_factory(lease) is an async context manager yielding Sequence[asyncio.Task].
# Runtime properties: healthy, lease (None on a follower), subscriber, task.
await runtime.verify() -> bool
# fanout.py, already used by the consumer bridges:
await push_realtime_delta(manager, *, channel: str, event: dict, **kwargs) -> None
```

Parent adds `API_REALTIME_DISTRIBUTED: bool = False` to its settings, and maps the
settings above to explicit validated `API_REALTIME_FANOUT_*` values if operational
overrides are needed. Reuse `API_REALTIME_LEASE_TTL_SECONDS`. No new settings are
read implicitly by these modules. Instantiate the same FanoutSettings on every
API. The default lease key deliberately equals the legacy singleton lease: a
rolling mixed-mode deployment cannot create two domain leaders. However **do not
route clients to distributed followers until all serving APIs run distributed
mode**; a legacy leader does not publish the required heartbeats.

Main lifespan composition, after Redis/Neo4j initialization and before `yield`:

```python
if not settings.API_REALTIME_DISTRIBUTED:
    # Existing singleton lifespan, collector, consumers and backfill unchanged.
    lease = await stack.enter_async_context(ApiRealtimeLease(
        redis, ttl_seconds=settings.API_REALTIME_LEASE_TTL_SECONDS))
    app.state.realtime_lease = lease
    await stack.enter_async_context(_runtime_lifespan(app, stack))
else:
    runtime = await stack.enter_async_context(DistributedRealtime(
        redis, settings=fanout_settings, leader_factory=leader_runtime))
    app.state.distributed_realtime = runtime
    app.state.realtime_lease = runtime  # verify() checks subscriber freshness.
```

The parent supplies `leader_runtime` by extracting its current leader-only
composition into this exact lifecycle shape (use a **local** exit stack each time,
not the serving API's outer stack):

```python
@asynccontextmanager
async def leader_runtime(lease):
    tasks = []
    async with AsyncExitStack() as leader_stack:
        # Register cleanup BEFORE startup. stop_runtime cancels and gathers every
        # consumer/watchdog and awaits collector.stop(), including partial startup.
        leader_stack.push_async_callback(stop_runtime)
        await require_leadership(lease)
        await ensure_consumer_groups(redis)
        # Start/configure the existing collector here, never in follower startup.
        # Wrap its poll_action: require_leadership; await actual_poll;
        # require_leadership. Keep its existing owning ingestion/idempotency checks.
        # Run the existing topology workspace backfill here, after fencing.
        handlers = fenced_handlers(all_handlers, lease)
        for stream_key, group in STREAM_GROUPS.items():
            tasks.append(asyncio.create_task(run_consumer_loop(
                redis=redis, stream_key=stream_key, group=group,
                consumer_name="nanfo-api", handlers=handlers,
                reclaim_idle_ms=settings.EVENT_RECLAIM_IDLE_MS,
                batch_size=settings.EVENT_CONSUMER_BATCH_SIZE,
                completion_ttl_seconds=settings.EVENT_COMPLETION_TTL_SECONDS,
                handler_timeout_seconds=settings.EVENT_HANDLER_TIMEOUT_SECONDS)))
        # Include a long-running collector watchdog in tasks. It must return/raise
        # if the configured collector stops or runtime_healthy becomes false;
        # otherwise a dead collector could leave consumers alive indefinitely.
        # The factory must not suppress cancellation or detach untracked work.
        app.state.consumer_tasks = tasks
        app.state.telemetry_collector = collector
        try:
            yield tasks
        finally:
            app.state.consumer_tasks = []
            app.state.telemetry_collector = None
```

`all_handlers` is the current `_merge_handlers` result; do not register domain
handlers in subscribers. `fenced_handlers` preserves handler module/qualname so
existing completion markers retain their identities. Context-local publisher
installation is inherited by all tasks created in `leader_runtime`; it resets on
exit. There is no process-global mutable publisher to leak into REST/follower work.
Every subscriber uses the existing singleton manager objects in **its own process**.

Startup captures the broadcast cursor before attempting leadership. The supervisor
creates a new factory lifecycle on acquisition; heartbeat publication starts after
the factory yields successfully. Main awaits a fresh broadcast before admission.
Follower acquisition retries continuously. A consumer cancellation (including failed
publication), return or failure cancels **all** leader work; bounded cleanup precedes
compare-and-delete lease release. Renewal failure, ownership loss at work completion,
or cleanup timeout calls `terminate_api` (`os._exit(1)`). The process supervisor must
restart it. This avoids an orphan collector running beyond leadership. On graceful
shutdown the leader work stops first, then the subscriber invalidates local sockets
and drains their deadline-bounded terminal writers, then the parent's stack may
close Redis. Keep the default fail-stop callback in
production; injected callbacks exist only for isolated lifecycle tests.

### Readiness / capability split

Parent must branch its `/ready` checks in distributed mode:

* `await runtime.verify()` is the per-API serving condition: running supervisor,
  independent subscriber, recent publication and live Redis. No leader lease is
  required on a follower. Missing/stale broadcasts return false even on idle networks.
* Local consumer count and local collector presence are leader-only diagnostics.
  Followers must not fail readiness because they intentionally have zero consumers
  and no collector. Mark those checks delegated in diagnostics rather than claiming
  a local collector exists. A leader checks its yielded tasks and collector health;
  the watchdog tears down leadership on failure.
* Keep dependency/storage checks. Do not change the telemetry capability to measured
  solely because a subscriber is healthy: that capability still requires the parent's
  configured, healthy measured source. Separate serving readiness from that capability.

### Bounds and failure semantics

* Exact stream MAXLEN4096; each encoded entry <=256KiB, so retained payloads have an
  approximately1GiB worst-case ceiling plus Redis overhead. Typical deltas are much
  smaller; operators should size/tune retention for expected traffic. Reads are at
  most32 entries; dispatch is serial and deadline-bounded. Per-socket defaults remain
  64 queued deltas/1MiB plus one in flight, with a5s auth/send timeout.
* Per-API delivery-ID LRU holds at most4096 identities. Duplicate publish retries
  still advance sequence but do not double-send within this window. Subscriber/API
  restart establishes a tail baseline; clients must REST-refetch, not expect replay.
* Epoch changes, missing sequence (including exact trim), malformed/version-mismatched
  or oversized entries, stale/future timestamps, socket queue overflow and subscriber
  outages close affected sockets. Bus-level uncertainty conservatively closes all
  channels on that API; reconciliation remains scoped to each client's subscriptions.
  Reconnection during an outage is also rejected. Error frames are best effort under
  network failure; transport close/reconnect carries the same reconciliation obligation.
* Lua checks lease, assigns monotonic sequence and appends atomically. ACK is allowed
  only after Redis confirms append, not after every socket receives it. Unknown append
  outcome cancels the durable consumer, leaving its PEL entry and no completion marker.
  Retried owning effects must use their existing durable event IDs/transactions;
  completion TTL and subscriber dedup do not confer exactly-once business effects.
  Oversized/invalid producer work is terminal only after confirmed bounded quarantine
  plus reset publication (see review fixes above); failures confirming that recovery
  remain pending and never silently ACK.
* Durable domain streams retain their established Redis persistence assumptions.
  Broadcast retention is intentionally lossy. Use a protected internal Redis service;
  arbitrary writers to internal keys can invalidate all sockets. Default legacy lease
  key requires standalone Redis, as used by deployment. Redis Cluster requires all
  three Lua keys to share a hash tag and a coordinated lease-key migration.
* Time freshness assumes bounded clock skew across APIs (default future tolerance2s).
  A resumed event loop also checks its monotonic freshness before accepting new data.
  Lease checks fence entry/exit of owning work and atomic fanout publication. They are
  not distributed transactions with external systems; owning durable idempotency and
  collector/device-specific authority remain mandatory for uncertain in-flight effects.

## Acceptance and cleanup

Opt-in command from `backend/`:

```bash
RUN_DISTRIBUTED_REALTIME=1 poetry run pytest tests/integration/test_distributed_realtime_sockets.py --no-cov -q
```

This starts two spawned Uvicorn processes using the real existing four WS routes,
production JWT/session/current-permission/current-membership validation and shared
real Redis. Only SQL/graph owner reads use deterministic scoped fixtures. Domain
idempotency crash acceptance uses a test-owned atomic Redis effect, while telemetry
unit coverage checks commit/replay-before-publication against its owning service.
It does not claim PostgreSQL retention or live collector/lab validation. Slow-client
acceptance injects server-side transport delay on an actual socket for deterministic
backpressure, rather than relying on OS send-buffer saturation.

The fixture uses installed image
`sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2`
(`redis:7-alpine` at validation time), `--pull=never --rm`, no volume mounts,
`127.0.0.1::6379`, and disabled persistence on this disposable Redis only. APIs bind
port0 with inherited bound sockets (no free-port race). Each test names all resources
`nanfo-realtime-<uuid>`. No existing Redis/container/database is mutated; no emulation.

Cleanup in `finally`: terminate owned API children, join4s, kill/join remaining
children, assert none alive, close process handles and bound sockets, close Redis,
`docker rm --force <exact-owned-name>`, then assert an exact-name Docker query is empty.
Container removal deletes only its ephemeral test data. No global flush/prune/kill.
Tests cover all-channel broadcast, missed/double/ordered delivery, committed-effect
crash replay, session/membership/permission revocation, malformed bus, exact trimming,
subscriber recovery, slow-client isolation, killed-leader failover/new API restart,
stale-publisher fencing, and live stolen-lease fail-stop/follower recovery.

### Recorded result (2026-09-20)

Final scoped gate: **187 passed in20.12s**, including both real two-process socket
campaigns; no skips in this command. Scoped Ruff passed. Tracked whitespace diff
check passed. Exact cleanup assertions passed and a final
`docker ps -a --filter name=nanfo-realtime-` check returned no containers.

```bash
RUN_DISTRIBUTED_REALTIME=1 poetry run pytest \
  tests/integration/test_distributed_realtime_sockets.py \
  tests/unit/test_distributed_realtime.py tests/unit/test_api_realtime_lease.py \
  tests/unit/test_event_recovery.py tests/unit/test_ws_push_consumer.py \
  tests/unit/test_telemetry_consumer.py tests/unit/test_websocket_delivery.py \
  tests/unit/test_websocket_auth_revalidation.py tests/unit/test_websocket_alerts.py \
  tests/unit/test_websocket_digital_twin.py tests/unit/test_websocket_digital_twin_auth.py \
  tests/integration/test_simulation_event_ws_flow.py \
  tests/integration/test_intent_event_ws_flow.py --no-cov -q
```

Earlier live stolen-lease acceptance exposed that a heartbeat could discover loss
before renewal, triggering graceful demotion rather than fail-stop. Fixed by
checking ownership when supervised leader work exits; the final test proves the
old process exits1 and the follower recovers. Two telemetry test failures exposed
concurrently added tombstone reads returning truthy unset mocks; test fixtures now
explicitly return no tombstone. Production telemetry persistence was not changed.

**Initial integration status (superseded above):** implemented and accepted in the
isolated helper composition before main/config/readiness ownership was delegated.
Legacy singleton remains the default. No commits or shared-resource mutations.
