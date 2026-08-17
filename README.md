# NANFO

NANFO (Network AI & Neural Fabric Orchestrator) is a modular-monolith platform for network operations that combines:

- Explainable intent validation and execution workflows
- Simulation-first change safety
- Realtime telemetry, topology, and alert streaming
- A Digital Twin operator UI
- Multi-tenant organization/workspace boundaries

This repository contains both backend and frontend code, plus architecture, API, and project-tracking documentation.

## Current Status

- Vertical Slices VS1 through VS20 are marked complete in `docs/project/CurrentSprint.md`.
- VS21 is in progress with two explicitly open high-risk residuals:
  - broad tenant/RBAC enforcement consistency across all route families
  - simulation terminal-event producer parity for `simulation.completed` and `simulation.cancelled`
- Recent full validation evidence (backend + frontend gates) is recorded in:
  - `docs/project/CurrentSprint.md`
  - `docs/project/DevelopmentJournal.md`

## What Is Implemented

High-level delivered capabilities:

- Authentication and JWT session flows (`/auth/login`, `/auth/logout`, `/auth/refresh`, `/auth/me`)
- Organization, workspace, and membership lifecycle
- Network and device lifecycle with topology synchronization
- Topology graph, node neighborhood, impact, and reconcile endpoints
- Telemetry history, device telemetry, health counters, and websocket deltas
- Alerts lifecycle (`list`, `ack`, `resolve`) with realtime updates
- Simulation lifecycle (`start`, `pause`, `branch`, `detail`, `compare`)
- Intent validation/execution/detail flows with explainability metadata
- Plugin registry lifecycle with safety checks (install, enable, disable)
- Reporting async generation and status retrieval
- Audit log query surface

Frontend operator routes are delivered under `/ops/*` (overview, tenancy, topology analysis, telemetry, reliability, plugins, reports, digital twin, simulation, intent, audit).

## Architecture Snapshot

### Backend

- Framework: FastAPI (`backend/app/main.py`)
- Style: modular monolith with module ownership boundaries
- Internal integration: Redis Streams event bus
- Realtime: WebSocket channels
- Layering: router -> service -> repository

### Frontend

- Framework: React + Vite + TypeScript
- Data/state: React Query + Zustand
- Realtime: managed websocket hooks with reconnect/unauthorized handling
- Route-level lazy loading for feature surfaces

### Data Stores

- PostgreSQL: primary relational module data
- Neo4j: topology graph queries and relationships
- Redis: event bus streams, rate limiting, token deny-list, websocket support

Planned/deferred architecture breadth (for later roadmap phases) remains documented in ADRs and chapter conformance artifacts.

## Repository Layout

- `backend/` - FastAPI app, domain modules, migrations, tests
- `frontend/` - React operator console, tests, perf gates
- `docs/` - architecture, API contracts, feature PRDs, sprint tracking, ADRs
- `scripts/` - local environment helper scripts (`dev-start.sh`, `dev-stop.sh`)

## API and Realtime Surfaces

REST API base: `http://127.0.0.1:8000/api/v1`

Core route groups:

- `/auth` - login/logout/refresh/me
- `/organizations` - org/workspace/member lifecycle
- `/networks` - network/device lifecycle
- `/topology` - graph, node view, neighbors, impact, reconcile
- `/telemetry` - history, device, health
- `/simulations` - start, pause, branch, detail, compare
- `/intents` - validate, execute, detail
- `/alerts` - list, ack, resolve
- `/plugins` - list, install, enable, disable
- `/reports` - generate, status
- `/audit/logs` - audit query

WebSocket channels:

- `/ws/topology`
- `/ws/telemetry`
- `/ws/alerts`
- `/ws/digital-twin`

OpenAPI docs:

- Swagger: `http://127.0.0.1:8000/api/docs`
- Redoc: `http://127.0.0.1:8000/api/redoc`

## Local Development Setup

### Prerequisites

Install these first:

- Docker (with compose support)
- Python 3.12+
- Poetry
- Node.js 20+ and npm

Arch Linux helper installer is available at `scripts/install-deps-arch.sh`.

### 1) Start Infrastructure

From repository root:

```bash
./scripts/dev-start.sh
```

This starts PostgreSQL, Neo4j, and Redis using `backend/docker-compose.yml`.

### 2) Configure and Install Backend

```bash
cp backend/.env.example backend/.env
cd backend
poetry install
poetry run alembic -c alembic/alembic.ini upgrade head
```

Notes:

- `backend/.env` is required by the backend app and Alembic.
- Keep secrets local; do not commit `.env`.

### 3) Create a Local Bootstrap User (Required)

There is currently no public registration endpoint, so you must create at least one user to log in.

Run this from `backend/`:

```bash
poetry run python - <<'PY'
import asyncio

from app.core.security import hash_password
from app.db.postgres import AsyncSessionLocal
from app.modules.identity.repository import UserRepository

EMAIL = "admin@example.com"
PASSWORD = "admin123"
DISPLAY_NAME = "Local Admin"
ROLE = "Admin"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        repo = UserRepository(db)
        user = await repo.get_by_email(EMAIL)
        created = False

        if user is None:
            user = await repo.create(
                email=EMAIL,
                hashed_password=hash_password(PASSWORD),
                display_name=DISPLAY_NAME,
            )
            created = True
        else:
            user.hashed_password = hash_password(PASSWORD)
            if not user.display_name:
                user.display_name = DISPLAY_NAME

        roles = await repo.get_roles_for_user(user)
        if ROLE not in roles:
            await repo.assign_role(user.user_id, ROLE)

        await db.commit()
        action = "Created" if created else "Updated"
        print(f"{action} bootstrap user: {EMAIL} (role={ROLE})")


asyncio.run(main())
PY
```

You can change `EMAIL`, `PASSWORD`, and `ROLE` in the snippet.

### 4) Run Backend API

From `backend/`:

```bash
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

### 5) Configure and Run Frontend

In a new terminal:

```bash
cp frontend/.env.example frontend/.env
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Open:

- `http://127.0.0.1:5173`

Login with the credentials you created in Step 3.

### 6) Stop Local Services

From repository root:

```bash
./scripts/dev-stop.sh
```

Remove containers and volumes (full reset):

```bash
./scripts/dev-stop.sh --purge
```

### Validation and Test Commands

Backend:

```bash
cd backend
poetry run pytest tests -q
poetry run ruff check app tests
```

Frontend:

```bash
cd frontend
npm run lint
npm run typecheck
npm run test
npm run test:e2e
npm run build
npm run perf:bundle
```

Project note: repo-wide backend Ruff baseline currently has known legacy debt tracked in sprint docs; scoped lint gates for touched files are used in active slices.

### Troubleshooting

- Docker daemon not running:
  - `./scripts/dev-start.sh` attempts to start Docker, but you may need to start it manually.
- Backend fails at startup connection checks:
  - verify PostgreSQL, Neo4j, Redis containers are healthy (`docker compose ps` in `backend/`).
- Login fails with 401:
  - ensure bootstrap user was created and password is correct.
- Frontend cannot reach backend:
  - verify `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` in `frontend/.env`.

## Is It Ready To Run Locally?

Yes, with one important caveat: you must bootstrap a user first because there is no self-service registration endpoint yet.

After infra start, migration, and user bootstrap, the app is runnable locally for development and feature validation.

## Is It an MVP?

Yes, this repository is at least MVP-level (and functionally beyond a thin MVP) for core NANFO workflows:

- auth, tenancy boundaries, network/device management, topology analysis
- telemetry + alerts + digital twin realtime flows
- simulation, intent execution, plugins, and reporting baselines

However, it should be considered an active pre-GA MVP/beta rather than final production-finished state, because VS21 still tracks open high-risk hardening items.

## Canonical Documentation Map

Use these as source-of-truth references:

- Product/sprint state: `docs/project/CurrentSprint.md`
- Delivery journal: `docs/project/DevelopmentJournal.md`
- Architecture: `docs/architecture/`
- API standards/contracts: `docs/api/`
- Feature PRDs: `docs/features/`
- ADRs: `docs/adr/`
