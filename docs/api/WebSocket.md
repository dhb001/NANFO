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

## 2. Authentication

- The JWT access token must be provided as a query parameter on connection upgrade: `wss://<host>/ws/topology?token=<access_token>`.
- The server validates the token on connection. An invalid or missing token must reject the upgrade with HTTP `401 Unauthorized`.
- The server must re-validate the token's expiry before every delta push. On expiry, the server pushes a `WS_UNAUTHORIZED` error frame and closes the connection. The client must reconnect using a refreshed token.
- Credentials must never appear in WebSocket message payloads.

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
  "data": { "code": "WS_UNKNOWN_CHANNEL", "message": "Channel not registered." }
}
```

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

---

## 5. Backpressure and Error Signaling

When the server cannot keep up with delta volume (e.g., subscriber queue depth exceeds threshold), it sends a backpressure frame and may drop subsequent deltas until the client acknowledges:

```json
{
  "event": "error",
  "data": {
    "code": "WS_BACKPRESSURE",
    "message": "Delta queue capacity exceeded. Reconnect and re-fetch full state from REST endpoint."
  }
}
```

| Error Code | Cause |
|:--|:--|
| `WS_UNAUTHORIZED` | JWT expired or invalid during an active connection |
| `WS_UNKNOWN_CHANNEL` | Subscribe request for unregistered channel |
| `WS_BACKPRESSURE` | Server-side queue overflow |
| `WS_INVALID_FILTER` | Malformed or unauthorized filter parameters |

On any error code that signals session invalidity (`WS_UNAUTHORIZED`), the server closes the connection immediately after sending the error frame. The client is responsible for reconnect and re-fetch of full state.
