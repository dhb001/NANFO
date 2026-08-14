# Roadmap

## Milestone 1 - Foundation
- Documentation architecture baseline, guardrails, workflows, and ADR foundations.

## Milestone 2 - Core Backend
- API gateway scaffolding, module boundaries, and core execution plumbing.

## Milestone 3 - Authentication
- JWT/RBAC baseline with audit logging and protected routes.

## Milestone 4 - Topology Engine
- Network model, object lifecycle baseline, and initial topology views.

## Milestone 5 - Telemetry
- Ingestion pipeline, normalization, storage, and live update channels.

## Milestone 6 - Digital Twin
- Spatial model synchronization and initial living-world visualization loop.

## Milestone 7 - Simulation Engine
- Deterministic simulation lifecycle and baseline compare workflows.

## Milestone 8 - AIOS
- Explainable recommendation baseline with confidence and approval gates.

## Milestone 9 - Hypervisor
- Vendor-neutral intent execution, verification, and rollback baseline.

## Milestone 10 - Production Readiness
- Hardening, observability, security posture, and controlled release criteria.

## Vertical Slice Sequence (Execution History + Remaining)
- VS9 (complete): Hypervisor execution + rollback baseline via existing intent contracts.
- VS10 (complete): Deferred topology analysis endpoint set (`neighbors`, `impact`, `reconcile`) under C6 governance.
- VS11 (complete): Alerts lifecycle API completion (`list`, `ack`, `resolve`) with event/audit parity.
- VS12 (complete): Plugin registry lifecycle + sandbox safety baseline.
- VS13 (complete): Reporting async generation/status + artifact lifecycle baseline.
- VS14 (complete): M10 production-readiness closure gate (hardening, validation evidence, release criteria).
- VS15 (complete): Post-M10 synthetic load campaign baseline + frontend burst-resilience continuity evidence refresh.
- VS16 (in progress): Follow-on optimization planning and deferred external load-tooling expansion governance.
- VS17 (planned): External load-tooling execution baseline.
- VS18 (planned): Backend performance continuity hardening.
- VS19 (planned): Frontend performance continuity hardening.
- VS20 (planned): Optimization program closure gate.

Completion rule for all planned slices: backend and frontend acceptance criteria must both pass before a slice is marked complete.

Source of truth for ordered remaining work and closure criteria: `docs/project/CurrentSprint.md` (`Post-VS16 Plan` + `Remaining Work Master Checklist`).

## First Vertical Slice
- User logs in.
- User creates a network.
- User adds one device.
- Device is stored and shown in topology.
- Live updates are received for that device.
