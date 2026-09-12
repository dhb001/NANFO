# Frontend Session Behavior

## ADR018 Operator Surfaces

Autonomy now has keyboard-accessible panels for status/decisions, frozen model
diagnostics, versioned configuration and timed overrides. Emergency STOP stays
available outside the panels. Only the selected operator panel fetches its data;
network/session changes discard drafts, selections and late mutation notices.

- Model registry/history selectors use the public operator-allowlisted IDs from
  `model_diagnostic_schemas.py`, never filesystem paths. Inference is explicit,
  historical and non-actuating. Action probabilities are not safety confidence.
  Records expose model/input/history hashes, provenance, value and actual timing.
  Missing live history stays unavailable; no training source or weight is changed.
  Backend isolation work (including Landlock) does not imply live inference or
  safety authorization. Isolation status is not invented from registry metadata.
- Configuration consumes `ConfigurationResponse` and `SetConfigurationRequest`.
  Effective operational settings are separate from requested signed reward weights
  (-100 to100), retraining-required state and unavailable model-owned effective
  training. Only documented operational fields are editable. Unsupported fields,
  including false-valued controls, fail validation. Conflicts retain the original
  draft revision and require explicit refresh/reload, never automatic reapproval.
- Overrides inspect an explicit network-scoped intent/execution UUID pair before
  enrollment. Eligibility uses the validated exact UUID in execution provenance's
  `approved_by_user_id`, not the intent creator's `requested_by_user_id`.
  The server still checks fresh journal ownership, exact command and
  readback. Duration/reason/return mode and expected revision are explicit. Browser
  countdowns never trigger restoration or mode changes. Cancel requests restoration;
  pending/uncertain, restored, blocked return and returned states stay distinct.
  STOP dominates return, including pending requests. Return uses a fresh explicit
  reason/revision and leaves all provider/current-approval checks to the server.
- Twin's optional measured-probe panel explicitly reads `/telemetry/paths` and
  displays actual ordered canonical hops, ports, timestamps, packet/run/window IDs,
  evidence hash, freshness, partial/ambiguous status and observed path variation.
  This evidence covers selected probes only, not all flows. Approved configuration
  comparison is separate and currently unavailable through the measured contract.
  The current schema supplies canonical node IDs but **no canonical link IDs**.
  The strict mapping adapter and renderer therefore keep the ordered-list fallback,
  with no guessed arrow highlight. Fresh fully mapped segments are the only allowed
  renderer input; names/proximity/planned paths are never substituted.
  Observed packet/hop evidence remains useful in the list, but actual scene-arrow
  integration is not complete without canonical link IDs. These surfaces are not
  a claim that every Step12 integration or live verification gate is complete.

Frontend-only verification (2026-09-10): lint and strict typecheck passed;
465 unit/component tests passed;38 mocked Chromium scenarios passed without retries
on development and separately on the minified production build, including the new
390px keyboard scenario across all panels. Build/performance passed all unchanged
limits:408.48KiB total JS gzip against410.16KiB. Related operator panels share one
lazy chunk to avoid per-panel compression overhead; existing charts are preserved.
Existing Three.js chunk-size and auth-session dynamic-import warnings remain.
Approver regressions cover requester A/executor B: current B can request enrollment,
current A cannot, and missing/malformed approver UUIDs never fall back to the creator.
Follow-up build and browser output is under `/tmp/opencode/approver-review-*`, with
browser traces, screenshots and video disabled; no generated artifacts were added
to the repository.

### Separate Backend-Live Gate

`npx playwright test --config playwright.live.config.ts` is a separate read-only
browser integration suite with no route mocks, lab startup, migration or service
reset. Configure `E2E_LIVE_FRONTEND_URL`, `E2E_LIVE_EMAIL`, `E2E_LIVE_PASSWORD`,
`E2E_LIVE_ORGANIZATION_ID`, `E2E_LIVE_WORKSPACE_ID`, and `E2E_LIVE_NETWORK_ID` for a
provisioned deployment using the approved backend routes. Credentials are not
committed and traces/screenshots/video are disabled in this suite.

This gate was invoked and **skipped** because live deployment credentials/scope
were not configured. Live model inference and override worker/controller lifecycle
verification remain integration work, not claims established by mocked browser
tests. This frontend workstream changed no backend, AI, emulation or training files.
Cross-workstream project tracking remains owned by the coordinating workstream;
this section records the frontend handoff without editing shared project documents.

Authentication tokens and workspace selection are persisted in `sessionStorage`,
not `localStorage`. Sessions intentionally belong to one browser tab. Reloading
that tab restores its session after `/auth/me` verification; other tabs must log
in independently. Legacy shared `nanfo.auth.*` and workspace keys are discarded,
not migrated, so an old refresh token cannot be replayed by multiple tabs.
New windows with an opener discard inherited credentials. Application links that
open new tabs must use `noopener`.

Refresh requests are single-flight within the tab and replace both tokens in one
storage write. Logout waits for an in-flight rotation; if the access token has
expired, it refreshes once and retries backend logout before local cleanup.
Network failures clear the local session but display that revocation is unconfirmed.

Before-open WebSocket close code `1006` is ambiguous. The client probes the existing
`/auth/me` endpoint and rotates only on a confirmed `401`. Upgrade recovery is
limited to one conclusive attempt until a connection opens successfully, including
across the resulting token rotation. Inconclusive network/server failures permit
another auth probe after an exponential cooldown (5 seconds, capped at 60 seconds).
Transport reconnects continue with backoff; an outage alone never rotates tokens.

Global plugin registry and telemetry health UI require the Admin role in addition
to the corresponding permission. Active membership is enforced by the backend;
the frontend does not infer membership from roles or local workspace selection.
Tenant telemetry history remains accessible with `read:telemetry`.

## Governed Autonomy (ADR-012)

`/ops/autonomy` is lazy-loaded and available through the shell, command palette,
and `G N` shortcut with `read:telemetry`. It requires selected organization,
workspace and network context. Changes and immediate emergency stop require both
`write:config` and `execute:rollback`; current writable membership remains a server
check, not a frontend role inference.

The UI consumes `backend/app/modules/autonomy/schemas.py` through the approved
GET/PUT `/api/v1/autonomy` and POST `/api/v1/autonomy/stop` canonical envelopes.
It polls bounded durable history every 10 seconds while mounted and foregrounded,
backs off on failures, stops interval polling on 401/403, and cancels reads when
scope changes. Readiness expires after 30 seconds without a successful status read.
No mode or latch is updated optimistically. Stop remains available during a failed
status read or pending mode change; only a matching server response with
`emergency_stopped=true` confirms the latch. Cancellation can still be unresolved.
Reload reads the persisted server latch, never a browser-owned replacement.

Every mode PUT requires `expected_revision`, taken from the last confirmed status
at explicit submission, including revision zero for an unconfigured network.
Missing, negative, fractional or unsafe JavaScript integer revisions are rejected.
HTTP 409 retains confirmed mode/latch, refreshes status, and never automatically
retries or renews approval. Stop still sends only `{network_id}`. Confirmed server
mutation responses cancel older reads; lower-revision responses cannot overwrite
newer cached controls. A new explicit mode submission uses the refreshed revision.

Monitor is the non-actuating draft default. Recommendation never dispatches.
Autonomous selection is gated by reported readiness/providers; the backend remains
authoritative and rejected changes retain the confirmed mode. No checkpoint is
auto-selected, and no local training artifacts are read. Training completion or a
failed quality gate never becomes model approval. Online learning and production
dispatch remain false. A conditional one-step certificate is not a global or
continuous-time stability guarantee, switch verification, or measured benefit.

Optional structured `safety.certificate` displays actual backend model/provider,
calibration/policy, action/routes, input SHA-256, observation/horizon/expiry,
drift in bytes squared and queue bounds in bytes. Optional `safety.binding` exposes
the returned observation/proposal/calibration/action hashes and evaluation time.
No certificate is derived from free-text evidence and absent fields are not filled
with invented values. Expiry labels use the browser clock only; the server must
recheck. Reported hashes are not signatures or independently verified provenance.

The inspected response exposes execution identity, revision, decision status and
verification, but does not expose worker lease or pipeline-stage fields. The UI
does not invent these or send ownership/lease controls. A future backend contract
must explicitly expose them before they can be rendered as read-only diagnostics.

Validation for the revision/certificate follow-up: lint, strict typecheck, 313
unit/component tests (68 autonomy tests), production build, and all unchanged
bundle bounds passed. All 31 Chromium E2E tests passed against the Terser-minified
production preview with retries disabled; the four focused autonomy E2E tests
also passed on the development server. Coverage includes 390px layout,
gate denial, stop pending/acknowledged/error/scope mismatch, persisted reload,
read-only permissions, durable-history polling, pending old PUT -> acknowledged
stop -> old PUT 409 -> explicit new-revision mode change, stale response rejection,
and optional structured certificate display/validation. Browser APIs are mocked;
these are not live database/worker/controller or safety-calibration certification.

The autonomy-only validation above used Terser safe defaults, with no unsafe
compression or budget changes: its total JS gzip was 404.18 KiB against the
existing 410.16 KiB cap. The combined ADR-017 validation below supersedes that size.
Existing large Three.js chunk and mixed auth-session import warnings remain.
`npm audit --omit=dev` reports two moderate React Router dependency advisories;
dependency security upgrades remain a separate scope. No backend, AI-engine,
emulation, campaign artifacts or shared project-tracking files were edited here.

## Combined ADR-017 Frontend Gates

Final integration preserves scenario input/work limits, bounded telemetry queries,
realtime reconciliation, Twin persistence safeguards and all original performance
thresholds. Panels have accessible names, and telemetry E2E locators target the
history region's buttons rather than hidden chart options or duplicated text.
Chart content, table fallback and device drilldown remain available.

The command palette, toasts and async states use CSS animations instead of the
Framer Motion runtime. Entry/exit timing, palette blur/translation/scale and toast
translation/scale are retained; reduced-motion media preferences disable motion.
Exiting content is temporarily retained but hidden from assistive technology and
disabled/inert. Reopening cancels pending removal, timers clean up on unmount,
and toast width remains bounded on mobile. No animation dependency was added.
Terser uses two safe compression passes, without unsafe flags or threshold changes.

Combined validation on 2026-09-10:
- Full ESLint and TypeScript checks passed.
- All 369 unit/component tests in 60 files passed.
- All 37 Chromium E2E tests passed on both the development server and minified
  production preview, with retries disabled and isolated ports.
- Production build and every original bundle-continuity bound passed: total JS
  gzip 395.25 KiB / 410.16 KiB; largest chunk 221.74 / 253.91 KiB; largest non-Three
  chunk 51.67 / 58.59 KiB; Twin entry 0.64 / 6.84 KiB.
- Frontend diff whitespace checks passed. Existing Three.js chunk-size and mixed
  auth-session import warnings remain; dependency advisories are not resolved by
  this work.

The path panel accepts `execution_provenance.approved_plan` as the persisted
command's seven-field object: `operation`, `source_host`, `destination_host`,
`paths`, `weights`, `rate_mbps`, `dscp`. It does not require or invent a `source`
field. The parent backend projection now checks the persisted plan hash and returns
a copy or null; existing plan/readback hashes and successful nonsuperseded readback
govern the limited configuration claim.
Fixtures exercise this exact shape. Packet traversal, live inference evidence and
physical safety authorization are not inferred. Browser tests mock API contracts;
they do not validate actual physics, live backend workers or packet paths.

### Review Follow-Up

Subscribed/backpressure reconciliation reads existing simulation/intent detail for
up to 20 known, current-scope UUIDs, even without active detail queries. Reads use
two concurrent workers, a ten-second per-read timeout, cancellation on auth/scope
changes, epoch/object-version guards, server timestamps and simulation revisions.
Successful REST snapshots replace stale fields; 401/403/404 or mismatched identity/
scope retire the old object, while transport failures remain explicitly stale.
The UI reports known/requested/unavailable/omitted counts; this is never full history.

Raw `flow_*` counters retain snapshot timestamp, table, cookie, priority, ordinal
and fetched row identity. Repeated cookie/index values are not durable flow IDs;
duplicate rows remain distinct, realtime retention includes snapshot/event identity,
and no line connects snapshots. The UI labels these as snapshot-local counters.

Intent execution accepts an optional explicitly entered simulation UUID. Editing
it clears approval; dispatch locks it for identical retries, and cancellation
always omits it. Selecting an ID does not synthesize action/network hashes or create
the prepared artifact required by the exact-state backend evidence check. Start and
branch handoffs display the actual configured-model source and false physical-safety
authorization. Identical-checkpoint E2E branches assert zero deltas; the separate
changed-input fixture submits different capacity and distinct outputs, not physics proof.

Review browser outputs are kept in `/tmp/opencode/scenario-e2e-results` and
`/tmp/opencode/frontend-production-e2e-results`. Only this workstream's eight older
artifact directories were moved out of `frontend/test-results`, and its tracked
last-run marker was restored to its prior content. No other source was reverted.
