# Feature PRD: Plugins

## Purpose
Support safe extension of NANFO through sandboxed connectors, collectors, and visualization modules.

## Business Goal
Enable vendor-neutral extensibility without core code changes.

## Functional Requirements
- Install/enable/disable/uninstall plugin lifecycle.
- Validate signatures and dependency compatibility.
- Enforce sandbox boundaries.

## Non-Functional Requirements
- Fault isolation for plugin failures.
- Deterministic startup registration behavior.

## API
- `GET /api/v1/plugins`
- `POST /api/v1/plugins/install`
- `POST /api/v1/plugins/{id}/enable`
- `POST /api/v1/plugins/{id}/disable`

## Database
- Plugin registry and lifecycle status tracking.

## Events
- `plugin.installed`, `plugin.enabled`, `plugin.disabled`, `plugin.failed`

## Risks
- Runtime instability from unsafe plugin behavior.

## Acceptance Criteria
- [ ] Invalid signatures are rejected.
- [ ] Plugin failures do not crash core runtime.

ADR-028: the registry is metadata-only. Signer/signature fields are *declarations*: they
pass prefix, length and allowlist admission but are never cryptographically verified, and
responses report `declared_unverified`. "Invalid signature" therefore means an
inadmissible declaration; the historical code `PLUGIN_SIGNATURE_INVALID` is kept.
Lifecycle transitions commit before publication with deterministic event IDs, and
deferred publications are swept every 30 s. `plugin.failed` events for rejected installs
are rate-limited (`PLUGIN_FAILED_EVENT_WINDOW_SECONDS`,
`PLUGIN_FAILED_EVENT_MAX_PER_ACTOR`). Detail: `backend/app/modules/plugin/README.md`.

## Tests
- Unit: manifest validation.
- Integration: lifecycle transitions and isolation checks.
