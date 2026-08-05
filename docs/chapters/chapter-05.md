# **Chapter 5 – Unified Enterprise Data Fabric, Polyglot Persistence & Telemetry Engine**

## **5.1 Introduction & Vision**

The Unified Enterprise Data Fabric (UEDF) serves as the core information backbone of NANFO. Rather than storing operational metrics, configurations, and topology data in isolated, proprietary databases, the UEDF creates a unified semantic layer. This layer connects every entity, event, metric, configuration, simulation, recommendation, workflow, and historical record into a single enterprise knowledge ecosystem.

This architecture enables the AI Operating System (AIOS), the Digital Twin Engine, the Network Hypervisor, and the Network Physics Engine to reason over the exact same trusted information. Instead of querying disparate data stores, the platform relies on an **Enterprise Digital Memory (EDM)**—an institutional memory that permanently correlates incidents, topologies, AI conversations, administrator decisions, and rollbacks. This ensures that years later, the platform can answer complex historical queries regarding past outages, remediation steps, and their long-term efficacy.

## **5.2 Polyglot Persistence Architecture**

NANFO abandons the traditional monolithic database pattern in favor of a Polyglot Persistence Architecture, deploying specialized storage technologies tailored to the specific operational profile of each data domain:

```text
                       Application Layer
                                │
                    Repository / Service Layer
                                │
 ┌──────────────┬───────────────┴──────────────┬──────────────┐
 │              │                              │              │
PostgreSQL  TimescaleDB                      Neo4j          Redis
 │              │                              │              │
Relational  Telemetry                      Topology &      Cache &
  Data       History                       Knowledge       Sessions
                                             Graph
```

* **PostgreSQL (Relational Transactional Data):** Serves as the primary transactional datastore, maintaining Third Normal Form (3NF) structures with targeted denormalization for performance and soft-deletion for historical tracking. It manages structured configurations, users, RBAC roles, devices, buildings, workflows, simulations, and audit logs.  
* **TimescaleDB (High-Frequency Time-Series Telemetry):** A specialized PostgreSQL extension optimized for high-volume time-series ingestion. It stores CPU utilization, memory pressure, temperature, signal strength, throughput, packet loss, and latency metrics via efficient time-based partitioning and compression policies.  
* **Neo4j (Knowledge Graph & Topology):** Manages network topology, spatial containment, and semantic relationship mapping.  
* **Redis (Low-Latency Cache & Event Routing):** Facilitates real-time operations by storing active user sessions, JWT blacklists, WebSocket channel subscriptions, live Digital Twin states, telemetry caches, and asynchronous job queues.  
* **Object Storage (MinIO / S3 / OCI):** Isolates large binary artifacts from primary relational databases, housing 3D glTF/OBJ models, floor plan blueprints, firmware binaries, execution reports, and configuration backups.

## **5.3 Database Schemas & Universal Object Model (UOM)**

To enforce strict security boundaries and access permissions, PostgreSQL is segmented into isolated domains: auth, campus, network, telemetry, simulation, ai, reporting, plugin, audit, and system.

### **5.3.1 Universal Object Model (UOM) & Versioning**

Every managed entity in NANFO inherits from a common abstract **Universal Object Model (UOM)**. This guarantees that all objects share consistent core attributes: Global Object ID, Name, Description, Tags, Created Date, Updated Date, Owner, RBAC Permissions, and Status.

Furthermore, significant network configuration changes do not overwrite historical records. Instead, they generate **new immutable versions** complete with metadata tags, timestamps, and author attribution. This underpins the platform's ability to execute instant rollbacks, historical comparisons, and compliance auditing.

### **5.3.2 Relational Entity Hierarchy**

The relational schema follows a predictable, hierarchical structure:

* **Organizations & Campuses:** organizations maps to multiple campuses (containing geographic boundaries, time zones, and OSM references).  
* **Spatial Containers:** buildings (footprint geometry, height, levels) $\\rightarrow$ floors (elevation, navigation mesh) $\\rightarrow$ rooms (capacity, material properties for RF simulation) $\\rightarrow$ racks (power/cooling capacity, U-height).  
* **Infrastructure Elements:** devices (vendor, model, management IP, MAC, health score), interfaces (speed, duplex, VLAN, PoE), and links (medium, bandwidth, status). Vendor-specific attributes (e.g., PoE power budgets) are stored flexibly in PostgreSQL JSONB columns to keep the core schema stable.  
* **Wireless & Access Control:** wireless\_zones (coverage polygons, noise) and clients (mobility profiles, current AP associations), alongside RBAC tables (users, roles, permissions, user\_roles) and an append-only audit\_logs table that is permanently protected from modification or deletion.

## **5.4 The Enterprise Knowledge Graph (EKG)**

To move beyond traditional, rigid SQL joins, NANFO overlays a Knowledge Graph (Neo4j) on top of the domain model, unlocking advanced impact analysis and contextual AI reasoning.

* **Semantic Relationships:** Objects are connected via first-class relationship edges such as located\_in, connected\_to, managed\_by, powered\_by, depends\_on, simulated\_by, recommended\_by, and affected\_by.  
* **Cross-Domain Intelligence:** The graph unifies previously isolated operational domains. For instance, the AI can correlate human student density (Human Layer) with Wi-Fi signal attenuation (Wireless Layer) and power circuit loads (Environment Layer) to predict future bottleneck corridors.  
* **Network DNA Profiling:** Generates a comprehensive architectural profile summarizing redundancy levels, security posture, wireless maturity, device diversity, sustainability scores, and automation readiness across campuses.  
* **Unified Object Explorer:** Selecting any entity (e.g., Access Point AP-ENG-203) queries the Knowledge Graph to instantly expose its 3D spatial location, live telemetry, firmware version, configuration history, AI recommendations, maintenance records, and related incident tickets without requiring module switching.

## **5.5 Telemetry Engine & Ingestion Pipeline**

The Telemetry Engine acts as an event-driven data platform responsible for continuously collecting, validating, normalizing, and distributing network metrics across the platform. It guarantees low latency, high reliability, and seamless replay capabilities.

```text
       Physical Network
               │
               ▼
     Telemetry Collectors
               │
               ▼
   Validation & Normalization
               │
               ▼
   Telemetry Event Bus (Redis)
     ┌─────────┼─────────┐
     ▼         ▼         ▼
TimescaleDB   AIOS   Alert Engine
     │         │         │
     ▼         ▼         ▼
   Replay  Predictions Notifications
     │
```

     ▼

Digital Twin

### **5.5.1 Collection & Normalization Pipeline**

The engine deploys a modular collector architecture (OpenFlow Collector, SNMP Collector, Syslog Collector, Wireless Collector, API Collector) implementing a shared interface (connect(), collect(), validate(), normalize(), publish()).

* **Validation:** Raw telemetry is subjected to schema checking, timestamp verification, range validation, and duplicate detection. Malformed data is quarantined for inspection rather than silently dropped.  
* **Normalization:** Vendor-specific metric naming conventions (e.g., Cisco's ifInOctets versus Juniper's input-octets) are translated into a standardized internal JSON schema. This abstraction is critical to maintaining total vendor neutrality.

### **5.5.2 Event Processing & Real-Time Distribution**

Telemetry is collected once and consumed by multiple subsystems asynchronously. Every metric update generates an event (e.g., BandwidthSpike, DeviceOffline, APOverloaded) published directly to the Telemetry Event Bus.

* No subsystem polls the database for live updates; the AI Engine, Alert Engine, and Digital Twin react strictly to incoming event broadcasts.  
* The WebSocket Gateway streams incremental delta updates to the frontend via dedicated channels (/ws/telemetry, /ws/alerts, /ws/heatmaps), ensuring only changed values cross the wire to optimize bandwidth.

## **5.6 Replay Buffer, Time Machine & Data Lineage**

The tight integration of the UEDF and the Telemetry Engine powers NANFO's signature **Time Machine** and historical replay capabilities.

* **Replay Engine:** Every telemetry record is permanently timestamped and stored in TimescaleDB. When an administrator manipulates the UI timeline slider, the Replay Engine reconstructs the exact network state, packet animations, heatmaps, and AI recommendations as they existed at that historical instant.  
* **Data Lineage & Provenance:** Every piece of operational data tracks its exact provenance (e.g., Signal Strength $\\rightarrow$ Collected by AP $\\rightarrow$ Processed by Connector $\\rightarrow$ Stored in TimescaleDB $\\rightarrow$ Ingested by AI Agent $\\rightarrow$ Rendered in Digital Twin). This ensures total auditability, trust, and debugging clarity.

## **5.7 Governance, Quality & Fault Tolerance**

To maintain enterprise-grade operational stability, the persistence and telemetry subsystems enforce rigorous operational policies:

* **Collector Resilience:** If a telemetry source or collector fails, the engine applies exponential backoff, marks the source as degraded, generates an administrative alert, and continues collecting from all surviving sources without interrupting the broader pipeline.  
* **Data Quality Monitoring:** The system monitors its own telemetry health, tracking collection latency, processing queues, dropped event counts, and WebSocket throughput.  
* **Retention Policies:** Configurable lifecycle rules govern data storage (e.g., 24-hour high-resolution cache in Redis; 90-day detailed metrics in TimescaleDB; indefinite hourly/daily summaries).  
* **Security Enforcement:** All telemetry transmission and database communication require strict TLS encryption, JWT service-to-service authentication, role-based authorization checks, and secure secret management.

