---
match: "backend/**"
---
# Backend Engineering & Service Layer Architecture

## 1. Service Layer Rules
* **Layer Separation:** Enforce strict separation: Controller (FastAPI Router) -> Service Layer (Business Logic) -> Repository Layer (SQLAlchemy ORM).
* **Database Reference:** Refer to `database.md` for all storage engines, polyglot persistence routing, and schema rules.
* **Asynchronous Offloading:** Heavy background workloads (OSM parsing, report generation, deep AI inference) must be offloaded to Celery worker pools.

## 2. API Schema & Event Contracts
* **API Specifications:** Read `docs/api/API_STANDARD.md` for all REST envelope formats, HTTP methods, and WebSocket delta constraints.
* **Distributed Locks:** Apply Redis distributed locks with idempotency tokens to all configuration push actions.