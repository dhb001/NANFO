# ADR-028 contract changes (C1–C26)

Owner: ADR-028 §3. This is the one list of every externally visible contract change made
by ADR-028. The envelope `{success,data,meta,errors}` and status-code rules are in
`API_STANDARD.md`. Transport, identity and event details are in `WebSocket.md`,
`Authentication.md` and `EventAPI.md`. Module-level detail is in the owning module READMEs
under `backend/app/modules/*/README.md`.

ADR-028 treats a change as additive unless it marks it **BREAKING**. Only four items
carry that label: C3, C4, C5 and C10. Some unlabelled items still change an existing
response; the Label column and the sections below call those out (for example C6, C11,
C18 and C25). No new endpoints or domain event names were added. Audit-only actions are
not bus events.

## Summary

| Contract | Surface | Change | Label |
|---|---|---|---|
| C1 | `/ws/*` | Bearer in `Sec-WebSocket-Protocol`; new close codes and error codes | additive; `?token=` kept for one compatibility release |
| C2 | all REST | 503 `DEPENDENCY_UNAVAILABLE`, 413 `REQUEST_TOO_LARGE`, 422 `errors.details` | additive |
| C3 | `/intents/validate`, `/intents/execute` | Unique idempotency key per workspace; replay or 409 | **BREAKING for duplicate keys** |
| C4 | campus model assets | Metadata pages by default; `include_data=true` bounded; 304; 507 quota | **BREAKING default** |
| C5 | report download | `ETag: "sha256:<hex>"`; 304 | **BREAKING format** |
| C6 | organizations | `caller_role`; one 404 for "absent" and "not a member" | additive field; the non-member GET changes from 403 to 404 |
| C7 | `/audit/logs` | `scope=platform`; `page <= 10000` | additive |
| C8 | device groups | `expected_updated_at`; 409 `DEVICE_GROUP_CONFLICT` | additive |
| C9 | `/auth/refresh`, sessions | 20 s retry grace; revocation on account changes; 12 h idle expiry | additive |
| C10 | JWT | `iss="nanfo-api"`, `aud="nanfo"` required; PyJWT, HS256/384/512 | **BREAKING for pre-deploy tokens** |
| C11 | `/auth/login` | Per-IP (all attempts) and per-email (failures) buckets; 72-byte limit | behaviour: passwords over 72 bytes now fail with 401 |
| C12 | `/telemetry/health` | Read-only; `slo`, `total_records_estimated` | additive |
| C13 | network inventory events | Payload `sequence` | additive |
| C14 | Redis streams | DLQ CLI, retention `schedule`, delivery rules | operator contract |
| C15 | lab mailbox | `hmac_sha256` on command envelopes | internal |
| C16 | frontend build | Same-origin API/WS defaults; loopback build guard | build contract |
| C17 | autonomy | Typed `confidence`; calibration gates | additive |
| C18 | intents/simulations | Simulation evidence required for high-impact lab actions | behaviour (409 codes) |
| C19 | JWT keys | `JWT_PREVIOUS_SECRET_KEYS` verify-only overlap | operator contract |
| C20 | workers | `claim_attempts`; terminal `failed` / `attempts_exhausted` | additive |
| C21 | receiver receipts | Ed25519 v2 receipts with `key_id` | internal |
| C22 | CI | Production-gateway browser lane | CI contract |
| C23 | lab container | Successor capability profile; frozen overlay opt-in | deployment contract |
| C24 | Redis/secrets | ACL user `nanfo`; `REDIS_USERNAME`; split secret volumes | deployment contract |
| C25 | `PUT /autonomy` | Two-person switch (202 pending); Admin-only STOP clear | behaviour |
| C26 | reports, model diagnostics | Per-org report quota (507); per-network/per-org diagnostic 429 | additive |

## Transport and errors (C1, C2)

Normative text: `WebSocket.md` §2 and §5, `API_STANDARD.md` §3.

- WebSocket: offer `["nanfo.v1", "nanfo.bearer.<access_token>"]` and no query string. The
  server selects `nanfo.v1` only.
- WebSocket errors and closes:
  - `WS_UNAVAILABLE` or `WS_SUBSCRIBE_TIMEOUT`: close 1013 (retry with jitter);
  - an unexpected server error: `WS_UNAVAILABLE`, close 1011;
  - `WS_CONNECTION_LIMIT` (16 sockets per user): close 1008 (stop and show *Retry realtime*);
  - token expiry: `WS_UNAUTHORIZED`, close 1008;
  - inbound frames over 64 KiB: close 1009.
- 503 `DEPENDENCY_UNAVAILABLE` with `Retry-After` (default 5 s; 10 s for Redis memory
  admission) for PostgreSQL, Redis, Neo4j or storage outages. Session-store outages are
  503, never 401. Clients must not log the user out on 503.
- 413 `REQUEST_TOO_LARGE` over the route body limit:
  - default 1 MiB (`API_MAX_BODY_BYTES`);
  - `POST .../campus/model-assets` 12 MiB (`API_MAX_ASSET_UPLOAD_BYTES`);
  - `PUT .../spatial-scene` 8 MiB (`API_MAX_SPATIAL_SCENE_BYTES`).
- 422 `VALIDATION_ERROR` adds `errors.details: [{"loc": [...], "type": "..."}]`, at most 20
  entries. Input values and context are never included, and location names the route does
  not declare are masked as `"*"`. Bodies nested too deeply to parse are 400 `BAD_REQUEST`.
- Invalid JWTs return 401 `AUTH_TOKEN_MISSING_OR_INVALID`.

## Identity, organizations and audit (C6, C7, C9, C10, C11, C19)

Normative text: `Authentication.md`.

- **C10 (BREAKING for pre-deploy tokens).** Tokens carry `iss="nanfo-api"` and
  `aud="nanfo"`. Decoding requires `exp`, `iat`, `sub`, `jti`, `iss` and `aud`, with 30 s
  leeway and the configured HS256/384/512 algorithm only. Tokens issued before deployment
  fail with 401, so users log in again. Library: PyJWT (python-jose removed). Services with
  `NANFO_SERVICE_ROLE=worker` need no `JWT_SECRET_KEY`.
- **C19.** `JWT_PREVIOUS_SECRET_KEYS` (comma-separated) are verify-only. Tokens are signed
  with `JWT_SECRET_KEY` and verified against the current key, then the previous ones.
  Rotation procedure: `deploy/OPERATIONS.md` → Credential Rotation.
- **C9.** Re-presenting a refresh token rotated at most 20 s ago
  (`AUTH_REFRESH_GRACE_SECONDS`) returns the *same* pair, but only while that pair is still
  the newest in its session family. Any other reuse revokes the family and is audited as
  `auth.token.reuse_detected`. Sessions expire after 12 h without a refresh
  (`AUTH_SESSION_IDLE_TIMEOUT_SECONDS`, sliding, never past the absolute lifetime).
  Deactivation, password change and role downgrade revoke every session of the user.
- **C11.** Login throttling uses `RATE_LIMIT_LOGIN_MAX_ATTEMPTS` (5) per
  `RATE_LIMIT_LOGIN_WINDOW_SECONDS` (60):
  - the per-IP bucket counts every attempt;
  - the per-email bucket (keyed by SHA-256) counts failures and is cleared on success;
  - a throttled attempt returns 429, and only the first per window is audited.
  Passwords over 72 UTF-8 bytes get the generic 401 (existing such accounts need a reset).
  Length bounds: `refresh_token` at most 4096 characters, email at most 254.
- **C6.** `OrgResponse` gains `caller_role: "Admin" | "Operator" | "Read-Only"` on list,
  get, create and update. `GET /organizations/{org_id}` returns the same 404 for an absent
  organization and for a caller who is not a member.
- **C7.** `GET /api/v1/audit/logs`:
  - `scope=platform` (global Admin, unscoped token only) returns `org_id IS NULL` events
    such as authentication. With `org_id` it is 422; with an org-scoped token, 403.
  - The default `scope=org` still requires `org_id` or an org-scoped token, plus membership.
  - Workspace-scoped tokens are denied (403), because audit rows carry no workspace.
  - `page` is 1..10000. Data adds `scope`.
  - Search: a UUID term matches UUID columns exactly; other terms are an escaped
    case-insensitive substring.
- New audit-only actions: `auth.token.refresh_failed`, `auth.token.reuse_detected`,
  `auth.user.sessions_revoked`, `auth.user.deactivated`, `auth.user.password_changed` and
  `auth.user.roles_changed`, with resource types `auth_session` and `user`.

## Network, assets, topology and spatial (C4, C8, C13)

Detail: `docs/features/Network.md` §3.4–3.5 and `SpatialScene.md`.

- **C4 (BREAKING default).** `GET /api/v1/networks/{network_id}/campus/model-assets` now
  defaults to `include_data=false`. It returns metadata pages `{items,total,page,page_size}`
  (`page` 1..10000, `page_size` 1..100, default 20) and omits `model_data_base64`.
  - `include_data=true` requires `page_size <= 10`, else 400
    `CAMPUS_MODEL_ASSET_INLINE_PAGE_TOO_LARGE`.
  - The inline bodies of one page are capped at 32 MiB in total, else 400
    `CAMPUS_MODEL_ASSET_INLINE_LIMIT_EXCEEDED`. The cap is checked from metadata before
    any body is loaded.
  - Upload/upsert responses return metadata only.
  - Quotas:
    - per network: `NETWORK_ASSET_NETWORK_MAX_ACTIVE_BYTES` (256 MiB) and
      `NETWORK_ASSET_NETWORK_MAX_ACTIVE_ASSETS` (64), counted in the database;
    - global store caps;
    - both return 507 `CAMPUS_MODEL_ASSET_QUOTA_EXCEEDED`.
  - `GET .../campus-model-assets/{asset_id}/download` returns `ETag: "sha256:<hex>"`,
    honours `If-None-Match` (strong or weak, lists, `*`) with 304, and streams the verified
    body with `Cache-Control: private, no-store`.
  - `python -m app.modules.network.asset_gc` removes only objects that no asset row
    references. Retired assets keep their bytes.
- **C8.** Each device-group upsert item may carry `expected_updated_at` (ISO-8601 with a
  UTC offset). A changed or missing active group returns 409 `DEVICE_GROUP_CONFLICT`
  (reload, then retry). Responses always carry the real `updated_at`.
- **C13.** Inventory event payloads gain `sequence` (see `EventAPI.md` §6).
- `POST /api/v1/topology/reconcile` really resynchronises Neo4j from PostgreSQL. It adds
  the counts `active_devices`, `upserted_nodes`, `tombstoned_nodes`,
  `skipped_newer_nodes` and `watermark_sequence`.
- Network deletion also stays blocked while an autonomous execution is unreleased
  (409 `INVENTORY_DEPENDENCIES_ACTIVE`, as before).
- Campus buildings are upserted in place.
- New audit-only actions: `network.campus_model_asset.uploaded`,
  `network.campus_model_asset.retired`, `network.campus_buildings.upserted`,
  `network.device_groups.upserted`, plus the existing `network.spatial_scene.replaced`.
  All now carry the org id.
- Spatial scene: `PUT` accepts up to 8 MiB. The history responses are unchanged; storage
  uses per-object deltas (`SpatialScene.md`). History `page` is now 1..10000.

## Telemetry and alerts (C12)

- **C12.** `GET /api/v1/telemetry/health` never publishes or evaluates. SLO windows are
  evaluated in the collector workers. The response gains:
  - `slo`: `status` (`ok|degraded|critical|unavailable`), `severity_reason`,
    `alert_active`, `anomaly_reason_flags`, `anomaly_streak`, `evaluated_at`,
    `evaluation_interval_seconds`, `stale`, `window`, `trend`, `thresholds`;
  - `total_records_estimated`: true when `total_records` is a planner estimate or a
    bounded count cached for at least 60 s.
- History, aggregation and device-history pages use `page` 1..10000. Their counts stop at
  10,001 rows: `total_capped: true` means "at least `total`" (show "≥"). Cursor mode is
  unchanged. Naive timestamps and timestamps more than 5 minutes in the future are
  rejected.
- Telemetry SLO alerts are platform-scoped (`payload.alert_scope = "platform"`, no
  workspace, with an `evaluation_window`). Visibility: `Alerts.md`.

## Reports (C5, C26)

Detail: `backend/app/modules/report/README.md`.

- **C5 (BREAKING format).** Downloads send `ETag: "sha256:<hex>"` (was `"<hex>"`).
  `If-None-Match` (strong or weak, lists, `*`) matching the digest returns 304 without
  reading the file. Clients accept both formats and weak validators; the body SHA-256
  remains the authoritative check.
- **C26.** Generation is admitted per organisation. The limit is
  `REPORTS_MAX_BYTES_PER_ORG` (512 MiB, never below one artifact), on top of the global
  reserve. Over quota returns **507 `REPORT_ORG_QUOTA_EXCEEDED`**. The global reserve
  still returns 503 `REPORT_STORAGE_UNAVAILABLE`. Idempotent replays are never refused.
- **C20.** A job that exceeds `REPORTS_MAX_CLAIM_ATTEMPTS` (5) fails with
  `REPORT_ATTEMPTS_EXHAUSTED` and `reason: "attempts_exhausted"`. History `page` is
  1..10000.

## Intents (C3, C18)

Detail: `backend/app/modules/intent/README.md`.

- **C3 (BREAKING for duplicate keys).** `Idempotency-Key` on `POST /intents/validate` is
  unique per workspace (migration 0030; pre-existing duplicates keep the earliest row's
  key, later rows become `<key>~dup~<intent_id>`).
  - Same key, same `network_id` and same normalized intent: 200 with
    `meta.idempotent_replay=true` (and `data.idempotent_replay=true`).
  - Any other reuse: 409 `IDEMPOTENCY_KEY_REUSED`.
  - Keys over 120 characters: 400 `IDEMPOTENCY_KEY_INVALID`.
  Clients generate a fresh key per submission.
- `POST /intents/execute` uses the intent's stored key; the body `idempotency_key` or the
  header must equal it or be omitted, else 409 `INTENT_IDEMPOTENCY_CONFLICT`. Concurrent
  executes: the loser gets 409 `INTENT_ALREADY_EXECUTING`.
- Manual lab execution sends `approval_binding: {plan_hash, binding_digest, run_id}`
  exactly as returned by validate/detail. A stale or missing binding is 409
  `APPROVAL_BINDING_MISMATCH`.
- With `INTENT_REQUIRE_DISTINCT_APPROVER` (default true), the requester cannot execute
  their own intent: 409 `DISTINCT_APPROVER_REQUIRED`.
- **C18.** `reroute_path` and `isolate_vlan` lab actions require the `simulation_id` of a
  completed, passing simulation of the same network. Its limits must respect the server
  policy floors, and its evidence expires 300 s after completion. Otherwise 409
  `SIMULATION_REQUIRED`, `SIMULATION_POLICY_VIOLATION` or `SIMULATION_EVIDENCE_REJECTED`.
- Validate/detail add `approval_binding`, `simulation_action_binding: {intent_id,
  plan_sha256, network_state_sha256}` (copy it into `scenario_config.action_binding`) and
  `validation.simulation_required`. `execution_provenance` adds `simulation_id` and
  `simulation_evidence`.
- The `intent` document must be JSON-native: at most 64 KiB, depth 10, 128 keys per object
  and 1024 items per array, with finite numbers only. Otherwise 422.

## Simulations (C18, C20)

Detail: `backend/app/modules/simulation/README.md`.

- `state` can now be `failed`. After `SIMULATION_MAX_CLAIM_ATTEMPTS` (5) the run ends with
  `failure_reason=attempts_exhausted` and is announced by the documented event
  `simulation.cancelled`.
- `GET /simulations/{id}` adds `execution_policy: {policy_floors, limits_respect_policy}`
  (null for unconfigured runs). The floors are `SIMULATION_POLICY_MAX_LOSS_PCT` (1.0),
  `SIMULATION_POLICY_MAX_LATENCY_MS` (1000) and `SIMULATION_POLICY_MIN_THROUGHPUT_MBPS` (0).
- Starting or resuming a modeled run past `SIMULATION_MAX_ACTIVE_PER_WORKSPACE` (8)
  queued/running runs returns 429 `SIMULATION_QUOTA_EXCEEDED` with `Retry-After: 30`.
- Pausing a paused run or resuming a queued run is a no-op. History `page` is 1..10000.

## Autonomy and model diagnostics (C17, C25, C26)

- **C17.** `Proposal`, `DecisionResponse` and `DecisionSummary` carry
  `confidence: {value: 0..1, method, calibrated, calibration_id | null}`.
  - `Proposal.confidence` is omitted for pre-C17 history.
  - The frozen model reports `method="policy_action_probability"`, `calibrated=false`.
  - Operational settings add `min_confidence` (default 0.95, must be ≥ 0.95) and
    `allow_uncalibrated_confidence` (default false). The latter is honoured only when
    `NANFO_EXPERIMENTAL_LAB_ENABLED` is true and `EXECUTION_MODE=emulation`; the
    configuration response adds `allow_uncalibrated_confidence_honoured`.
  - Refusal reasons: `confidence_missing`, `confidence_uncalibrated`,
    `confidence_below_threshold`, `receiver_confidence_policy_denied`.
- Decisions add `repeat_count` (≥ 1), `last_seen_at` and `projection` (`summary` in
  history lists, `full` for `last_decision`). Summaries return `observation.samples = []`
  with `sample_count`, and no `selected_action`.
- **C25.** `PUT /api/v1/autonomy` to `autonomous` by user A records a pending request and
  returns **202**:
  - `meta` carries `pending_approval: true`, `pending_approval_expires_at` and
    `pending_requested_by_user_id`;
  - `data.pending_approval` is `{requested_by_user_id, mode, expected_revision,
    checkpoint_sha256, approval_expires_at, requested_at, expires_at}`;
  - a *different* user's identical `PUT` applies it; the same user gets 409
    `AUTONOMY_DISTINCT_APPROVER_REQUIRED` (`AUTONOMY_REQUIRE_DISTINCT_APPROVER`, default
    true).
  Clearing an emergency STOP (a `PUT /autonomy` while stopped) needs org role Admin (403
  `AUTONOMY_STOP_CLEAR_REQUIRES_ADMIN`).
  `POST /autonomy/stop` is open to any member holding `read:telemetry` while
  `AUTONOMY_STOP_ALLOW_READ_ONLY` is true (the default). A STOP that cannot latch within
  its lock timeout returns 503 `AUTONOMY_STOP_BUSY` with `Retry-After: 1`. Mode changes,
  STOP, overrides and configuration changes are audited: `autonomy.mode.approval_requested`,
  `autonomy.mode.changed`, `autonomy.stop.latched`, `autonomy.configuration.changed` and
  `autonomy.override.{created,cancel_requested,return_requested}`.
- **C26.** `POST /api/v1/autonomy/model/diagnose` locks per network and bounds concurrency
  per organisation (`AUTONOMY_MODEL_DIAGNOSTICS_MAX_PER_ORG`, default 2, range 1..16).
  Busy returns 429 `MODEL_DIAGNOSTIC_BUSY` (same network) or `MODEL_DIAGNOSTIC_ORG_LIMIT`,
  both with `Retry-After: 5`.
- Unchanged codes: `AUTONOMY_NOT_READY`, `AUTONOMY_REVISION_CONFLICT`,
  `AUTONOMY_UNRESOLVED`.

## Internal, build and deployment contracts (C14–C16, C20–C24)

- **C14.** Delivery, DLQ and retention: `EventAPI.md` §4.
- **C15.** Lab command envelopes carry `hmac_sha256`: HMAC-SHA256 over the canonical
  envelope without that field, using the key at `NANFO_LAB_COMMAND_KEY_FILE`.
  - The key file is at least 32 bytes, mode 0400/0600, and owned by the reading process.
  - The lab rejects missing or invalid MACs and files not owned by the commands-directory
    owner. The backend writer refuses to publish without a key.
  - The frozen lab predates C15 and cannot receive commands.
  - Shared implementation: `emulation/lab_contracts.py`.
- **C16.** Production builds default to the same-origin API (`""`) and derive `ws(s)://`
  from `window.location`. `vite build` refuses a loopback `VITE_API_BASE_URL` unless the
  build process sets `NANFO_ALLOW_LOOPBACK_API_BASE_URL=1`. `npm run dev` proxies `/api`
  and `/ws` to `NANFO_DEV_API_PROXY_TARGET` (default `http://127.0.0.1:8000`).
  `frontend/.env.example` documents both modes.
- **C20.** `reports` and `simulations` gain `claim_attempts` (migration 0030). The
  shared helpers (`app.core.canonical`, `http_cache`, `pagination.PageNumber` 1..10000,
  `correlation`) are the only implementations.
- **C21.** Receiver health receipts are Ed25519 v2 `{body{..., key_id}, signature}`.
  - `key_id` is the first 16 hex characters of SHA-256 over the raw public key.
  - The receiver signs with `NANFO_RECEIVER_HEALTH_PRIVATE_KEY_FILE`; verifiers use
    `NANFO_RECEIVER_HEALTH_PUBLIC_KEY_FILE` (PEM).
  - Key-file rules: an absolute path with no symlinks; parent directories not
    group/other-writable; a regular file with mode 0400 or 0600 and one hard link.
  - Legacy HMAC receipts need `NANFO_RECEIVER_HEALTH_LEGACY_HMAC=true` (frozen runtimes
    only).
- **C22.** `backend/scripts/review_fullstack.py` builds without `VITE_API_BASE_URL` and
  serves `dist` through the real `deploy/nginx.conf`. Failures report the case, the error
  class and a redacted first error line.
- **C23.** The successor lab runs with:
  - `cap_drop: [ALL]` and `cap_add: [NET_ADMIN, NET_RAW, SYS_ADMIN]`;
  - `no-new-privileges`, a read-only root and `nosuid,nodev` tmpfs.
  The privileged frozen image runs only through `deploy/compose.lab.frozen.yaml` with
  `NANFO_LAB_FROZEN=1`. See `deploy/README.md`.
- **C24.** Redis ACL user `nanfo` (`+@all -@dangerous +info +client|setname +client|id`,
  all keys and channels); `REDIS_USERNAME` is carried in every Redis URL.
  - The deployment disables `default` and uses `nanfo-admin` for rotation.
  - The development compose keeps `default` enabled with the same restrictions, so older
    `.env` files keep working.
  - Secrets are staged into `runtime_secrets_api` (with `jwt_secret`) and
    `runtime_secrets_worker` (without it).

## New settings

The new settings are typed, bounded where numeric, and documented in
`backend/.env.example`. The ones clients and operators most often need:

- identity: `AUTH_REFRESH_GRACE_SECONDS`, `AUTH_SESSION_IDLE_TIMEOUT_SECONDS`,
  `JWT_PREVIOUS_SECRET_KEYS`, `NANFO_SERVICE_ROLE`;
- request limits: `API_MAX_BODY_BYTES`, `API_MAX_ASSET_UPLOAD_BYTES`,
  `API_MAX_SPATIAL_SCENE_BYTES`;
- WebSocket: `WS_MAX_CONNECTIONS_PER_USER`, `WS_SUBSCRIBE_TIMEOUT_SECONDS`,
  `WS_AUTH_CACHE_SECONDS`, `WS_MAX_FRAME_BYTES`;
- events: `EVENT_MAX_DELIVERIES`, `EVENT_CONSUMER_NAME`, `EVENT_CONSUMER_CONCURRENCY`,
  `EVENT_PUBLISH_MAX_MEMORY_RATIO`;
- workflows: `INTENT_REQUIRE_DISTINCT_APPROVER`, `SIMULATION_*` (floors, quota, claim
  attempts), `REPORTS_MAX_BYTES_PER_ORG`, `REPORTS_MAX_CLAIM_ATTEMPTS`;
- retention: `*_OUTBOX_RETENTION_DAYS`, `ALERT_OBSERVATION_*`;
- autonomy: `AUTONOMY_REQUIRE_DISTINCT_APPROVER`, `AUTONOMY_STOP_ALLOW_READ_ONLY`,
  `AUTONOMY_DECISION_RETENTION_DAYS`, `AUTONOMY_MODEL_DIAGNOSTICS_MAX_PER_ORG`;
- other: `REDIS_USERNAME`, `WATCHDOG_*`.

`NETWORK_ASSET_*` are read from the process environment only: `backend/.env` forbids
unknown keys, so set them in Compose or the environment.
