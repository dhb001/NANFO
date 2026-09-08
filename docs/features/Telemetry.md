# Feature PRD: Telemetry Ingestion & Streaming

## Foundation Truth Boundary

Configured demo runtime adapters are synthetic samples or an empty stub;
no measured SNMP/gRPC collector is implied by an adapter name. Synthetic samples
carry `tags.synthetic=true` and `tags.execution_mode=demo`. Non-demo modes reject
synthetic runtime polling. Missing, malformed, nonfinite and boolean values are
rejected rather than coerced into zero measurements. Empty telemetry health has
`ingest_lag_ms=null` and `status=unavailable` (or degraded on known failures).
The global collector-health endpoint requires Admin capability plus active org
membership; tenant-scoped history remains available to authorized read-only users.

## Measured Emulation (Steps 3-4)

ADR-009 adds an `emulation` runtime adapter, only in `EXECUTION_MODE=emulation`.
It reads the isolated lab snapshot against an operator-owned inventory binding,
rechecks actor capabilities/membership, and ingests actual OpenFlow counters,
duration-derived port rates, capacity-normalized utilization, Linux queue backlog,
ping RTT and probe loss. Tags distinguish measured emulation from synthetic or
physical data. Cached observations keep stable event IDs across export sequences;
pending batches are acknowledged only after full publication. Stale pending data
blocks explicitly. No durable outbox is claimed.

History/device queries support aware `start_time` inclusive and `end_time`
exclusive, normalized to UTC. History supports `aggregation=avg|min|max|sum` with
required metric, both time bounds (at most seven days), and `bucket_seconds`
1..86400. Grouping includes device, metric, unit, source, port, probe peer and run.
Raw flow counters remain queryable, but `flow_*` aggregation is rejected because
snapshot v1 does not expose durable per-flow match identity. Empty buckets are not
zero-filled. Existing endpoints and tenant checks remain authoritative.

## 1. Purpose
Collect, validate, normalize, store, and stream high-frequency telemetry to drive AI reasoning, alerting, and digital twin updates.

## 2. Requirements
- Implement modular collectors with shared lifecycle interface.
- Normalize vendor-specific metrics into canonical schema.
- Publish domain events for multi-consumer processing.
- Stream incremental deltas to subscribed WebSocket channels.

## 3. API Endpoints
All endpoints must follow `docs/api/API_STANDARD.md`.
- `GET /api/v1/telemetry/history`
- `GET /api/v1/telemetry/device/{id}`
- `GET /api/v1/telemetry/health`

## 4. Streaming Channels

Each channel serves a distinct event domain. Clients must subscribe exclusively to the channels required for their function (per `docs/api/API_STANDARD.md` §4).

| Channel | Domain | Primary Producer | Payload Type |
|:--|:--|:--|:--|
| `/ws/telemetry` | High-frequency metric deltas (bandwidth, CPU, latency, signal strength) | Telemetry module | Metric delta |
| `/ws/alerts` | Alert state changes and threshold breaches | Alerting module (future) | Alert delta |
| `/ws/digital-twin` | 3D scene object position and state updates | Digital Twin module (M6) | Scene delta |
| `/ws/topology` | Network topology structural changes (device/link lifecycle) | Network module (Event Bus consumer) | Topology delta |

> **Channel separation rationale:** Topology structural events (`network.device.added`, `network.device.updated`, `network.device.deleted`) represent changes to the network object graph and are consumed by topology renderers and graph consumers. They must not be multiplexed with high-frequency metric telemetry on `/ws/telemetry` to avoid forcing topology consumers to filter irrelevant metric noise and to prevent metric consumers from processing structural graph changes.
> See `docs/api/WebSocket.md` for subscription protocol, delta payload format, and backpressure semantics.

## 5. Risks
- Data quality degradation from malformed source payloads.
- Backpressure under bursty traffic without queue tuning.

## 6. Acceptance Criteria
- [ ] Collector failures trigger alert + retry with backoff.
- [ ] Canonical schema validation rejects malformed payloads.
- [ ] Consumers receive event deltas without polling.
- [ ] Telemetry health endpoint reports ingest lag and drop counters.
