# NANFO Documentation Map

## Structure
- `architecture/`: high-level architecture narratives and diagrams.
- `adr/`: architecture decision records.
- `api/`: API standards and contracts.
- `features/`: feature PRDs.
- `project/`: sprint and project journals.
- `standards/`: engineering and execution standards.
- `chapters/`: chapter-wise thesis/product narrative mirror.

## Golden Rule
- Every recurring question must have one canonical home.
- Cross-reference canonical files instead of restating normative content.

## Canonical Ownership
- Why NANFO exists: `/.agents/rules/constitution.md`
- What AI must never do: `/.agents/rules/architecture-guardrails.md`
- How AI should reason: `/.agents/rules/engineering-behaviour.md`
- API response envelope and baseline API policy: `/docs/api/API_STANDARD.md`
- Current active delivery state: `/docs/project/CurrentSprint.md`
- Chronological delivery history: `/docs/project/DevelopmentJournal.md`

## Phase Priority Tracking
### Phase 1 (Foundation)
- [x] `api/API_STANDARD.md`
- [x] `project/CurrentSprint.md`
- [x] `project/DevelopmentJournal.md`

### Phase 2 (Feature PRDs)
- [x] `features/Authentication.md`
- [x] `features/Topology.md`
- [x] `features/Simulation.md`
- [x] `features/Telemetry.md`
- [x] `features/Alerts.md`
- [x] `features/IntentEngine.md`
- [x] `features/Reporting.md`
- [x] `features/Plugins.md`

### Phase 3 (ADRs)
- [x] `adr/ADR-001-modular-monolith-first.md`
- [x] `adr/ADR-002-polyglot-persistence-uedf.md`
- [x] `adr/ADR-003-design-before-implementation-workflow.md`
- [x] `adr/ADR-004-domain-driven-design.md`
- [x] `adr/ADR-005-backend-technology-stack.md`
- [x] `adr/ADR-006-event-bus-internal-communication.md`
- [x] `adr/ADR-007-aios-and-digital-twin-architecture.md`
- [x] `adr/ADR-008-simulation-before-deployment.md`

### Phase 4
- Start implementation only after design handoff artifacts are present for each non-trivial feature.

## API Documents
- `api/API_STANDARD.md`
- `api/REST.md`
- `api/WebSocket.md`
- `api/EventAPI.md`
- `api/Authentication.md`
- `api/OpenAPI.md`

## Architecture Documents
- `architecture/Vision.md`
- `architecture/Architecture.md`
- `architecture/AIOS.md`
- `architecture/Hypervisor.md`
- `architecture/Physics.md`
- `architecture/DigitalTwin.md`
- `architecture/EventBus.md`
- `architecture/Networking.md`
- `architecture/Storage.md`
- `architecture/Deployment.md`

## Project State Documents
- `project/CurrentSprint.md`
- `project/DevelopmentJournal.md`
- `project/DecisionLog.md`
- `project/KnownIssues.md`
- `project/TechnicalDebt.md`
- `project/Roadmap.md`
- `project/Milestones.md`

## Standards Documents
- `standards/AgentExecutionStandard.md`
- `standards/DocumentationStandard.md`
- `standards/SourceOfTruthMap.md`
- `standards/UIDesignStandard.md`
- `standards/AccessibilityStandard.md`
- `standards/LoggingStandard.md`
- `standards/MonitoringStandard.md`
- `standards/ErrorHandlingStandard.md`
