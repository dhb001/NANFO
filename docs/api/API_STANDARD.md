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
* **GET:** Retrieve resources (200 OK).
* **POST:** Create new resources (201 Created).
* **PATCH:** Partially update resources (200 OK).
* **DELETE:** Soft-delete resources (204 No Content).
* **400 Bad Request:** For Pydantic validation failures.
* **401 Unauthorized:** Missing or invalid JWT.
* **403 Forbidden:** Valid JWT, but insufficient RBAC permissions.
* **422 Unprocessable Entity:** Malformed JSON payload.

## 4. Real-Time WebSockets
* **Channels:** Clients must subscribe exclusively to necessary channels (e.g., `/ws/telemetry`, `/ws/digital-twin`).
* **Delta Architecture:** To support 60 FPS rendering without bandwidth exhaustion, WebSocket payloads must be transmitted as incremental deltas. Only the specific values that have changed since the last tick are pushed over the wire.