# ADR-009 Backend Live Validation

## Final Integrated Verification

Final parent-run command on 2026-09-08:
`PYTHONPATH=..:. poetry run python scripts/verify_emulation.py --live`.
Sanitized artifact: `/tmp/opencode/emulation-audit-2fpnq4g1/result.json`.

After final binder organization/workspace pagination hardening, the same live
command passed again: `/tmp/opencode/emulation-audit-qr967iwi/result.json`.
The full backend regression remained 1,230 passed / 1 optional SQL fixture skipped,
and Ruff over app/tests/scripts passed.

- Actual loopback HTTP/WebSocket, PostgreSQL, Redis and Neo4j: 9 nodes, 11 edges,
  12 snapshots, 2,672 unique rows and matching frames, zero duplicates.
- Partial publication: 102-sample prefix then full 204-sample replay after the
  producer advanced; final 244-sample retry also deduplicated.
- Measured peaks: throughput 20.577 Mbps (busiest port direction), link utilization
  98.048%, ping RTT 52.24 ms, leaf backlog 284,632 bytes / 97 packets. Actual probe
  loss was zero. These maxima may occur on different ports/times, not one sample.
- Independent workload: 19,216,408 delivered bytes; controller/OVS CLI TX deltas
  19,911,595 / 19,911,263 bytes (332-byte asynchronous sampling difference).
- All aggregation modes matched independent device/metric/unit/source/port/peer/
  run/bucket calculations; time bounds, scoped device history, observed/synthetic
  graph isolation and disabled-actor denial passed.
- Lab/backend stopped, audit actor disabled; retained evidence inventory/telemetry
  is audit-only and its binding is deliberately no longer authorized.

Final regression: backend 1,230 passed / 1 opt-in SQL fixture skipped; frontend
209 passed, 25 Chromium tests without retries, lint/typecheck/build/perf passed.
The live verifier independently exercised SQL aggregation on real PostgreSQL.

## Measurement Review Correction

The initial runs below established connectivity but did not certify correct
measurement identity or rate timing. Their sequence-based IDs duplicated cached
observations, their rate divisor used switch reply completion rather than port
duration, and their retry test did not advance the producer during a partial
batch. Those measurement claims are superseded by this corrected live run:

`/tmp/opencode/emulation-audit-0dupngy6/result.json`

- 2026-09-08 20:04:19..20:05:16 UTC: 9 nodes, 11 observed edges, 13 snapshots,
  2,876 unique measurement rows and 2,876 exact matching WebSocket frames.
- Observation IDs use run, bound device, dimensions and observation timestamp;
  port raw IDs also include duration, rate IDs include interval start/end. Sequence
  remains provenance only. Cached observations across later snapshots are deduped;
  conflicting identity reuse is rejected with bounded fingerprint state (131,072
  combined entries, freshness-window pruning, fail-closed on capacity).
- Full-publication acknowledgement now gates the next input read and baseline
  advancement. Live test published 102 samples of a 204-sample batch, withheld
  acknowledgement, confirmed producer advancement and replayed all 204 samples.
  A final 244-sample retry also produced no duplicate rows. Real Redis outage was
  not injected live; the unit/ingestion regression injects mid-batch failure and
  proves prefix deduplication plus persistence of the previously missing suffix.
- Pending retries revalidate current actor/membership. An expired pending batch
  raises an explicit retained-batch/operator-recovery error and does not consume
  newer snapshots. Pending state is memory-only: process restart discards it and
  is not durable recovery or an automatic loss-free remedy.
- Rates use actual OpenFlow port duration deltas; switch timestamp differences
  only gate freshness/order. Independent verifier calculation uses that duration.
  Peak throughput 20.531848 Mbps, utilization 98.192735%, RTT 28.632 ms, queue
  backlog 272,520 bytes/92 packets. Actual probe loss was 0%, not fabricated loss.
- Independent controller and OVS CLI TX deltas both 19,911,858 bytes; delivered
  traffic 19,219,304 bytes. Four aggregation modes matched independent grouping
  and values (18 groups each); time bounds/device scope passed.
- Real Neo4j tested observed/synthetic writes in both orders, two parallel observed
  links, parallel synthetic links under two generators, repeated merges, both
  replacement paths and pruning. Synthetic writer keys now include generator
  ownership and stable edge identity; observed links were preserved. Audit-only
  test edges were removed and the original observed graph restored.
- Actor disabled, later poll denied, temporary groups removed, owned backend/lab
  stopped; normal database containers remained healthy. No historical-query or
  frontend files were changed in this correction.
- Final regression: 1,230 passed, one SQL fixture test skipped for unset
  `TELEMETRY_TEST_DSN`; scoped Ruff and diff checks passed.

## Reproduce

From `backend/`, with normal backend settings pointing at the running NANFO
PostgreSQL, Redis and Neo4j services:

```bash
PYTHONPATH=..:. poetry run python scripts/verify_emulation.py --live
```

Requires the already-built lab image, Docker Compose and the checked-in
`emulation` package. Default audit timeout is 240 seconds; accepted explicit
`--timeout-seconds` range is 120..600. No credentials are accepted as arguments.
The script refuses an active local uvicorn/gunicorn process, active Redis stream
reader, or existing lab container. It never kills user processes or borrows a lab.

The verifier creates a randomized Identity-owned actor with in-memory credentials,
assigns the existing Admin role without modifying role/permission definitions,
and calls existing authenticated organization/workspace/network/device APIs.
No route dependencies or authentication are overridden. A random loopback TCP
port serves the real app, including an actual authenticated telemetry WebSocket.

Temporary tail-only Redis groups dispatch only audit-owned events to real audit,
topology, websocket and telemetry handlers. This avoids reading shared backlog or
running global topology backfills. Normal shared consumer groups are not changed;
audit events remain in streams and may be read by them on subsequent startup.
Temporary groups are destroyed at exit. The dedicated actor is disabled, and its
inventory/telemetry/audit evidence rows are retained, not destructively removed.
Normal telemetry health counters include these real ingestion operations.

The verifier starts the isolated lab using `emulation/control.py start`, drives
`traffic`, and stops only that lab using `stop`, including on handled failures.
Producer output artifacts are refreshed by this owned run. The separate operator
directory is a random mode-0700 `/tmp/opencode/emulation-audit-*` directory holding
mode-0600 `binding.json` and sanitized `result.json`, neither mounted into the lab.

## Live Evidence

Two successful runs on 2026-09-08, against the existing `nanfo_postgres`,
`nanfo_redis` and `nanfo_neo4j` containers. No migrations, resets, credential
changes, or unrelated row deletion were performed.

Final strengthened run:
`/tmp/opencode/emulation-audit-ejyln67z/result.json`

| Check | Actual Result |
| --- | --- |
| Authenticated inventory and binding UUID mapping | 9 devices, matched returned UUIDs |
| Topology REST, two-node pages including cross-page edges | 9 nodes, 11 observed edges |
| Polling and persistence | 12 snapshots, 2,896 unique rows |
| Explicit final batch retry | 252 retried samples, 0 duplicate rows |
| Actual telemetry WebSocket | 2,896 frames, unique IDs and matching payloads |
| Source provenance | synthetic=false, emulation, measured, fresh, source timestamps retained |
| First sample rates | Unavailable, no throughput/utilization fabricated |
| Source counter/rate/queue/probe calculations | Independently recomputed and matched |
| Maximum throughput | 20.527847 Mbps |
| Maximum per-port utilization | 98.226929% |
| Maximum ping RTT | 30.619 ms, explicitly RTT |
| Probe loss | 0%, explicitly probe loss, not PDR |
| Maximum queue backlog | 275,548 bytes; 95 packets |
| Raw port and flow counters | Nonzero, retained independently |
| Independent traffic delivery | 19,217,856 bytes |
| Controller TX delta / independent OVS CLI TX delta | 19,913,509 / 19,913,639 bytes |
| History aggregation API | avg/min/max/sum: 18 per-port groups each, matched independent calculations |
| Time bounds and device history | Inclusive start, exclusive end and device scope passed |
| Current actor revalidation | Disabled actor rejected on subsequent adapter poll |
| Cleanup | Actor disabled, temporary groups removed, isolated backend exited, owned lab stopped |

The earlier successful artifact is
`/tmp/opencode/emulation-audit-tom90k0s/result.json` (2,892 rows/frames).
Both dedicated evidence scopes remain in the database with disabled audit actors.

## Defect Fixed

`DeviceService.add_device()` published asyncpg's returned PostgreSQL INET object
directly. JSON serialization failed inside the existing fail-open event publish
path, allowing a host API create response without the topology event. The event
now serializes INET as a string while preserving null, with regression coverage in
`backend/tests/unit/test_emulation_inet_event.py`. Live creation projected all four
hosts through the real event consumer after the fix.

## Limits

- The real adapters, handlers, databases, authenticated HTTP and WebSocket paths
  were exercised. Normal app lifespan's shared consumer-group scheduling, global
  backfill, failure retries, dead-letter recovery and durable outbox were not.
- Zero observed ping loss is a successful measurement, not a missing fifth metric
  family. No artificial loss or fabricated nonzero value was introduced.
- Discovery remains visible through existing topology REST refresh; no new link
  event/channel or endpoint was introduced.
- Audit scope data is retained for evidence. The generated binding's actor is
  disabled after verification, so it is not an operational collector credential.
- No Step 5 control actions, Step 11 evaluator, production control, or durable
  exactly-once delivery is certified by this run.
- Full backend suite after the live fix: 1,214 passed, one dedicated SQL fixture
  test skipped because `TELEMETRY_TEST_DSN` was unset. The live verifier separately
  exercised all four aggregation modes against the actual configured PostgreSQL.
