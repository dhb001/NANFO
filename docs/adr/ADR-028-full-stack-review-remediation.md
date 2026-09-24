# ADR-028: Full-stack review remediation program

- Date: 2026-09-23
- Status: **Accepted.** The repository owner explicitly directed that every finding of the
  23 September 2026 full-stack review be fixed in one coordinated change.
- Base: commit `75b514f` (clean tree). Supersedes nothing; extends ADR-027 contracts.
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
