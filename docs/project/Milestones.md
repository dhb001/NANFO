# Milestones

GitHub milestones mirror this list: <https://github.com/dhb001/NANFO/milestones>.
M1–M14 are closed; they were recorded on GitHub retrospectively on 2026-10-01 with their
completion dates, and their issues carry the `retrospective` label.

## M1
- Documentation baseline complete (rules, workflows, API standard, core PRDs, ADR baseline).

## M2
- Backend scaffolding and core data fabric operational in development.

## M3
- Authentication baseline complete (JWT/RBAC + audit logging).

## M4
- Topology engine baseline complete.

## M5
- Telemetry ingestion and live updates baseline complete.

## M6
- Digital twin synchronization baseline complete.

## M7
- Simulation lifecycle baseline complete.

## M8
- AIOS recommendation and explainability baseline complete.

- Execution slices aligned to M8 completion path:
  - VS8 (in progress): intent recommendation/explainability baseline closure.

## M9
- Hypervisor execution and rollback baseline complete.

- Planned implementation slice:
  - VS9: hypervisor execution + rollback baseline via intent lifecycle.

## M10
- Production readiness criteria met.

- Delivered implementation slices:
  - VS10: deferred topology analysis endpoints (`neighbors`, `impact`, `reconcile`).
  - VS11: alerts lifecycle API completion (`list`, `ack`, `resolve`).
  - VS12: plugins lifecycle + sandbox safety baseline.
  - VS13: reporting async generation/status baseline.
  - VS14: production-readiness closure gate and release evidence finalization.

## M11
- Post-M10 optimization continuity and governed external load-tooling expansion.

- Slice sequence:
  - VS15 (complete): synthetic load baseline + frontend burst-resilience continuity.
  - VS16 (complete): optimization planning/governance lock.
  - VS17 (complete): external load-tooling execution baseline.
  - VS18 (complete): backend performance continuity hardening.
  - VS19 (complete): frontend performance continuity hardening.
  - VS20 (complete): optimization program closure gate.

Authoritative ordered checklist and closure criteria live in `docs/project/CurrentSprint.md` (`Post-VS16 Plan`).

## M12 – Global Audit, 3D Twin and Strathmore Demo (complete 2026-09-03)
- Chapter 1–12 conformance audit, VS21 global audit with tenancy/RBAC hardening, the 3D
  digital twin as the primary operations surface, the Strathmore demo package, campus
  model assets and native device groups.

## M13 – Completion Program, ADR-009–ADR-020 (complete 2026-09-17)
- Completion plan Steps 1–15: foundation and security, measured SDN emulation, durable
  manual lab execution, measured learning, fail-closed safety/autonomy, matched routing
  and PPO training/refinement, scenario evaluator and operator workflows, module
  acceptance and the deployable, recoverable package.

## M14 – Measured Twin and Review Closure, ADR-021–ADR-027 (complete 2026-09-23)
- UI redesign, measured twin programme, operational twin runtime, measured qualification
  campaign, experimental lab closed loop, audit repair and repository review closure, plus
  the revised proposal and Chapter 4 diagrams.

## M15 – ADR-028 Full-Stack Review Remediation (current)
- Deliver every ADR-028 finding to `main` through a reviewed pull request
  ([#98](https://github.com/dhb001/NANFO/pull/98)) and take the owner decisions it needs.

## M16 – GitHub Governance and Remote CI (due 2026-10-29)
- Green remote CI, branch protection, Dependabot, history remediation, licence and the
  frozen dependency exceptions before they expire.

## M17 – Deployment and Successor Qualification
- Fresh qualification of the successor runtimes, host installation steps, the upgrade
  procedure for pre-ADR-028 deployments, escrow and operations capacity.

## M18 – Research Evidence and Evaluation
- Operational-domain deficit, intended-user study, repeated training, proactive timing
  and recovery evidence, and the physical RF survey.

## M19 – Code Quality and Technical Debt
- Bounded refactors and cleanups from `KnownIssues.md` and `TechnicalDebt.md`.
