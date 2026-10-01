# NANFO

NANFO (Network AI & Neural Fabric Orchestrator) is a modular-monolith platform for network operations that combines:

- Explainable intent validation and execution workflows
- Simulation-first change safety
- Realtime telemetry, topology, and alert streaming
- A Digital Twin operator UI
- Multi-tenant organization/workspace boundaries

This repository contains both backend and frontend code, plus architecture, API, and project-tracking documentation.

## Start On Localhost (API/UI Development)

For the complete supervised runtime, start with
[`deploy/README.md` — Fresh Install](deploy/README.md#fresh-install) and the
[0029 acceptance handoff (pre-ADR-028; schema head is now 0030)](docs/project/ReviewClosure-Deployment.md).
That path provisions the API, frontend gateway, **six core workers** (simulation,
report, alert, execution, autonomy and network outbox), the supervised stream-retention,
telemetry-retention and asset-GC services (ADR-028), private stores and persistent
storage. Optional fleet operations have separate configuration.

The commands below start development stores and API/UI processes. Async workflows
also require their workers. Model uploads need a private persistent
`NETWORK_ASSET_ROOT`; reports need `REPORTS_STORAGE_PATH`, shared with the report
worker. Provision service-UID-owned0700 directories outside web roots; see
[Assets](docs/project/CompletionProgram/Assets.md) and
[report setup](backend/app/modules/report/README.md). Prefer the supervised path
for end-to-end use.

From repository root:

```bash
./scripts/dev-start.sh
cd backend
poetry install
poetry run alembic -c alembic/alembic.ini upgrade head
# Create the local bootstrap user below before logging in.
poetry run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`dev-start.sh` generates `backend/.env` with four independent secrets and mode0600
only when absent, preserves existing files, and waits for healthy loopback-bound
stores. **Keep that generated file; do not overwrite it with `.env.example`.**
Existing initialized volumes require their matching credentials. A copied sample
has empty secrets and must be populated privately before startup.

In a second terminal, from the repository root:

```bash
cd frontend
test -e .env || cp .env.example .env
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open:

- Frontend: `http://127.0.0.1:5173`
- Backend API docs: `http://127.0.0.1:8000/api/docs`

Note: You must create a bootstrap user first (see "Create a Local Bootstrap User" in this README) because there is no public registration endpoint.

## Current Status — 25 September 2026 (ADR-028)

Authority: [ADR-028](docs/adr/ADR-028-full-stack-review-remediation.md) (outcome §6,
decisions §7, owner actions §8, final verification) and the
[remaining checklist](docs/project/CurrentSprint.md). Contract changes, including four
BREAKING ones (C3, C4, C5, C10), are listed in
[ADR028-ContractChanges](docs/api/ADR028-ContractChanges.md).

- Every finding of the 23 September full-stack review is remediated; schema head **0030**.
  The change is committed per ADR-028 workstream on top of `e55a4f5` and reaches `main`
  through the ADR-028 pull request ([#47](https://github.com/dhb001/NANFO/issues/47)).
- Final verification: backend **5,335 passed/0 failed** (coverage **85.64 %**, floor 84),
  private lane **94**, PostgreSQL 17/Redis lanes **323 + 29** with a clean migration round
  trip, portable lane **750** cases with zero skips, ai-engine **520**, frontend
  **909** unit and **71** e2e tests, evidence scan and gitleaks **0** findings.
- Not proven locally: image builds/trivy, the production-browser lane and any live lab
  qualification. The successor lab image and receiver need fresh qualification before any
  result claim ([KnownIssues](docs/project/KnownIssues.md)).

## Previous Status — 21 September 2026 (ADR027)

Current authority: [seven-workstream review matrix](docs/project/ReviewClosure-Completion.md)
and [remaining checklist](docs/project/CurrentSprint.md). Source is the ADR027
integration worktree over `3f9f1f1`; accepted releases have separately pinned source
manifests/images, not a new committed release identity.

- Schema **0029**, six core workers. Canonical spatial editing/history, persisted
  registration/protected assets, SNMPv3/fleet collection, configured RF overlays,
  distributed realtime and non-actuating AI review/memory are delivered within the
  [completion-program scope](docs/project/CompletionProgram/README.md).
- Latest parent-observed backend **3,949 passed/317 skipped**; frontend **615 tests/
  98 files**, lint/types/build/perf passed (**394.28/410.16 KiB**). Final fixture
  browser suite **70/70, no retries**; actual production-build full-stack **5/5**.
- Latest core0029 **c8rorfzd accepted28 passed/0 failed/5 blocked**, including
  encrypted11-volume backup/fresh restore;253 deployment tests passed. Backend
  image `a2bf67af…`, source aggregate `f7105617…`; exact identities below. Subsequent
  source-code changes are only experimental seed-scanner tooling/test (`9e46d086…`
  verifier), not core serving behavior. The current tree is not byte-identical to
  the accepted image. Distributed/lab/model/measured-telemetry scopes remain blocked.
  [Exact evidence](docs/project/ReviewClosure-Deployment.md),
  [durable credential-free bundle](docs/project/ReviewClosureEvidence/README.md).
  New private backup/key/result preservation and public refresh/retention receipts
  are complete locally; off-host escrow remains open.
- Clean upgraded PostgreSQL **254 passed/12 skipped**, followed by the exact
  real-Redis subset **12 passed/0 skipped**: all **266 selected** cases covered.
  Development `fakeredis` Lua/lupa dependencies and clean-CI EVAL checks are fixed;
  repaired nginx header/proxy gate **24 passed/0 skipped**. Remote CI remains unverified.
- Final portable gate: **441 JUnit cases, zero skips,11 explicit deselections**.
  Original AI environment **463 passed**, reaffirmed; no new training implied.
- Asset restore/metadata pagination, request identity, setup/proxy and route recovery
  repairs are delivered. Opt-in archive-before-delete stream retention passed
  **27 real-Redis cases**; operator scheduling/capacity obligations remain.
- **71 receiver credentials** were preserved privately and removed from the active
  tree; historical exposure remains unresolved. npm audit **0**; exact Python/frozen
  runtime exceptions expire **2026-10-21** and are not fixes. Remote CI is not claimed.
- ADR024 qualified the rebuiltv4 bounded benchmark and fresh recommendations with
  unchanged tensors. Actual **017 remains FAILED**:4/4 smokes,67/68 matrix outcomes
  completed,1 invalid measurement (`path1-1564-qualified`,
  `protected_regular_owner_file_required`); all20 fault outcomes completed. Its
  frozen source/original model are unchanged. Active emulation's reproduced atomic-
  replacement race is repaired with protected bounded reopen; frozen018 offline
  gates passed115 backend/3 historical skips,34 receiver and2 STOP checks.
- Independent018 review **accepted the protected-read repair** and reconfirmed017
  failure. It found `reserved_seed_count:1342` falsely treated as a reservation;
  active extractor correction passed60 tests. **Fresh campaign blocked:**996/1000
  genuine/preregistered train-operational values reserved,4 available/36 required,
  deficit32. No018 plan/live acceptance, seed reuse or split change.
  [Experimental status](docs/project/CompletionProgram/ExperimentalAcceptance.md).
  Physical RF, intended-user study, independent repeated training and calibrated
  autonomy remain evidence obligations; the experiment is not complete.

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
- Metadata-only plugin registry lifecycle (install, enable, disable, uninstall)
- Worker-generated CSV/PDF reports, history and authenticated verified downloads
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
- Redis: event bus streams, rate limiting, refresh-session store, websocket support

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

- Docker with Compose supporting `up --wait --wait-timeout`
- Python 3.12+
- Poetry
- Node.js 22.12+ and npm (`frontend/.nvmrc` pins 22.22.0)

Arch Linux helper installer is available at `scripts/install-deps-arch.sh`.

### 1) Start Infrastructure

From repository root:

```bash
./scripts/dev-start.sh
```

This starts PostgreSQL, Neo4j, and Redis using `backend/docker-compose.yml`, binds
published store ports to loopback and waits for health (default180s;
`NANFO_DEV_WAIT_SECONDS` accepts1–3600). It generates a private `backend/.env` only
when absent. Existing volumes require the original matching credentials. Setup
success means healthy stores; API and workers are separate processes.

### 2) Configure and Install Backend

```bash
cd backend
poetry install
poetry run alembic -c alembic/alembic.ini upgrade head
```

Notes:

- Keep the generated `backend/.env`; it is used by the app and Alembic. Never copy
  the empty-secret sample over it. Privately correct an existing invalid env before
  rerunning setup; the helper does not replace it.
- `upgrade head` is for the owned development database and currently reaches 0030.
  Supervised0027/0028 installations need the separately reviewed upgrade procedure
  in [the deployment handoff](docs/project/ReviewClosure-Deployment.md); cold restore
  uses identical images/schema and does not migrate.
- Keep secrets local; do not commit `.env`.

### 3) Create a Local Bootstrap User (Required)

There is currently no public registration endpoint, so you must create at least one user to log in.

Run this from `backend/`:

```bash
poetry run python - <<'PY'
import asyncio
from getpass import getpass

from app.core.security import hash_password
from app.db.postgres import AsyncSessionLocal
from app.modules.identity.repository import UserRepository

EMAIL = "admin@example.com"
PASSWORD = getpass("New local bootstrap password: ")
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

Set `EMAIL` and `ROLE` for the local account; enter its password at the private
prompt. For an existing email this deliberately resets its password and adds the
selected role.

### 4) Run Backend API

From `backend/`:

```bash
poetry run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

### 5) Configure and Run Frontend

In a new terminal:

```bash
cd frontend
test -e .env || cp .env.example .env
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
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

The exact commands CI runs are in
[CONTRIBUTING.md → Test commands](CONTRIBUTING.md#test-commands-identical-to-ci), for each
area: backend, frontend, AI engine, the portable deployment/emulation/script lane,
dependency audits, packaging and the production-browser lane. CONTRIBUTING.md also covers
the private-artifact lanes and the 13 required checks. A quick local subset:

```bash
cd backend && make check     # ruff + unit/integration tests, excluding private artifacts
cd frontend && npm run lint && npm run typecheck && npm test
```

Report security problems privately as described in [SECURITY.md](SECURITY.md); do not
open a public issue.

The earlier repository-wide Ruff debt label is obsolete; the review baseline passed
full backend lint. Current run counts and exact execution scopes are recorded in
[ReviewClosure-Completion](docs/project/ReviewClosure-Completion.md). Real production
browser acceptance has a separate [full-stack runner](docs/project/ReviewClosure-Fullstack.md).

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

After infra start, migration, and user bootstrap, the API/UI are runnable for
development. Use the supervised package for all six workers and private persistent
storage needed by end-to-end asynchronous workflows.

## Is It an MVP?

Yes, this repository is at least MVP-level (and functionally beyond a thin MVP) for core NANFO workflows:

- auth, tenancy boundaries, network/device management, topology analysis
- telemetry + alerts + digital twin realtime flows
- simulation, intent execution, plugins, and reporting baselines

It remains an active pre-GA platform. Core recovery has bounded isolated acceptance;
physical calibration, distributed scale and qualified autonomous control still have
the explicit implementation and acceptance gaps in the completion-program register.

## Canonical Documentation Map

Use these as source-of-truth references:

- Product/sprint state: `docs/project/CurrentSprint.md`
- Current review/acceptance matrix: `docs/project/ReviewClosure-Completion.md`
- Delivery journal: `docs/project/DevelopmentJournal.md`
- Architecture: `docs/architecture/`
- API standards/contracts: `docs/api/`
- Feature PRDs: `docs/features/`
- ADRs: `docs/adr/`
