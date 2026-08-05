---
match: "backend/**"
---
# Unified Enterprise Data Fabric (UEDF) & Polyglot Persistence

## 1. Storage Domain Responsibilities
* **PostgreSQL (Relational):** Transactional data, device inventories, RBAC, workflows, and immutable audit logs.
* **TimescaleDB (Time-Series):** High-frequency metrics (bandwidth, CPU, latency, signal strength) using automated time-based partitioning.
* **Neo4j (Knowledge Graph):** Semantic topology, multi-hop physical/logical dependencies, and spatial containment graphs.
* **Redis (In-Memory):** Active sessions, rate limiting, WebSocket Pub/Sub channels, and distributed task lock management.
* **MinIO / S3 (Object Storage):** Binary assets including 3D glTF/GLB models, firmware binaries, floor plans, and PDF reports.

## 2. Database Execution Rules
* **Soft Deletes:** Maintain audit traceability by utilizing soft-deletion patterns for operational entities.
* **Schema Migrations:** All relational changes must execute via versioned Alembic migrations.
* **Data Isolation:** Every backend module strictly owns its respective tables. Direct cross-module SQL joins are prohibited.