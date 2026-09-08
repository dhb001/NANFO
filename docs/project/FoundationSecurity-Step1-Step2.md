# Trustworthy Foundation and Session Isolation

## Scope

User-authorized implementation of completion-plan Steps 1 and 2. Keep existing
REST routes, websocket channels, canonical envelopes, and module ownership.
No real network controller, evaluator, report renderer, or learning model is added.

## Contracts

- Configuration `EXECUTION_MODE` is `demo` (default), `emulation`, or `production`.
  Selecting a mode does not install an executor. Unsupported actions fail closed.
- REST response metadata adds `execution_mode`. The UI displays Unknown until
  authoritative metadata is received. Synthetic telemetry carries
  `tags.synthetic=true` and its execution mode; it is not live measurement.
- Intent execution without a controller returns existing `execution_failed`
  semantics, not successful verification or fictitious rollback.
- Simulation without an evaluator becomes `cancelled` with `risk_gate=blocked`.
  Start/resume persist that terminal state before publishing; no worker race can
  leave those new requests queued waiting for an unavailable evaluator.
  Unmeasured outputs and comparisons are null, not zero. Existing JSON output
  storage supports this without a migration. Historical baseline outputs lacking
  measurement provenance must not be represented as validated measurements.
- Reports without a renderer become `failed` with no artifact references.
  Previously fabricated baseline artifact references must not be advertised as
  downloadable generated files.
- Auth endpoints remain unchanged. Refresh now returns a full TokenPair,
  including the rotated refresh token. Clients atomically replace both tokens.
- Access and refresh JWTs include a session identifier and explicit token type.
  Redis (the existing session owner) tracks the absolute session expiry and current
  refresh token identity/digest. Rotation is atomic; replay revokes the family.
  Logout revokes the family. Legacy sessionless tokens require a fresh login.
- REST and websocket authorization rechecks active identity, current capabilities,
  and current membership. Optional token scope only narrows membership access.
- Organization mutations require write capability plus organization Admin role.
  Other tenant writes require org Admin or Operator in addition to global write
  capabilities. Cross-tenant intent network references fail before publication.
  Global diagnostic/registry surfaces require Admin and active membership; they
  are not represented as tenant-filtered resources. Audit reads require an
  explicit authorized organization.
- Websocket delivery requires an authenticated access session and per-delivery
  scope/capability validation. Missing scope is not a global alerts subscription.

## Ownership and Risks

Identity owns session lifecycle; Redis requires no relational migration.
Organization owns membership queries; other modules use its public service
contract rather than querying its tables. Simulation/intent/report own truth
classification. Frontend owns cache cleanup and permission-aware presentation,
never authoritative authorization. No new domain event names are introduced.

This intentionally removes previous demo-success behavior and invalidates old
sessions. Redis unavailability denies authentication rather than bypassing it.
Current role/membership checks add database work to authenticated reads and pushes.
True controller/evaluator/report implementations remain future steps.

## Acceptance

- Effective strict TypeScript, frontend lint/tests/build/browser gates.
- Backend lint plus regression and targeted session/tenant tests.
- Rotation/replay/logout and legacy-token rejection, cross-tenant and read-only
  denial, websocket token-type and membership-revocation coverage.
- No synthetic action claims actual execution, no nonexistent report artifact,
  and missing measurements render unavailable.
- Record actual command outcomes and remaining integration limitations; do not
  certify live Redis/database or controller behavior from mocks alone.

## Verified Results (2026-09-08)

- Backend: `poetry run ruff check app tests --no-cache` passed;
  `poetry run pytest tests -q --no-cov -p no:cacheprovider`: 1,112 passed.
- Frontend: effective `npm run typecheck`, `npm run lint`, and `npm run test`
  passed (39 files, 188 tests).
- Production build and unchanged bundle gates: `npm run perf:bundle` passed;
  total JavaScript gzip 401.67 KiB versus limit 410.16 KiB.
- Chromium `npm run test:e2e -- --output=/tmp/opencode/nanfo-foundation-final-e2e`:
  24 passed. These browser tests use mocked API contracts, including legacy
  successful-contract fixtures; they are not evidence of installed executors.
- Sessions are deliberately tab-local; new independent/opener-tab and expired
  logout flows are covered. Inconclusive websocket upgrade probes retry with
  cooldown instead of permanently disabling authentication recovery.

## Remaining Limits

Live Redis/PostgreSQL fault/concurrency certification and a live full-stack browser
campaign were not performed. Redis family atomicity is exercised with fakeredis;
repository/transport integration uses controlled fixtures. A transactional outbox
remains Step 6: commit-to-event crash windows can lose notifications, although new
unavailable simulation records remain durably terminal. Current physical control,
simulation evaluation, and report rendering are intentionally unavailable.
Three.js chunk and mixed static/dynamic session-import build warnings remain.
No relational migration is required. Existing sessions must log in again.
