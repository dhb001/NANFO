# Feature PRD: Telemetry Ingestion & Streaming

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
