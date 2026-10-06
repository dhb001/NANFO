# WebSocket Conventions

## Purpose
Define real-time channel naming, subscription protocol, delta payload format, authentication, and backpressure/error signaling for all NANFO WebSocket connections.

## Dependency
- Global response/error semantics: `docs/api/API_STANDARD.md`.
- Canonical channel registry: `docs/features/Telemetry.md` §4.
- Architecture boundaries: `.agents/rules/architecture-guardrails.md`.

---

## 1. Channel Registry

The authoritative channel list lives in `docs/features/Telemetry.md` §4. The current canonical channels are:

| Channel | Domain |
|:--|:--|
| `/ws/telemetry` | High-frequency metric deltas |
| `/ws/alerts` | Alert state changes |
| `/ws/digital-twin` | 3D scene object updates |
| `/ws/topology` | Network topology structural changes |

> New channels must be added to `Telemetry.md` §4 first. No WebSocket channel may be opened without a registered canonical entry.

---

## 2. Authentication (ADR-028 C1)

- Connect to `/ws/<channel>` **without** a query string. Offer the subprotocols
  `["nanfo.v1", "nanfo.bearer.<access_token>"]`. The server selects exactly `nanfo.v1` and
  never echoes the bearer entry. A bearer entry is valid only alongside `nanfo.v1`, and
  only one may be offered.
- The legacy form `wss://<host>/ws/<channel>?token=<access_token>` is still accepted for
  one compatibility release. New clients must not use it; the server redacts the query
  string from every log line.
- A missing, invalid, expired or unauthorized token is refused **before accept** with close
  1008 (the upgrade fails with HTTP 403; browsers may report 1006).
- Authentication runs once per connection. Its decision seeds a per-connection
  authorization cache that lasts at most `WS_AUTH_CACHE_SECONDS` (15 s) and never outlives
  the token `exp`.
- At token expiry the server sends `WS_UNAUTHORIZED` and closes 1008, even on an idle
  channel. The client refreshes once and reconnects with the new token.
- A backing-service outage during authentication, subscription or revalidation is never
  reported as an authentication failure: the server accepts, sends `WS_UNAVAILABLE` and
  closes 1013. Clients retry with jittered backoff and do not rotate the token.
- Credentials must never appear in WebSocket message payloads.
- Only access tokens with a live Redis session are accepted; refresh tokens are
  rejected. After the cache window, every delivery checks current identity, capability
  and organization membership, not only token expiry. Alerts subscriptions enumerate
  authorized workspaces even when the login token has no tenant claim. Missing event
  scope never grants global delivery.
- Browser upgrade rejection can appear as close 1006. Clients use a bounded
  authenticated REST probe with cooldown after inconclusive transport failures;
  only a confirmed authentication failure triggers token rotation.

---

## 3. Subscription Protocol

After a successful connection upgrade, the client sends a subscribe frame:

```json
{
  "action": "subscribe",
  "channel": "topology",
  "filters": {
    "network_id": "uuid"
  }
}
```

The server acknowledges:

```json
{
  "event": "subscribed",
  "channel": "topology",
  "filters": { "network_id": "uuid" },
  "timestamp": "ISO8601"
}
```

Clients must not send subscribe frames for channels not in the canonical registry. A request for an unknown channel receives:

```json
{
  "event": "error",
  "data": { "code": "WS_UNKNOWN_CHANNEL", "message": "Subscription denied." }
}
```

The frame is strict: exactly `action`, `channel` and `filters`, with string values.
`channel` must match the connected `/ws/<channel>`. `/ws/topology`, `/ws/telemetry` and
`/ws/digital-twin` require exactly `filters.network_id` (a UUID); `/ws/alerts` accepts no
filters. The frame must arrive within `WS_SUBSCRIBE_TIMEOUT_SECONDS` (10 s), otherwise
the server sends `WS_SUBSCRIBE_TIMEOUT` and closes 1013. Inbound frames larger than
`WS_MAX_FRAME_BYTES` (64 KiB) close the socket with 1009. A user may hold at most
`WS_MAX_CONNECTIONS_PER_USER` (16) sockets.

---

## 4. Delta Payload Requirements

All server-push payloads are **incremental deltas only**. The server must never push a full state snapshot over a WebSocket channel. Full state is retrieved via the corresponding REST endpoint before the WebSocket connection is established.

### 4.1 Topology Delta (channel: `/ws/topology`)

```json
{
  "event": "topology.device.added",
  "correlation_id": "uuid",
  "timestamp": "ISO8601",
  "data": {
    "delta_type": "add",
    "node": {
      "device_id": "uuid",
      "hostname": "string",
      "device_type": "string",
      "status": "string"
    }
  }
}
```

`delta_type` values: `add` | `update` | `remove`.

For `update` deltas, only the changed fields are included in `node`:

```json
{
  "event": "topology.device.updated",
  "correlation_id": "uuid",
  "timestamp": "ISO8601",
  "data": {
    "delta_type": "update",
    "node": {
      "device_id": "uuid",
      "status": "offline"
    }
  }
}
```

For `remove` deltas:

```json
{
  "event": "topology.device.removed",
  "correlation_id": "uuid",
  "timestamp": "ISO8601",
  "data": {
    "delta_type": "remove",
    "node": { "device_id": "uuid" }
  }
}
```

### 4.2 Digital Twin Scene Delta (channel: `/ws/digital-twin`)

```json
{
  "event": "simulation.started",
  "correlation_id": "uuid",
  "timestamp": "ISO8601",
  "data": {
    "delta_type": "update",
    "scene_object": {
      "id": "simulation-state",
      "object_type": "simulation_state",
      "state": "queued",
      "simulation_id": "uuid",
      "scenario_id": "uuid",
      "risk_gate": "required",
      "status": "queued",
      "changed_fields": {
        "state": "queued",
        "status": "queued",
        "risk_gate": "required",
        "scenario_id": "uuid"
      }
    }
  }
}
```

`simulation.completed`, `simulation.paused`, `simulation.cancelled`, and `simulation.branch_created` reuse the same shape with updated lifecycle `state`, `status`, and `risk_gate` values.

`intent.validated`, `intent.execution_started`, `intent.execution_completed`, and `intent.execution_failed` are translated to `/ws/digital-twin` `scene_object` deltas using `object_type="intent_state"` with lifecycle fields (`intent_id`, `status`, `intent_kind`) and optional confidence metadata in `changed_fields`.

---

## 5. Backpressure and Error Signaling

When the server cannot keep up with delta volume (e.g., subscriber queue depth exceeds threshold), it sends a backpressure frame and closes the socket with 1013:

```json
{
  "event": "error",
  "data": {
    "code": "WS_BACKPRESSURE",
    "message": "Delta queue capacity exceeded. Reconnect and re-fetch full state from REST endpoint."
  }
}
```

Every error frame is followed by a close. Close codes and client behaviour (ADR-028 C1):

| Error Code | Close | Cause | Client action |
|:--|:--|:--|:--|
| `WS_UNAUTHORIZED` | 1008 | Token expired, revoked or no longer authorized during an active connection | Refresh once, then reconnect with the new token |
| `WS_UNAVAILABLE` | 1013 (1011 for an unexpected server error) | Backing-service outage during authentication, subscription or revalidation | Retry with jittered backoff; not an authentication or filter error |
| `WS_SUBSCRIBE_TIMEOUT` | 1013 | No subscribe frame within 10 s | Retry with jittered backoff |
| `WS_CONNECTION_LIMIT` | 1008 | The user already holds `WS_MAX_CONNECTIONS_PER_USER` sockets | Stop retrying; show a visible *Retry realtime* control |
| `WS_BACKPRESSURE` | 1013 | Server-side queue overflow | Reconnect and re-fetch full state from REST |
| `WS_UNKNOWN_CHANNEL` | 1008 | Subscribe request for an unregistered or different channel | Terminal |
| `WS_INVALID_FILTER` | 1008 | Malformed frame, or filters that are invalid or not authorized | Terminal |
| `WS_FORBIDDEN` | 1008 | Reserved terminal code; the current server reports a denied subscription as `WS_INVALID_FILTER` | Terminal |
| (no frame) | 1008 | Credentials refused before accept | Refresh or log in, then reconnect |
| (no frame) | 1009 | Inbound frame larger than `WS_MAX_FRAME_BYTES` | Terminal (client defect) |

Terminal codes are never retried automatically. After reconnecting, the client re-fetches
full state from REST.
