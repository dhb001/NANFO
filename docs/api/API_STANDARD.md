# NANFO API Standards

## 1. Architectural Style & Versioning
* All REST endpoints must follow resource-oriented conventions.
* All endpoints must be strictly versioned within the URI path (e.g., `/api/v1/campuses`).
* Major breaking architectural shifts introduce an `/api/v2/` namespace rather than breaking existing client contracts.

## 2. Standard REST Envelope
Every REST endpoint must return a predictable, standardized JSON payload structure.

**Success Response:**
```json
{
  "success": true,
  "data": {
    "device_id": "AP-ENG-203",
    "status": "online"
  },
  "meta": {
    "request_id": "req_8f92a1b4",
    "timestamp": "2026-08-05T12:30:20Z",
    "execution_time_ms": 25
  },
  "errors": null
}
```

**Error Response:**
```json
{
  "success": false,
  "data": null,
  "meta": {
    "request_id": "req_9f33b2c1",
    "timestamp": "2026-08-05T12:30:22Z"
  },
  "errors": {
    "code": "DEVICE_NOT_FOUND",
    "message": "The requested device does not exist or lacks sufficient RBAC permissions."
  }
}
```

## 3. HTTP Methods & Status Codes
Response `meta` also includes `execution_mode`: `demo`, `emulation`, or
`production`, sourced from backend configuration. This describes the configured
environment, not installed controller/model capabilities. An HTTP-success envelope
can contain a failed domain operation; clients must inspect its lifecycle status.

* **GET:** Retrieve resources (200 OK).
* **POST:** Create new resources (201 Created).
* **PATCH:** Partially update resources (200 OK).
* **DELETE:** Soft-delete resources (204 No Content).
* **400 Bad Request:** An unparseable body (`BAD_REQUEST`), or a domain request error with
  its own code.
* **401 Unauthorized:** Missing or invalid JWT (`AUTH_TOKEN_MISSING_OR_INVALID`).
* **403 Forbidden:** Valid JWT, but insufficient RBAC permissions.
* **409 Conflict:** A state or concurrency conflict, with a stable domain code.
* **413 Payload Too Large:** `REQUEST_TOO_LARGE` when the body exceeds the route limit:
  1 MiB by default, 12 MiB for campus model-asset upload, 8 MiB for a spatial-scene `PUT`.
* **422 Unprocessable Entity:** Request validation failure (`VALIDATION_ERROR`). ADR-028
  C2 replaces the earlier "400 for Pydantic validation" rule.
* **429 Too Many Requests:** Throttling or an active-work quota, with `Retry-After` where
  the owner defines one.
* **503 Service Unavailable:** `DEPENDENCY_UNAVAILABLE` with `Retry-After` when
  PostgreSQL, Redis, Neo4j or storage is unavailable. A session-store outage is 503, never
  401, so clients keep the session and retry.
* **507 Insufficient Storage:** Per-network campus asset and per-organisation report
  quotas.

Validation errors (ADR-028 C2) add `errors.details`, at most 20 entries of
`{"loc": [...], "type": "..."}`. Input values and validator context are never returned,
and location names the route does not declare are masked as `"*"`:

```json
{
  "success": false,
  "data": null,
  "meta": {"request_id": "req_9f33b2c1", "timestamp": "2026-09-24T12:30:22Z"},
  "errors": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [{"loc": ["body", "page_size"], "type": "less_than_equal"}]
  }
}
```

Unhandled errors return a generic 500 without exception text; the server logs a redacted
stack (types and frames only) with the request id. The full list of ADR-028 contract
changes is in `ADR028-ContractChanges.md`.

## 4. Real-Time WebSockets
* **Channels:** Clients must subscribe exclusively to necessary channels (e.g., `/ws/telemetry`, `/ws/digital-twin`).
* **Delta Architecture:** To support 60 FPS rendering without bandwidth exhaustion, WebSocket payloads must be transmitted as incremental deltas. Only the specific values that have changed since the last tick are pushed over the wire.
* **Authentication:** The bearer token travels in the `Sec-WebSocket-Protocol` header, never in the URL (ADR-028 C1). Close codes and retry rules are in `WebSocket.md` §2 and §5.
