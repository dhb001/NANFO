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

## Vertical Slice Sequence (Post-VS8)
- VS9 (planned): Hypervisor execution + rollback baseline via existing intent contracts.
- VS10 (planned): Deferred topology analysis endpoint set (`neighbors`, `impact`, `reconcile`) under C6 governance.
- VS11 (planned): Alerts lifecycle API completion (`list`, `ack`, `resolve`) with event/audit parity.
- VS12 (planned): Plugin registry lifecycle + sandbox safety baseline.
- VS13 (planned): Reporting async generation/status + artifact lifecycle baseline.
- VS14 (planned): M10 production-readiness closure gate (hardening, validation evidence, release criteria).

Completion rule for all planned slices: backend and frontend acceptance criteria must both pass before a slice is marked complete.

Source of truth for ordered remaining work and slice closure criteria: `docs/project/CurrentSprint.md` (`Post-VS8 Plan`).

## First Vertical Slice
- User logs in.
- User creates a network.
- User adds one device.
- Device is stored and shown in topology.
- Live updates are received for that device.
