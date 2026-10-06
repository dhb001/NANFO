# ADR-028: Full-stack review remediation program

- Date: 2026-09-23 (accepted); implemented 2026-09-23/24.
- Status: **Implemented, pending owner verification actions.** The repository owner
  explicitly directed that every finding of the 23 September 2026 full-stack review be
  fixed in one coordinated change. Outcome §6, integrator decisions §7, owner actions §8.
- Base: commit `75b514f` (clean tree). Supersedes nothing; extends ADR-027 contracts.
  Part of the change is in the owner's commit `e55a4f5`; the rest is uncommitted (§8).
- Scope: backend, frontend, persistence, deployment/CI, AI engine and emulation findings.

## 1. Governing constraints

1. Historical evidence bytes, frozen model/runtime identities, recorded campaign results
   and accepted release receipts are **not rewritten**. Changes that alter a frozen
   runtime (lab image, frozen v4 client, qualified checkpoint) are delivered as
   *successor* artifacts that require fresh qualification; they never relabel old results.
2. Module ownership is preserved. No module queries another module's tables. Owner
   modules expose read-only query functions where another module needs an answer.
3. Every behaviour change ships with a regression test. Contract changes below are
   additive unless explicitly marked **BREAKING**, and are documented in `docs/api`.
4. Remote/owner-only actions (branch protection, history rewrite, licence choice,
   pushing) are prepared but not executed without explicit owner confirmation.

## 2. Parallel ownership map (disjoint files)

| Workstream | Owns (exclusive write) |
|---|---|
| **BE-Platform** | `backend/app/main.py`, `backend/app/core/*` except `security.py` (may extend, never break, `correlation.py`, `errors.py`, `http_cache.py`, `pagination.py`), `backend/app/db/*`, `backend/app/api/readiness.py`, `backend/app/api/v1/__init__.py`, `backend/app/websocket/**`, `backend/app/events/**` except the consumers listed for other owners, `backend/scripts/stream_retention.py`, new `backend/scripts/dead_letter.py` |
| **BE-Identity** | `backend/app/core/security.py`, `backend/app/modules/identity/**`, `backend/app/modules/organization/**`, `backend/app/api/v1/{auth,organizations,audit}.py`, `backend/app/events/consumers/audit_consumer.py` |
| **BE-Network** | `backend/app/modules/network/**` (not `models.py`/`outbox_models.py`), `backend/app/api/v1/{networks,topology,spatial}.py`, `backend/app/events/consumers/topology_consumer.py`, **new** `backend/app/modules/{intent,simulation,autonomy}/queries.py` (read-only `has_blocking_work`) |
| **BE-Telemetry** | `backend/app/modules/telemetry/**` (not `models.py`), `backend/app/api/v1/{telemetry,telemetry_paths}.py`, `backend/app/events/consumers/telemetry_consumer.py`, telemetry worker scripts |
| **BE-Workflows** | `backend/app/modules/{intent,simulation,plugin}/**` (not `models.py`, not `intent/lab.py`, not `*/queries.py`), `backend/app/api/v1/{intents,simulation,plugins}.py`, `backend/app/events/consumers/simulation_consumer.py`, intent/simulation worker scripts |
| **BE-AlertReport** | `backend/app/modules/{alert,report}/**` (not `models.py`), `backend/app/api/v1/{alerts,reports}.py`, `backend/app/events/consumers/{alert,report}_consumer.py`, report/alert worker scripts |
| **BE-Autonomy** | `backend/app/modules/autonomy/**` except `experimental/**` and `models.py`/`queries.py`, `backend/app/api/v1/{autonomy,autonomy_controls,model_diagnostics}.py`, autonomy worker scripts |
| **BE-DB** | every `backend/app/modules/**/models.py` and `*_models.py`, `backend/alembic/**` (migration `0030`), model/migration parity tests |
| **FE-Platform** | `frontend/**` except `frontend/src/features/digitalTwin/**`; sole owner of `package.json`/`package-lock.json`, lint/ts/vite configs, `frontend/.env.example` |
| **FE-Twin** | `frontend/src/features/digitalTwin/**` |
| **Deploy-CI** | `deploy/**`, `.github/**`, `backend/docker-compose.yml`, `backend/Makefile`, `backend/.env.example`, `scripts/*.sh`, `scripts/{audit_dependencies,evidence_hygiene,run_portable_tests,check_fakeredis_lua}.py` (+tests), `security/**`, `.gitignore` files, repository governance files, `backend/tests/private_artifacts.txt`, `backend/tests/integration/test_gateway_headers.py`, `backend/tests/unit/test_proxy_boundary.py` |
| **AI-Emulation** | `ai-engine/**`, `emulation/**`, `backend/app/modules/autonomy/experimental/**`, `backend/app/modules/intent/lab.py`, root research `scripts/*.py` not owned by Deploy-CI, experimental/passive-observer/native-qualification backend tests and scripts |
| **Integrator** | cross-cutting fallout, `docs/**` updates, final verification |

Tests live with the code they cover; an owner may edit tests for its own code only.

### 2.1 Wave-2 ownership amendments (after interruption, 2026-09-23)

- Completed wave-1 owners: BE-Platform, BE-Identity, BE-Telemetry, BE-Workflows. Their files are
  now free; follow-ups go to **BE-Followups**.
- **BE-Network** and **BE-AlertReport** resume from their partial diffs (same ownership).
- `backend/app/modules/autonomy/{campaign_evidence,qualification}.py` move to **AI-Emulation**
  (research evidence/statistics). `backend/app/modules/intent/autonomous.py` moves to **BE-Autonomy**.
- Deploy-CI splits into **Deploy-Runtime** (`deploy/**`, `backend/tests/integration/test_gateway_headers.py`,
  `backend/tests/unit/test_proxy_boundary.py`) and **CI-Repo** (`.github/**`, `backend/docker-compose.yml`,
  `backend/Makefile`, `backend/.env.example`, `scripts/*.sh`, `scripts/{audit_dependencies,evidence_hygiene,
  run_portable_tests,check_fakeredis_lua}.py` + tests, `security/**`, all `.gitignore` files, governance
  files, `backend/tests/private_artifacts.txt`, `backend/scripts/review_fullstack.py` + its test,
  `backend/tests/unit/test_dev_setup.py`).
- **BE-Followups** owns: `backend/app/core/config.py` (additive settings only), new
  `backend/app/core/watchdog.py`, `backend/scripts/{verify_execution,verify_operator_override,
  verify_modeled_simulation,prepare_strathmore_demo}.py`, simulation/intent/plugin outbox follow-ups,
  `backend/tests/unit/test_rest_tenant_authorization.py`, `backend/tests/unit/test_inventory_restoration.py`.
- Progress notes for every wave-2 agent: `/home/DHB/.cache/nanfo-adr028/<workstream>.md` (survives reboot).

### 2.2 Wave-3 amendments (resume after orchestrator abort, 2026-09-24)

- Completed wave-2 owners: BE-Network, BE-AlertReport, BE-DB. Their files are free; follow-ups go to
  **BE-Followups** (backend) or the **Integrator**.
- Resumed in their own sessions with unchanged ownership: BE-Autonomy, BE-Followups, FE-Platform, FE-Twin,
  Deploy-Runtime, CI-Repo.
- AI-Emulation splits into two disjoint owners:
  - **AI-Emulation** keeps `ai-engine/**`, `emulation/frozen/**`, the root research scripts (`scripts/{adr024_campaign,
    verify_adr024_campaign,preserve_qualification_evidence,preserve_review_closure,recover_qualified_runtime,
    live_feed_evaluate,presentation}.py` + tests), `backend/app/modules/autonomy/{campaign_evidence,qualification}.py`,
    frozen-model backend scripts, the campaign-014 private-evidence copies, and the lab launchers
    (`ai-engine/src/nanfo_routing/supervisor.py`, `scripts/adr024_campaign.py`).
  - **AI-Lab** owns `emulation/**` except `emulation/frozen/**`, `backend/app/modules/autonomy/experimental/**`
    except `models.py`, `backend/app/modules/intent/lab.py` (+ a minimal edit to the single mailbox-writing
    function), and the experimental/passive-observer/native-qualification backend scripts and tests.

## 3. Cross-workstream contracts

### C1. WebSocket authentication transport (replaces query tokens)
- Client connects to `/ws/<channel>` **without** a query string and offers subprotocols
  `["nanfo.v1", "nanfo.bearer.<access_token>"]`. The server selects exactly `nanfo.v1`
  (never echoes the bearer entry). `?token=` remains accepted for one compatibility
  release and is redacted from every log line.
- Invalid/expired/unauthorised token → close **before accept** with 1008 (HTTP 403 upgrade).
- Dependency outage during auth/subscribe → accept, send
  `{"event":"error","data":{"code":"WS_UNAVAILABLE","message":"Realtime temporarily unavailable."}}`,
  close **1013**. Clients retry with jittered backoff; never treat as a filter error.
- No subscribe frame within 10 s → `WS_SUBSCRIBE_TIMEOUT` + close 1013 (client retries).
- Per-user concurrent socket cap (default 16) → `WS_CONNECTION_LIMIT` + close 1008
  (client stops, shows a visible *Retry realtime* control).
- Authorization is cached per connection for ≤15 s (never beyond token `exp`); the
  server closes with `WS_UNAUTHORIZED` + 1008 at token expiry even on idle channels.
- `WS_INVALID_FILTER`, `WS_UNKNOWN_CHANNEL`, `WS_FORBIDDEN` remain terminal.

### C2. Error envelope
- `503 DEPENDENCY_UNAVAILABLE` (+ `Retry-After`) for backing-service outages
  (`app.core.errors.DependencyUnavailableError`, Redis/SQLAlchemy/Neo4j connection errors).
  Redis session-store outages return 503, **not** 401.
- `413 REQUEST_TOO_LARGE` for bodies over the route limit (default 1 MiB; asset upload 12 MiB).
- Validation failures stay **422** (API_STANDARD amended) and add
  `errors.details: [{"loc": [...], "type": "..."}]` (no input values, no ctx).
- Unhandled errors log the redacted stack (frames, not `exc.args`) with request id.

### C3. Intent idempotency (**BREAKING for duplicate keys**)
- Migration 0030: unique `(workspace_id, idempotency_key) WHERE idempotency_key IS NOT NULL`
  on `intents`; pre-existing duplicates keep the earliest row's key and later rows get
  `<key>~dup~<intent_id>` (data preserved, recorded in migration notes).
- `POST /intents/validate` with an existing key: same network + same normalized intent →
  returns the stored intent (`meta.idempotent_replay=true`); otherwise **409
  `IDEMPOTENCY_KEY_REUSED`**.
- Execute/cancel reuse the selected intent's stored `idempotency_key`; execute locks the
  intent row. Frontend generates a fresh key per validate submission.

### C4. Campus model assets (**BREAKING default**)
- `GET .../campus/model-assets` defaults to `include_data=false` (metadata pages).
  `include_data=true` requires `page_size<=10` and a 32 MiB aggregate body cap (else 400).
- Upload/upsert responses return metadata only (no `model_data_base64`).
- Downloads: `ETag: "sha256:<hex>"`, honour `If-None-Match` → 304, streamed body.
- Quota is per network (DB accounting); unreferenced blobs are garbage-collected.

### C5. Report download ETag (**BREAKING format**)
- `ETag: "sha256:<hex>"` (was `"<hex>"`), `If-None-Match` → 304. Clients accept both
  formats and weak validators; SHA-256 of the body is the authoritative check.

### C6. Organization caller role
- `OrganizationResponse` gains `caller_role: "Admin"|"Operator"|"Read-Only"` on list/get.
- Org `GET` returns the same 404 for "absent" and "not a member".

### C7. Audit platform scope
- `GET /audit/logs?scope=platform` (global Admin only) returns `org_id IS NULL` events
  (authentication). Default `scope=org` keeps requiring `org_id`. `page<=10000`.

### C8. Device-group optimistic concurrency
- Each upsert group item may carry `expected_updated_at` (ISO-8601). Mismatch → 409
  `DEVICE_GROUP_CONFLICT`. Responses always contain real `updated_at`.

### C9. Refresh-token retry grace
- Re-presenting the refresh token rotated **≤20 s** ago returns the *same* issued pair
  (idempotent retry after a lost response / concurrent tab). Otherwise reuse detection
  revokes the family as before and is audited as `auth.token.reuse_detected`.
- Deactivation, password change and role downgrade revoke all of a user's sessions
  (per-user session index). Idle sessions expire after 12 h without refresh.

### C10. JWT claims (**BREAKING for pre-deploy tokens**)
- Tokens carry `iss="nanfo-api"`, `aud="nanfo"`; decode requires them with 30 s leeway;
  algorithm restricted to HS256/384/512; library PyJWT (python-jose removed).
- Services with `NANFO_SERVICE_ROLE=worker` do not require `JWT_SECRET_KEY`.

### C11. Login throttling
- Per-IP bucket counts all attempts; per-email bucket counts **failures** only and is
  cleared on success; only the first throttled attempt per window is audited.
- Passwords over 72 UTF-8 bytes are rejected (login returns the generic 401).

### C12. Telemetry health
- `GET /telemetry/health` is read-only (never publishes alerts). SLO evaluation runs in
  the collector worker with persisted windows; health returns an additive `slo` object.

### C13. Network inventory events
- Inventory event payloads gain `sequence` (per-network outbox sequence). Consumers order
  by `(network_id, sequence)` when present, falling back to timestamp for old events.

### C14. Domain-stream retention and DLQ
- Supervised deployments run `python -m scripts.stream_retention schedule` continuously
  (archive-before-delete, bounded batches); the dead-letter stream is included.
- `python -m scripts.dead_letter {list,replay,purge}`; purge archives first.
- Transient handler failures are retried via pending-entry reclaim with backoff; only
  deterministic failures or `delivery_count > EVENT_MAX_DELIVERIES` are dead-lettered.

### C15. Lab command authentication
- Mailbox command envelopes carry `hmac_sha256` over the canonical envelope using the key
  at `NANFO_LAB_COMMAND_KEY_FILE` (≥32 bytes, 0600/0400). Reader rejects missing/invalid
  MACs and non-owner files. Deploy provisions the secret for the execution worker and lab.

### C16. Frontend base URLs
- Production builds default to same-origin API (`""`) and derive `ws(s)://` from
  `window.location`; builds fail if a production `VITE_API_BASE_URL` points at loopback.

### C17. Autonomy confidence (constitution §2)
- Proposals carry typed `confidence {value, method, calibrated, calibration_id}`.
  Autonomous dispatch requires `calibrated=true` and `value >= min_confidence` unless the
  operator policy sets `allow_uncalibrated_confidence=true` (experimental lab only);
  refusals record reason `confidence_uncalibrated` / `confidence_below_threshold`.

### C18. Simulation before execution (constitution §2)
- High-impact manual lab actions require a completed, passing simulation of the same
  network whose limits respect server policy floors; its id and plan hash are bound into
  the execution record. The autonomous path is gated by the ADR-012 SafetyShield
  certificate plus C17; this is recorded as the constitution's pre-execution validation.

### C19. JWT signing-key rotation overlap
- `JWT_PREVIOUS_SECRET_KEYS` (comma-separated, verify-only) lets `manage.py rotate --secret
  jwt_secret` roll the signing key without logging users out; tokens are always signed with
  `JWT_SECRET_KEY` and verified against current then previous keys.

### C20. Shared helpers (already present; extend, never break)
- `app.core.correlation.normalize_audit_correlation` — the only request-id → UUID mapping.
- `app.core.canonical.canonical_json_bytes/canonical_sha256` — byte-identical to the existing
  strict canonical-JSON digests; divergent variants (NaN-tolerant, `default=str`) stay local.
- `app.core.http_cache.digest_etag/if_none_match_satisfied`, `app.core.pagination.PageNumber`,
  `app.core.errors.DependencyUnavailableError/RequestTooLargeError`.
- Worker job tables gain `claim_attempts` (reports, simulations) in migration 0030; jobs
  exceeding `*_MAX_CLAIM_ATTEMPTS` become terminal `failed` with reason `attempts_exhausted`.

### C21. Receiver health receipts (asymmetric)
- Receipts are signed with Ed25519 by the receiver iteration and verified with the public key only:
  `NANFO_RECEIVER_HEALTH_PRIVATE_KEY_FILE` (receiver) / `NANFO_RECEIVER_HEALTH_PUBLIC_KEY_FILE`
  (verifiers), PEM, 0400/0600, receipts carry `key_id` (SHA-256 of the raw public key, first 16 hex).
- Legacy HMAC receipts are accepted only when `NANFO_RECEIVER_HEALTH_LEGACY_HMAC=true` (frozen runtimes).

### C22. Production gateway browser lane
- `backend/scripts/review_fullstack.py` builds the frontend **without** `VITE_API_BASE_URL`, serves `dist`
  through the real `deploy/nginx.conf` (test upstream include pointing at the local API) and runs the
  full-stack Playwright suite against the gateway origin (same-origin API and WebSocket).
- On failure the sanitized report includes case name, error class and a redacted first error line.

### C23. Lab container security profile
- The default (successor) lab runs with `cap_drop: [ALL]`, `cap_add: [NET_ADMIN, NET_RAW, SYS_ADMIN]`,
  `security_opt: [no-new-privileges:true]`, `nosuid,nodev` tmpfs, on a supported base image with
  hash-pinned requirements. The frozen privileged EOL image is available only through the explicit
  opt-in overlay `deploy/compose.lab.frozen.yaml` / `NANFO_LAB_FROZEN=1` for historical reproduction.
  The successor requires fresh qualification before any result claim.

### C24. Redis ACL and per-service secrets
- Redis defines ACL user `nanfo` (`+@all -@dangerous +info +client|setname +client|id`, all keys, all
  channels); the `default` user is disabled. Backend setting `REDIS_USERNAME` (default `None`).
- Secrets are staged into two volumes: `runtime_secrets_api` (includes `jwt_secret`) and
  `runtime_secrets_worker` (no `jwt_secret`); workers run with `NANFO_SERVICE_ROLE=worker`.

### C25. Autonomy governance (constitution §2, security F3)
- Switching a network to `autonomous` is two-person: user A's `PUT /autonomy` records a pending request
  (Redis, TTL 1 h, bound to revision and mode, response `meta.pending_approval=true`); a *different* user's
  identical `PUT` confirms it. `AUTONOMY_REQUIRE_DISTINCT_APPROVER` (default true).
- Clearing an emergency STOP requires org role Admin. STOP itself is allowed for any org member holding
  `read:telemetry` when `AUTONOMY_STOP_ALLOW_READ_ONLY=true` (default true); every STOP is audited.
- Mode approvals, STOP, overrides and configuration changes are written with `append_audit_log`.

### C26. Tenant fairness for shared resources
- Report storage is admitted per organisation (`REPORTS_MAX_BYTES_PER_ORG`, default 512 MiB) in
  addition to the global reserve. Model diagnostics lock per network, not globally.

## 4. Migration 0030 (BE-DB)

Unique intent idempotency (C3, with dedupe); unique active campus building
`(network_id, building_id) WHERE deleted_at IS NULL` (dedupe older rows by soft delete);
concurrent indexes `telemetry_records(device_id, observed_at DESC, record_id DESC)`,
`audit_logs(org_id, "timestamp" DESC, log_id DESC)`; alert tenancy columns
`org_id/workspace_id/network_id` (backfilled from payload) + index
`(workspace_id, updated_at DESC, alert_id DESC)`; missing FK indexes; fixed server
defaults; `created_at` on simulation/report outboxes; `claim_attempts INT NOT NULL DEFAULT 0`
on `reports` and `simulations`; BRIN index on `telemetry_records(observed_at)`; `NOT VALID`
status CHECKs where the value set is closed in code; `eager_defaults=True` on every mapper
with an `onupdate=func.now()` column. All model `__table_args__` mirror migration
indexes/checks.
Revision `0031` is reserved for BE-Telemetry if retention needs schema.

## 5. Explicitly not performed by this change (owner action required)

- Enabling branch protection / rulesets on GitHub (prepared in `.github/rulesets/`).
- Git history rewrite of the 71 expired receiver tokens (history scan allowlists them).
- Choosing a licence; pushing or committing.
- Physical RF survey, user study, repeated training and live lab qualification of
  successor runtimes (code and protocols are delivered; evidence is not invented).

## 6. Implementation outcome

Wave 1 ran on 2026-09-23, waves 2–3 (§2.1, §2.2) on 2026-09-24. Counts are each owner's
targeted runs, not a full-suite run. The owners wrote or updated the DSN-gated PostgreSQL /
real-Redis suites, the Compose-CLI render tests and the live-lab lanes but did not run them.
Detailed contracts: `docs/api/ADR028-ContractChanges.md` and the module READMEs.

- **BE-Platform.** C1 WebSocket transport (bearer subprotocol, closes 1008/1013/1011/1009,
  16 sockets per user, 10 s subscribe timeout, authorization cache of at most 15 s, close
  at token expiry). C2 handlers (503 + `Retry-After`, 413, 422 `details`, stack traces
  logged without messages). C14 delivery: transient failures stay pending, deterministic
  ones are dead-lettered, stable consumer names and a janitor, the retention `schedule`
  loop, `scripts/dead_letter.py`. Also: an envelope version gate, publisher memory
  admission, bounded Redis/PostgreSQL/Neo4j pools and timeouts, lease-loss fencing, and
  `main.py` split into `core/exception_handlers.py` and `runtime/lifespan.py`. `APP_ENV`
  now defaults to `production`, where the API docs are off. Tests:
  `integration/test_ws_transport_contract.py` (24), `test_event_bus_delivery.py`,
  `test_retention_invariants.py` (28), `test_dead_letter_cli.py`,
  `test_logging_redaction.py`, Lua harness `tests/lua_streams.py`. Result: 871 passed,
  34 skipped.
- **BE-Identity.** C10 PyJWT; python-jose, ecdsa, pyasn1, rsa and six are gone from the
  lock. C11 throttling and the 72-byte password limit. C9 retry grace (the issued pair is
  sealed with AES-GCM for 20 s), a per-user session index, 12 h idle expiry,
  `IdentityAccountService` deactivate/password/role changes that revoke sessions, and
  `scripts/revoke_user_sessions.py`. C7 `AuditQueryService`. C6 `caller_role` and a
  uniform 404. Redis outages return 503. Tests: `test_security_pyjwt.py` (18),
  `test_login_throttling.py` (10), `test_session_lifecycle.py`, `test_audit_query.py`,
  `test_org_adr028.py`, `test_revoke_user_sessions_cli.py`.
- **BE-Telemetry.** C12 read-only health and a collector-side SLO evaluator with Redis
  windows and platform-scoped alerts. `service.py` split into modules of at most 400 lines.
  Also: a per-target fleet scheduler, a cached owner-authorization batch check, capped
  history counts, the retention stranding fix with segment archives and `--loop`, strict
  timestamps, and SNMPv3 secrets in a private memory-backed directory. Reserved revision
  0031 was not needed. Tests: `test_telemetry_slo_evaluator.py`,
  `test_telemetry_references.py` (11), `test_telemetry_retention.py` (22). Result: 576
  passed, 51 skipped.
- **BE-Workflows.** C3 idempotent validate, stored-key execute/cancel and row-locked
  execute. C18 simulation evidence with policy floors. Approval binding, a four-eyes rule,
  commit-before-publish with stable event IDs and deferred sweeps, and bounded intent
  documents. Simulation: claim-attempt exhaustion to `failed`, fair claiming, the
  workspace quota and off-loop checkpoint verification. Plugin signatures are now labelled
  "declared", never "verified". Tests: `test_intent_schemas.py`,
  `test_simulation_worker.py` and the updated intent/simulation/plugin suites. Result: 415
  passed, 33 skipped.
- **BE-Network** (waves 1–2). Bounded BFS traversal. Tombstoned devices are excluded.
  `ensure_graph_schema()` runs at startup. Reconcile does a real resync. C13 outbox
  `sequence`, and edge writers lock their endpoints. C4 asset contract: metadata by
  default, per-network quota, unreferenced-object GC (`python -m app.modules.network.asset_gc`),
  and digest ETag downloads. Buildings are upserted in place. C8 device-group concurrency.
  A single `NetworkAccessGuard`. Deletion is blocked by unreleased autonomous executions.
  Also: read-only `{intent,simulation,autonomy}/queries.py`, public `get_device(s)_for_owner`
  and `build_emulation_discovery`, outbox retention, and spatial-history delta storage (a
  full copy every 20 revisions). Tests: `test_network_access_and_queries.py`,
  `test_spatial_history.py` (37), `test_network_outbox.py`, `test_topology_traversal.py`.
  Result: 1072 passed, 68 skipped.
- **BE-AlertReport** (waves 1–2). Alert tenancy columns with array binds. Exact list
  counts. Bounded search. Platform-scoped SLO alerts, readable by a global Admin only and
  read-only. `alert_observations` retention. Poison events are dead-lettered. Reports:
  claim-attempt exhaustion, C5 `sha256:` ETag/304 with streamed verified bytes, the font
  fallback, the C26 per-organisation quota and outbox retention. Tests:
  `test_alert_tenancy.py`, `test_alert_observation_retention.py` (10),
  `test_report_org_quota.py` (13), `test_report_operations.py`. Result: 345 passed,
  44 skipped.
- **BE-DB.** Migration `0030_adr028_schema_remediation` (single head) implements §4, plus
  the spatial-history delta columns and a BRIN index on `alert_observations(observed_at)`.
  It runs a transactional part under `lock_timeout`, then an autocommit concurrent part.
  It is idempotent on re-run, and its downgrade refuses while delta history exists. Models
  mirror every migration index, CHECK and server default. Alembic `env.py` compares types
  and server defaults and runs one transaction per migration. Historical downgrades now
  refuse while immutable evidence exists. Tests: `test_model_migration_parity.py` (40,
  offline, zero drift) and `integration/test_migrations_postgres.py` (12,
  `MIGRATION_TEST_DSN`).
- **BE-Autonomy** (waves 2–3). C17 typed confidence and its gates, including a re-check in
  the receiver. STOP is a single conditional upsert with a bounded lock (`AUTONOMY_STOP_BUSY`);
  providers are cached and acceptance does no I/O. STOP cancels through journal recovery.
  C25 two-person mode switch, Admin-only STOP clear and audited governance. Decision
  coalescing, retention and summary projections. A driver registry. C21 Ed25519
  receipts v2. C26 per-network diagnostic lease with per-organisation slots.
  `intent/autonomous.py` is removed. Tests: `test_autonomy_adr028.py`,
  `test_autonomy_drivers.py` (28), `test_receiver_health_review.py` (52),
  `test_model_diagnostics.py`, `test_autonomy_canonical.py` (57),
  `integration/test_autonomy_endpoints.py`.
- **BE-Followups** (waves 2–3). Typed, bounded settings for every name read through
  `getattr` (33 names, none undeclared). C24 `REDIS_USERNAME` is carried in every Redis URL.
  A process watchdog (exit 70) in the API and three worker runners. Deep-JSON bodies were
  verified to give 400/422, never 500. Workers, not repositories, now own intent/simulation
  commits. Simulation/intent outbox retention. `CURRENT_SCHEMA = "0030"`. An 8 MiB
  spatial-scene PUT limit. The verify/demo scripts follow the new approval and simulation
  rules. Tests: `test_settings_followups.py`, `test_redis_acl_username.py`,
  `test_watchdog.py` (30), `test_deep_json_bodies.py` (28),
  `test_intent_approval_scripts.py` (21), `test_schema_version.py`,
  `test_spatial_scene_body_limit.py`.
- **FE-Platform** (waves 2–3). C16 same-origin defaults and a loopback build guard. C1
  client. Transient-safe session refresh and duplicate-tab handling. Token-free query
  keys. Realtime burst batching. Generated OpenAPI types (`npm run api:types`,
  `api:check`) with compile-time guards. Status tones that match the backend value sets
  exactly. C3/C18 intent flow (a fresh key per submission, guidance for every 409).
  C17/C25 autonomy views. ETag-tolerant report downloads. Error-handling and accessibility
  work. Type-aware lint with zero warnings, and `exactOptionalPropertyTypes`. Removed
  `@react-three/drei` and `clsx`. Tests: 131 files / 909 vitest tests and 71 Playwright
  tests (`generate-types.test.ts`, `statusTones.test.ts`,
  `shared/realtime/useManagedWebSocket.test.tsx`, `tokenRotation.test.tsx`,
  `tests/fullstack/origins.test.ts`).
- **FE-Twin** (waves 2–3). `TwinPageContent` is now a ~95-line orchestrator. The Canvas
  stays mounted outside the query states, with a WebGL error boundary and a 2D plan
  fallback. A virtualized node combobox. Backend-authoritative severity. On-demand
  rendering and instancing. Validated model import. Reviewed persist dialogs for buildings
  and device groups (C8). Explicit loading and error states. Accessibility fixes. Tests:
  47 files / 266 vitest tests.
- **Deploy-Runtime** (waves 2–3). Supervised `stream-retention`, `telemetry-retention` and
  `asset-gc` loops. Explicit `APP_ENV` and `NANFO_SERVICE_ROLE` on every service. Split
  secret volumes and the Redis ACL with `default` off (C24). C23 successor lab overlay with
  a frozen opt-in overlay. C15/C21 key provisioning. A hardened gateway (strict headers,
  login rate limit, trusted hop). Backup format 2 with streaming restore. Rotation
  `--resume`. `autoheal`. A pinned fleet egress subnet. An allowlisted backend image
  context. Current store digests. Tests: `deploy/tests/test_adr028_manage.py`,
  `test_adr028_runtime.py`, `test_backup_v2.py` (34), `test_gateway_config.py` (24),
  `test_verify.py` (62). Results: deploy 417 passed, 9 deselected; gateway 25 passed,
  6 deselected.
- **CI-Repo** (waves 2–3). Quality lanes with the `private_artifacts` marker,
  `COVERAGE_FLOOR`, a skip budget (`.github/scripts/ci_gates.py`) and the full `ai`
  suite. `packaging.yml`: hadolint, compose render, image builds, `nginx -t` and trivy.
  A PostgreSQL 17 `migrations` job. The C22 gateway browser lane. The ruleset
  `.github/rulesets/main.json` with 13 checks. SHA-pinned actions and Dependabot.
  Full-history gitleaks. Evidence location rules. The ecdsa exception is removed and the
  emulation audit is split into `emulation` and `emulation-frozen`. Dev stores on the
  production digests with a Redis ACL user. `.env.example` documents every setting except
  the unused `REPORTS_ARTIFACT_BUCKET` (§7.1). Added
  `CONTRIBUTING.md`, `SECURITY.md`, `CODEOWNERS` and a PR template. Tests:
  `.github/scripts/test_{ci_gates,workflows,governance}.py`,
  `scripts/test_evidence_hygiene.py` (23), `test_audit_dependencies.py` (21),
  `test_run_portable_tests.py`, `backend/tests/unit/test_env_example.py`,
  `backend/scripts/test_review_fullstack.py` (35). Portable lane: 722 cases, zero skips.
- **AI-Emulation** (waves 2–3). Tracked byte-identical copies (with `SHA256SUMS`) of the
  qualified checkpoint and the frozen client (`ai-engine/qualified/`) and of the frozen v4
  lab archive (`emulation/frozen/`). The successor protocol (`ai-engine/SUCCESSOR-PROTOCOL.md`).
  `adr024_campaign.py` launches the frozen lab only. A single pinned `weights_only`
  checkpoint load. Parameterised scratch and source roots. Calibration that issues
  `calibration_id` only for measured held-out data (none was produced). A Student-t
  qualification gate. `ai-engine` is pinned to Python 3.12.14. Tests:
  `test_frozen_identities.py` (8), `test_successor_protocol.py` (23),
  `test_checkpoint_safety.py`, `test_calibration.py` (11), and backend
  `test_qualification_student_t.py` (12) and `test_campaign_service_metrics.py`.
  Result: ai-engine 520 passed; a clean copy gives 489 passed plus 2 private skips.
- **AI-Lab** (wave 3). C23 successor image: digest-pinned `python:3.12.14-slim-trixie`,
  apt pins from a dated Debian snapshot, 34 hash-pinned dependencies, os-ken 4.2.2 in
  place of Ryu, and a runner that refuses any wider capability profile. The frozen recipe
  is kept byte-identical. A frozen-source loader that runs only verified bytes. Receiver
  policy v2 hardening. C15 command MACs (`emulation/lab_contracts.py`, shared contracts
  with drift tests). A Python 3.9 lab package: the observer and native clock moved to the
  backend. A fixed-argument observer helper. Guarded lab state writes. Leases on the
  database clock. A single metric-formula module (`experimental/formulas.py`).
  `freeze_runtime` now copies git-tracked source only. Tests were switched to the tracked
  copies (`backend/tests/private_artifacts.txt`: 45 → 37 entries). Tests:
  `emulation/tests/test_{successor_image,lab_contracts,experimental_receiver_hardening,
  experimental_runtime_loader,stdlib_lab_package}.py` and backend
  `test_passive_observer_adr028.py`, `test_experimental_constants.py`,
  `test_experimental_db_clock.py`. Results: emulation 197 passed, 6 skipped; backend
  experimental 432 passed, 57 skipped.

## 7. Integrator decisions

1. **`Settings.REPORTS_ARTIFACT_BUCKET` is kept** (CI-Repo's removal request was declined).
   `backend/.env` forbids unknown keys, so existing `.env` files that set it would stop the
   app from starting. It stays unused and is excluded from the `.env.example` completeness
   test.
2. **Campaign-014 private-evidence exception.** Campaign-014's own `plan.json` and
   `offline-gates.json` pin its 10 tracked files under
   `nanfo-experimental-campaign-014/source/deploy/state/adr023-private-evidence/`, and
   `seed-audit.json` lists them. Deleting them would break that campaign's source
   verification. The owner chose on 2026-09-24 a narrow evidence-hygiene exception for
   exactly these 10 paths, each pinned by SHA-256, rather than deletion or an immediate
   history rewrite. It is implemented in `security/evidence-location-exceptions.v1.json`
   (`--location-exceptions`): exact path, rule `tracked_deploy_state` and SHA-256 per file,
   so a changed byte, a rename, an eleventh file or a stale entry still fails. The final
   full scan reports 0 findings. The builder that swept them in (`freeze_runtime`) now
   copies git-tracked source only.
3. **Bundle cap raised from 420,000 B to 450,000 B** (`totalJsGzipBytesMax` in
   `frontend/src/scripts/perf/check-bundle-continuity.ts`); **awaiting owner confirmation**.
   The ADR-028 Twin and Platform features add about 29 kB gzip that chunk splitting cannot
   remove. Per-chunk caps are unchanged. Vetoing means trimming features.
4. **Qualify/infer overlap proven safe rather than serialised.** The installation-level
   qualification replay may overlap per-network inference. Each confined run gets a
   private stage and results are re-bound to installation identities. A private
   real-runtime test shows overlapped inference equals sequential inference. Serialising
   would queue every network behind a 120 s replay.
5. **Experimental retention enumeration is deliberately not gated by
   `NANFO_EXPERIMENTAL_LAB_ENABLED`.** Switching the lab off must not unpin telemetry that
   historical lab rows reference. The flag gates `run` and the C17 uncalibrated-confidence
   exception; status, stop and recover stay available.
6. **`intent/lab.py` imports `emulation.lab_contracts` lazily** (inside `Mailbox.write`),
   so `import app.main` never loads an emulation module, including from `backend/` without
   the repository root on `sys.path`. Backend code may import `emulation.*` only lazily.
7. **AI-Emulation / AI-Lab split (§2.2).** AI-Emulation owns the frozen and research side;
   AI-Lab owns the active lab and the experimental backend. Cross-requests went through
   the progress files. AI-Lab's formula module and `freeze_runtime` allowlist closed
   AI-Emulation's last two requests.

## 8. Owner actions

Prepared by this change; only the owner may perform them (§1.4, §5).

1. **Commit and push everything, including the untracked new files**, for example
   `ai-engine/qualified/`, `emulation/frozen/`,
   `frontend/src/shared/types/generated/openapi.ts`, `CONTRIBUTING.md`, `SECURITY.md`,
   `.github/{CODEOWNERS,dependabot.yml,pull_request_template.md,rulesets/}`,
   `.github/workflows/packaging.yml`, and the new modules and tests (list them with
   `git status --short | grep '^??'`). The commit also removes
   `backend/app/modules/intent/autonomous.py`. The tests switched to the tracked copies,
   and `freeze_runtime`, need these files committed. Re-run the full evidence-hygiene scan
   just before committing.
2. **Untrack two Playwright outputs**: `git rm --cached frontend/test-results/.last-run.json
   "frontend/test-results/spatial-geometry-dimension-29645-and-restores-omitted-shapes-chromium/canonical-geometry.png"`.
   The 10 campaign-014 files stay tracked under decision 2.
3. **GitHub** (steps in `CONTRIBUTING.md` → Branch protection):
   - Rulesets on a private repository need GitHub Pro, Team or Enterprise; otherwise
     make the repository public.
   - Merge the workflows and let one pull request run the 13 required checks once:
     `backend`, `frontend`, `ai`, `python-inventories`, `npm-lock`, `evidence-hygiene`,
     `database-contracts`, `migrations`, `stream-retention`, `production-browser`,
     `packaging`, `gateway-proxy-boundary`, `gateway-headers`.
   - Import `.github/rulesets/main.json`
     (`gh api --method POST repos/dhb001/NANFO/rulesets --input .github/rulesets/main.json`)
     and verify with `gh api repos/dhb001/NANFO/rules/branches/main`. Admins have no
     bypass unless one is added.
   - Enable the dependency graph, Dependabot alerts and Dependabot security updates.
   - Set Settings → Actions → General → workflow permissions to read-only.
   - `COVERAGE_FLOOR` is already 84 (85.60 % measured on CI's exact backend command, minus
     one point); no post-merge adjustment is needed.
4. **History rewrite and licence** (§5): rewrite the history that contains the 71 expired
   receiver tokens (commit `3f9f1f1`), then re-review the commit-bound fingerprints in
   `.gitleaksignore`. Choose a licence.
5. **Fresh qualification before any result claim**, never relabelling old results:
   - the successor lab image (`python3 emulation/control.py build`, then pin the image
     ID as `sha256:<64 hex>`);
   - the ADR025 receiver's successor wrapper (policy v2; fault campaigns start it with
     `--failpoints`);
   - the FRR runtime bindings. Edits to files in `RECEIVER_SOURCES` invalidate deployed
     bindings, which need a fresh reviewed equivalence. They also change the
     live-qualification receipt cache key, so qualification runs again after deploy.
   FRR experiment modes also need `NET_BIND_SERVICE` and, on AppArmor hosts, a profile
   that allows `/proc/sys/net/**` writes in the lab network namespaces.
6. **Passive-observer helper**: install `backend/scripts/nanfo_proc_timens.py` as
   `/usr/local/libexec/nanfo-proc-timens` (root, 0755) and add exactly this sudoers line:
   `nanfo-operator ALL=(root) NOPASSWD: /usr/local/libexec/nanfo-proc-timens ""`.
7. **Receiver key**: install `${NANFO_STATE_DIR}/receiver/receiver_health_private_key.pem`
   (PKCS#8 PEM, 0400/0600) only on the separately packaged FRR receiver, as
   `NANFO_RECEIVER_HEALTH_PRIVATE_KEY_FILE`. No container mounts it. There is no rotation
   command yet.
8. **Reviewed upgrade procedure for pre-ADR-028 deployments.** `manage.py` refuses
   ADR-020–027 deployments until one exists. It must cover the new configuration keys,
   the split secret volumes, `stream_archive`, the lab volume layout and schema 0030. It
   must also cover what the new contracts break:
   - pre-deploy JWTs lack `iss`/`aud`, so users log in again;
   - migration 0030 renames duplicate intent idempotency keys;
   - passwords over 72 bytes need a reset;
   - `APP_ENV` now defaults to `production`;
   - `NETWORK_ASSET_*` are read from the process environment only.
   `verify.py --reuse-build-record` now also needs `--redis-image sha256:<id>`.
9. **Confirm or veto the bundle-cap raise** (decision 3).

## Final verification (integrator)

Run on 24–25 September 2026 against the final working tree (base `e55a4f5` plus the
uncommitted ADR-028 changes). Throwaway PostgreSQL 17.11 / Redis 7.4.11 containers were
approved by the owner, bound to 127.0.0.1 without volumes, and removed afterwards.

| Lane | Command (summary) | Result |
|---|---|---|
| Backend (CI `backend` job) | `pytest tests/unit tests/integration -m "not private_artifacts"` with coverage | 5,335 passed, 367 skipped (DSN/Redis-image/opt-in), 94 deselected, 0 failed; coverage 85.64 % |
| Backend skip budget | `.github/scripts/ci_gates.py junit … --lane backend --min-cases 4500` | exit 0 (DSN skips 314 within the budget of 314) |
| Private-artifact lane | `pytest -m private_artifacts` (evidence present locally) | 94 passed, 0 skipped |
| Migrations (PG 17) | `alembic upgrade head → check → downgrade -1 → upgrade head → check` | single head 0030; both checks clean |
| Database contracts | 25 DSN suites incl. `test_migrations_postgres.py`, zero-skip gate | 323 passed, 0 skipped (two consecutive runs) |
| Stream retention | `test_stream_retention_redis.py` on the pinned Redis image | 29 passed, 0 skipped |
| Portable lane | `scripts/run_portable_tests.py` (deploy, emulation, scripts, `.github/scripts`) | 750 cases, 0 skips |
| Compose render (Docker CLI, no daemon) | `test_resolved_compose_contract_without_daemon`, `test_resolved_proxy_network_*` | 9 + 6 passed |
| Gateway | real nginx 1.30.5 (`NANFO_TEST_NGINX=1`): `test_gateway_headers.py` + `test_proxy_boundary.py` | 31 passed; `nginx -t` OK |
| ai-engine | `pytest -q`, `ruff check .` | 520 passed; clean |
| Frontend | lint, typecheck, vitest, build, `perf:bundle`, Playwright e2e, `api:check`, `npm audit` | clean; 909 tests; 422.34 KiB ≤ raised cap; 71 e2e passed; types match; 0 vulnerabilities |
| Hygiene | full evidence scan (`--tracked --include-untracked`), gitleaks history + pending diff + untracked | 0 findings; 0 leaks |
| Static | ruff, actionlint, shellcheck, hadolint (5 Dockerfiles), YAML/JSON parse | clean |

The integrator re-ran the backend, private, gateway, ai-engine, Compose-render and frontend
lint lanes on the final tree. The database lanes were run by the Integrator-DB agent; the
remaining frontend gates by FE-Platform at its final state (only `eslint.config.js` changed
afterwards, re-linted clean); hygiene, portable and static lanes by CI-Repo in its final
pass.

The database run found two product defects that no unit test had exposed; both are fixed
with unit and PostgreSQL regression tests:

1. **Report creation failed under the 0030 foreign key.** `report_outbox.report_id` now
   references `reports`, but without an ORM relationship SQLAlchemy flushed the outbox row
   first. `ReportOutbox.report` (many-to-one, `lazy="raise"`) orders the inserts.
2. **The STOP response reported the network as not stopped.** The latch is a raw SQL
   upsert and the session kept the pre-STOP control object, so the response showed
   `emergency_stopped=false`. The snapshot now re-reads the committed row
   (`get(fresh=True)`).

It also made 13 hidden PostgreSQL retention tests visible to CI (explicit
`RETENTION_TEST_DSN` gate), replaced the `'Viewer'` role that the 0030 CHECK rejects in
three acceptance scripts, and updated ten PostgreSQL tests to the ADR-028 contracts.

Not executable locally and first proven by CI: image builds and trivy (`packaging`), the
`production-browser` lane, and any lab build or live qualification (§8.5).
