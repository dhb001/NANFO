# **Chapter 10 – API Specifications, WebSockets, SDK Architecture & Internal Communication**

## **10.1 Introduction & API-First Philosophy**

Every operational feature, administrative action, and AI interaction within the Neuro-Adaptive Network Flow Orchestrator (NANFO) must be accessible through a fully documented, versioned application programming interface (API). The frontend application never accesses the backend databases directly.

This rigid separation is enforced through an **API-First Design Philosophy** that guarantees:

* **Decoupling:** Frontend interfaces, AI agents, and third-party integrations operate independently of the underlying Polyglot Persistence layers.  
* **Security by Default:** All requests undergo centralized authentication, Role-Based Access Control (RBAC) validation, and rate limiting at the gateway before business logic executes.  
* **Extensibility:** By standardizing the interfaces, the platform paves the way for a future transition from a Modular Monolith to distributed microservices.  
* **Real-Time Responsiveness:** The architecture splits synchronous operational commands (REST) from high-frequency, low-latency data streaming (WebSockets).

## **10.2 API Gateway, Routing & REST Specifications**

The FastAPI-driven backend serves as the unified API Gateway. To ensure backward compatibility as the platform evolves, all endpoints are strictly versioned within the URI path (e.g., `/api/v1/auth`, `/api/v1/campuses`). Major architectural shifts will introduce an `/api/v2/` namespace rather than breaking existing client contracts.

### **10.2.1 Standard API Response Format**

To simplify frontend state management and debugging, every REST endpoint returns a predictable, standardized JSON payload structure:

JSON  
{  
  "success": true,  
  "data": {  
    "device\_id": "AP-ENG-203",  
    "status": "online"  
  },  
  "meta": {  
    "request\_id": "req\_8f92a1b4",  
    "timestamp": "2026-08-05T12:30:20Z",  
    "execution\_time\_ms": 25  
  },  
  "errors": null  
}

### **10.2.2 Standard Error Responses**

When validation or business logic fails, the API returns descriptive error codes without exposing sensitive backend stack traces:

JSON  
{  
  "success": false,  
  "data": null,  
  "meta": {  
    "request\_id": "req\_9f33b2c1",  
    "timestamp": "2026-08-05T12:30:22Z"  
  },  
  "errors": {  
    "code": "DEVICE\_NOT\_FOUND",  
    "message": "The requested device does not exist or lacks sufficient RBAC permissions."  
  }  
}

## **10.3 Core REST Endpoints & GraphQL Integration**

The REST API exposes the full spectrum of NANFO's operational capabilities.

### **10.3.1 Domain Endpoints**

* **Authentication API:** `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `POST /api/v1/auth/refresh`, `GET /api/v1/auth/me`.  
* **Campus & Building API:** `GET /api/v1/campuses`, `POST /api/v1/import/osm`, `POST /api/v1/buildings`.  
* **Device & Infrastructure API:** `GET /api/v1/devices`, `PATCH /api/v1/devices/{id}`, `POST /api/v1/devices/{id}/reboot`, `POST /api/v1/devices/{id}/backup`, `POST /api/v1/devices/{id}/firmware`.  
* **Telemetry & Alerts API:** `GET /api/v1/telemetry/history`, `GET /api/v1/telemetry/device/{id}`, `POST /api/v1/alerts/{id}/ack`, `POST /api/v1/alerts/{id}/resolve`.  
* **Simulation API:** `POST /api/v1/simulations/start`, `POST /api/v1/simulations/pause`, `POST /api/v1/simulations/branch`, `GET /api/v1/replay/{id}`.  
* **AIOS API:** `POST /api/v1/ai/predict`, `POST /api/v1/ai/recommend`, `POST /api/v1/ai/explain`, `GET /api/v1/ai/models`.  
* **Reporting & Search API:** `POST /api/v1/reports/generate` (PDF/CSV/Excel), `GET /api/v1/search?q={query}` (Global fuzzy matching).

### **10.3.2 The GraphQL Gateway Recommendation**

While REST is utilized for standard CRUD operations, network administrators frequently require data that spans multiple relational bounds. For example: *"Show every Access Point in the Engineering Building, their connected switches, current client count, CPU utilization, active alerts, and AI recommendations."*

Executing this via REST requires multiple round-trip requests. Consequently, NANFO introduces a **GraphQL Gateway** alongside the REST API. This allows the frontend dashboard to retrieve complex, multi-resource hierarchies in a single, optimized query, drastically reducing network overhead.

## **10.4 Real-Time WebSockets & Streaming Telemetry**

To power the 3D Digital Twin and ensure the operational workspace functions as a "living world," NANFO utilizes stateful WebSockets. Rather than forcing the frontend to constantly poll the API every few seconds—which would rapidly saturate the backend—the platform streams live updates.

### **10.4.1 WebSocket Channels**

Clients subscribe exclusively to the channels they require:

* `/ws/telemetry`: Streams high-frequency device metrics (CPU, bandwidth, latency).  
* `/ws/alerts`: Pushes critical incident and security notifications instantly.  
* `/ws/digital-twin`: Broadcasts physical object state changes, packet animation coordinates, and spatial heatmap fluctuations.  
* `/ws/simulation`: Streams physics engine progression and clock ticks during active scenario execution.  
* `/ws/ai`: Streams natural-language reasoning, multi-agent debate consensus generation, and interactive mentor explanations.

### **10.4.2 Delta Payload Architecture**

To support 60 FPS rendering in the Digital Twin without bandwidth exhaustion, WebSocket payloads are transmitted as **incremental deltas**. Only the specific values that have changed since the last tick are pushed over the wire.

JSON  
{  
  "type": "telemetry.update",  
  "deviceId": "AP-ENG-203",  
  "metric": "cpu",  
  "value": 72,  
  "timestamp": "2026-08-05T12:31:05Z"  
}

## **10.5 Internal Domain Events & Message Broker Contracts**

Inside the Modular Monolith, subsystems coordinate their logic via an **Internal Event Bus (Redis)**. This event-driven architecture prevents tight coupling and ensures that an error in the Reporting Module does not crash the Telemetry Module.

Every time a significant state change occurs, a structured **Event Contract** is emitted.

### **10.5.1 Example Event Contracts**

* `device.created`, `device.updated`, `device.offline`.  
* `telemetry.received`, `telemetry.threshold_exceeded`.  
* `alert.generated`, `alert.resolved`.  
* `simulation.started`, `simulation.completed`.  
* `ai.recommendation.generated`.

Each event payload includes a unique `Event ID`, `Event Type`, `Timestamp`, the `Source Service`, and a `Correlation ID` to ensure execution traces can be accurately tracked across the entire monolith.

## **10.6 The NANFO SDK, Extensibility & Plugin Architecture**

To guarantee that NANFO remains an open, extensible ecosystem capable of long-term commercialization and academic research, the platform exposes a comprehensive **Developer SDK** and **Plugin API**.

### **10.6.1 The Plugin Lifecycle**

Third-party developers can write plugins to introduce custom device types, visualization overlays, report templates, external analytics integrations, and new AI models without modifying the core platform. Plugins operate in an isolated sandbox and follow a strict lifecycle: `Install` → `Validate Signature & Dependencies` → `Enable` → `Load APIs` → `Run` → `Disable` → `Uninstall`.

### **10.6.2 The AI Interface Contract**

To allow researchers to test novel machine learning models (e.g., swapping a local LLM or a new DRL agent into the AIOS Orchestrator), every third-party AI plugin must implement a strict programmatic interface:

* `loadModel()`: Initializes the agent into memory.  
* `predict()`: Forecasts future metrics based on input telemetry.  
* `explain()`: Generates the mandatory human-readable justification and evidence list for XAI compliance.  
* `evaluate()`: Returns benchmark metrics for the Confidence Escalation Framework.  
* `getMetadata()`: Registers the model version and algorithm type into the UEDF.

### **10.6.3 The Digital Twin SDK**

Most enterprise platforms only expose REST APIs; NANFO exposes the 3D scene graph itself. Through the Digital Twin SDK, developers can build interactive applications directly on top of the campus environment. Examples include indoor spatial navigation plugins, Augmented Reality (AR) maintenance overlays for field engineers, energy optimization visualizers, or smart-building HVAC integrations. By exposing the scene graph, telemetry streams, and the simulation engine natively, NANFO transforms from a standalone management tool into an extensible platform ecosystem.

