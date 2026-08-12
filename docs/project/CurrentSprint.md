# Current Sprint State

## Active Goals
- Vertical Slice 1 Implementation: **COMPLETE** — all modules implemented, tested, and migrated.
- Vertical Slice 2 Implementation: **COMPLETE** — telemetry ingestion/persistence/read APIs and telemetry health counters + `/ws/telemetry` fanout delivered through Step 8.
- Vertical Slice 3 Implementation: **COMPLETE** — runtime collector reliability, adapter-path advancement beyond stub, backpressure/SLO hardening, and VS3 planning-governance closure delivered through **VS3 Step 28**.
- Vertical Slice 4 Implementation: **COMPLETE** — runtime adapter increment, SLO alerting/runbook operationalization, deferred-topology governed design start, and executable Digital Twin scenario-validation handoff baseline delivered through **VS4 Step 4**.
- Vertical Slice 5 Implementation: **IN PROGRESS** — digital twin websocket session-security hardening advanced through **VS5 Step 2** (per-delta token-expiry + deny-list revalidation).

## Subsystem Progress — Vertical Slice 5

- [x] Step 1: Enforce `/ws/digital-twin` JWT expiry revalidation on every scene-delta push with `WS_UNAUTHORIZED` close semantics
- [x] Step 2: Add `/ws/digital-twin` per-delta deny-list (`jti`) revalidation path before push delivery
- [x] Step 3: Add digital twin websocket session-security observability branches/counters for close reasons
- [ ] Step 4: Expand simulation lifecycle event coverage beyond handoff/completion under governed simulation contract updates

## Subsystem Progress — Vertical Slice 4

- [x] Step 1: Vendor-facing runtime adapter increment baseline (SNMP/gRPC deterministic modes) behind runtime adapter factory controls
- [x] Step 2: Operationalize runtime adapter SLO thresholds into alerting signals and runbook-backed response metadata
- [x] Step 3: Begin governed implementation design for deferred topology analysis endpoints (`/neighbors`, `/impact`, `/reconcile`) under C6
- [x] Step 4: Start executable Digital Twin baseline integration with scenario validation pipeline handoff

## Subsystem Progress — Vertical Slice 3

- [x] Step 1: Collector startup retry/backoff baseline
- [x] Step 2: Single-poll runtime retry wrapper
- [x] Step 3: Runtime collector loop harness
- [x] Step 4: Runtime loop lifecycle wiring in app startup/shutdown
- [x] Step 5: Sustained runtime exhaustion visibility in telemetry health
- [x] Step 6: Sustained runtime-failure transition internal events
- [x] Step 7: Audit consumption for sustained-failure transitions
- [x] Step 8: Alert event flow routing for sustained-failure transitions
- [x] Step 9: `/ws/alerts` fanout for alert lifecycle events
- [x] Step 10: Alert websocket fanout observability counters/log branches
- [x] Step 11: Minimal production collector adapter stub wired to runtime poll path
- [x] Step 12: Runtime adapter health/backpressure observability counters
- [x] Step 13: Runtime adapter SLO snapshot visibility in telemetry health internals
- [x] Step 14: Runtime adapter backpressure anomaly warning thresholds in health logging
- [x] Step 15: Runtime adapter rolling anomaly streak visibility in health logging
- [x] Step 16: Runtime adapter anomaly streak persisted via Redis health counters
- [x] Step 17: Runtime adapter anomaly streak transition metadata observability
- [x] Step 18: Runtime adapter SLO health rollup severity visibility
- [x] Step 19: Runtime adapter SLO trend-window transition visibility
- [x] Step 20: Runtime adapter SLO trend-threshold trigger visibility
- [x] Step 21: Runtime adapter SLO trend-threshold cooldown and recovery visibility
- [x] Step 22: Runtime adapter trend-threshold cooldown-state observability summary
- [x] Step 23: Runtime adapter cooldown-transition event visibility and coverage
- [x] Step 24: Runtime adapter cooldown-correlation snapshot aggregation and coverage
- [x] Step 25: Runtime adapter mode factory and deterministic seeded production adapter path
- [x] Step 26: Runtime adapter dropped-sample backpressure hardening and SLO visibility
- [x] Step 27: C6 deferred topology planning/governance closure and non-routability hardening
- [x] Step 28: Digital Twin baseline integration/scenario planning closure and VS3 completion gate

## Subsystem Progress — Vertical Slice 2

- [x] Step 5: Telemetry ingestion scaffold + collector lifecycle wiring
- [x] Step 6: `telemetry_records` persistence baseline
- [x] Step 7: Telemetry read APIs (`history`, `device`, `health`)
- [x] Step 8: Telemetry operational health counters + persisted-event telemetry WS delta fanout

## Subsystem Progress — Vertical Slice 1

- [x] Architecture & Rules Setup
- [x] Documentation Structure (`docs/` map + phases 1-3)
- [x] Feature PRD Baseline (Authentication, Topology, Simulation, Telemetry, Organization)
- [x] ADR Baseline (ADR-001 to ADR-008)
- [x] Roadmap/Milestones aligned to vertical-slice-first delivery
- [x] Vertical Slice 1 Design Package — initial pass
- [x] Vertical Slice 1 Design Package — corrected (canonical docs re-read, errata resolved)
- [x] Vertical Slice 1 Design Closure — WebSocket channel ambiguity resolved
- [x] Vertical Slice 1 Design Closure — JWT claim baseline added to `Authentication.md` §8
- [x] Vertical Slice 1 Design Closure — `Organization.md` PRD created
- [x] Architecture Review Gate — APPROVE-WITH-CONDITIONS → all conditions resolved
- [x] Backend scaffolding (FastAPI, modular monolith, async SQLAlchemy, lazy engine)
- [x] Identity module: User, Role, Permission models + AuthService + JWT + rate-limiting
- [x] Organization module: Org, Workspace, OrgMember models + OrgService + WorkspaceService
- [x] Network module: Network, Device models + NetworkService + DeviceService (C5 enforced)
- [x] Event Bus: Redis Streams consumer loop + audit/topology/ws_push handlers
- [x] WebSocket: `/ws/topology` endpoint + connection manager
- [x] API routers: auth, orgs, networks, topology (scoped), audit — all envelope-compliant
- [x] Exception handlers: HTTPException → canonical envelope (all 4xx/5xx wrapped)
- [x] Database migration: `0001_initial_schema` applied to live PostgreSQL 16.14
- [x] Test suite: **68/68 passing** (39 unit + 29 integration, no warnings)
- [x] C5 verified: workspace_id validated via WorkspaceService API, no SQL cross-joins
- [x] C6 verified: deferred endpoints (/neighbors, /impact, /reconcile) absent from routing
- [x] Docker infrastructure: PostgreSQL 16, Neo4j 5.25, Redis 7 — all healthy

## Blocked / Deferred
- Digital Twin spatial references — deferred to M6
- Performance load testing — deferred to post-VS2
- Repo-wide Ruff debt outside VS2 Step 8 scope remains and is tracked for later cleanup.

## Next Sprint Candidates
- VS5 Step 4: expand simulation lifecycle event coverage beyond handoff/completion under governed contract updates.
