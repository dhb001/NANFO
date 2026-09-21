# Event API

## Purpose
Define internal domain event contract conventions for all NANFO modules.

## Dependency
- Architecture boundaries: `.agents/rules/architecture-guardrails.md`.
- Event-to-channel routing: `docs/api/WebSocket.md` §1 (channel registry).

---

## 1. Event Naming Convention

All domain events must follow the pattern: `module.entity.action`

Examples: `auth.user.logged_in`, `network.device.added`, `org.workspace.created`.

- `module`: the owning module in lowercase (`auth`, `network`, `org`, `telemetry`).
- `entity`: the domain entity in snake_case (`user`, `device`, `workspace`).
- `action`: past-tense verb in snake_case (`logged_in`, `added`, `created`, `updated`, `deleted`).

> **Guardrail:** Per `.agents/rules/architecture-guardrails.md`, event type names must never be invented outside this documented naming pattern. New names require documentation in the owning module's PRD before use.

---

## 2. Mandatory Event Envelope

Every domain event, regardless of producer or consumer, must carry this envelope:

```json
{
  "event_id": "uuid",
  "event_type": "module.entity.action",
  "timestamp": "ISO8601",
  "source": "module-name",
  "correlation_id": "uuid",
  "version": "1",
  "payload": { }
}
```

| Field | Type | Requirement | Description |
|:--|:--|:--|:--|
| `event_id` | UUID | Required | Globally unique event identifier. Used for consumer idempotency deduplication. |
| `event_type` | String | Required | Full event name following `module.entity.action` convention. |
| `timestamp` | ISO8601 | Required | UTC timestamp of event production. |
| `source` | String | Required | Producing module name (e.g., `"network"`, `"auth"`). |
| `correlation_id` | UUID | Required | Traces the originating request through the system. Copied from the HTTP `request_id` when applicable. |
| `version` | String | Required | Integer string starting at `"1"`. Increment on breaking payload changes. |
| `payload` | Object | Required | Event-specific data. Schema governed by the producing module's PRD. |

---

## 3. Payload Schema Governance

- Payload field schemas are defined in the owning module's Feature PRD.
- Non-breaking additions (new optional fields) do not require a version bump.
- Removal, renaming, or type change of existing fields requires a version bump and a migration plan documented in the module's PRD.
- Consumers must tolerate unknown fields (forward-compatibility).

---

## 4. Delivery and Retry Expectations

- Delivery guarantee: **at-least-once** via Redis Streams consumer groups (ADR-006).
- Every consumer must implement idempotency using `event_id`: on receiving a duplicate `event_id`, the consumer must discard the event and ACK it.
- Failed messages (repeated processing failures) must be routed to a dead-letter queue for operator inspection.
- Consumers must explicitly ACK events after successful processing.

---

## 5. Event-to-WebSocket Channel Routing

When an event is consumed by a WebSocket push subscriber, it is translated into a channel delta. The routing table is:

| Event Type Pattern | Target WS Channel | Delta Type |
|:--|:--|:--|
| `network.device.added` | `/ws/topology` | `add` |
| `network.device.updated` | `/ws/topology` | `update` |
| `network.device.deleted` | `/ws/topology` | `remove` |
| `simulation.started` | `/ws/digital-twin` | scene delta (`update`) |
| `simulation.completed` | `/ws/digital-twin` | scene delta (`update`) |
| `simulation.paused` | `/ws/digital-twin` | scene delta (`update`) |
| `simulation.cancelled` | `/ws/digital-twin` | scene delta (`update`) |
| `simulation.branch_created` | `/ws/digital-twin` | scene delta (`update`) |
| `intent.validated` | `/ws/digital-twin` | scene delta (`update`) |
| `intent.execution_started` | `/ws/digital-twin` | scene delta (`update`) |
| `intent.execution_completed` | `/ws/digital-twin` | scene delta (`update`) |
| `intent.execution_failed` | `/ws/digital-twin` | scene delta (`update`) |
| `telemetry.*` | `/ws/telemetry` | metric delta |
| `alert.*` | `/ws/alerts` | alert delta |

> Full delta payload format for each channel is defined in `docs/api/WebSocket.md` §4.

## 6. Network inventory lifecycle (ADR-026)

`network.network.created`, `network.network.updated`, `network.network.deleted`,
`network.device.added`, `network.device.updated`, and `network.device.deleted` are
durably enqueued in the same PostgreSQL transaction as inventory mutation, then
published at least once to `stream:network`. Stable event ID, timestamp, correlation,
and serialized payload survive retry/restart. Delivery is ordered per network.
All six events route to the deduplicated Audit consumer; the device trio also routes
to the topology and websocket consumers in §5. Network update/delete are audit-only.

Future payloads all contain UUID strings `network_id`, `workspace_id`, `org_id`,
and `actor_id`; `org_id` is authoritative Organization-service output at mutation
time, allowing processing even after parent deletion. Device events also contain
`device_id`. Creation carries `name` for networks; device addition carries `hostname`,
`device_type`, nullable `ip_address` and nullable `spatial_ref_id`.

Both update events contain `changed_fields`, an object of effective changed values.
Network keys: `name`, `description`, `cidr`. Device keys: `hostname`, `ip_address`,
`device_type`, `vendor`, `model`, `location_hint`, `spatial_ref_id`. Nullable keys can
explicitly be null. Omitted or unchanged keys are absent; an all-unchanged PATCH
emits no event. Neo4j updates map these string/null values to node properties; a
null removes the property. Websocket update nodes preserve the exact delta plus
`device_id`. Addition includes IP and spatial reference; deletion emits a remove
delta containing only `device_id`. Existing projection revision/tombstone ordering
continues to prevent stale updates from reviving deleted devices.

These additive v1 payload fields do not rewrite older outbox envelopes or immutable
audit evidence. Historical missing tenant scope must never be repaired by weakening
tenant filters or silently changing stored history.
