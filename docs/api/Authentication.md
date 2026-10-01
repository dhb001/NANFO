# Authentication API

## Purpose
Define authentication and authorization flow contracts.

## Scope
- Login, refresh, logout, and profile endpoints
- Token lifecycle and expiry policy
- RBAC permission model expectations

## Dependency
- Feature-level requirements are defined in `docs/features/Authentication.md`.

## Session Contract

Login and refresh return the canonical envelope containing a TokenPair:
`access_token`, `refresh_token`, `token_type="bearer"`, `expires_in` (seconds).
The refresh request remains `{ "refresh_token": "..." }`. Both tokens must be
replaced atomically. Logout uses the current access token and revokes its entire
session family. Tokens require explicit token type and session ID. Old tokens
without a live Redis family are rejected. Replay of a consumed refresh token
revokes that family. See `docs/project/FoundationSecurity-Step1-Step2.md`.

## ADR-028 changes (C6, C7, C9, C10, C11, C19)

- **JWT claims (C10, BREAKING for pre-deploy tokens).** Every token carries
  `iss="nanfo-api"` and `aud="nanfo"`. Decoding requires `exp`, `iat`, `sub`, `jti`, `iss`
  and `aud`, allows 30 s leeway and accepts only the configured `JWT_ALGORITHM` (HS256,
  HS384 or HS512). Tokens issued before this change are rejected (401), so users log in
  again. The library is PyJWT; python-jose was removed. A service with
  `NANFO_SERVICE_ROLE=worker` does not need `JWT_SECRET_KEY`.
- **Key rotation (C19).** Tokens are always signed with `JWT_SECRET_KEY` and verified
  against it, then against the comma-separated, verify-only `JWT_PREVIOUS_SECRET_KEYS`.
  Operator procedure: `deploy/OPERATIONS.md` → Credential Rotation.
- **Refresh retry grace (C9).** Re-presenting a refresh token that was rotated at most
  20 s ago (`AUTH_REFRESH_GRACE_SECONDS`) returns the *same* issued pair, while that pair
  is still the newest in its session family. This makes a retry after a lost response,
  or a second tab, safe. The pair is kept only in sealed form. Any other reuse revokes the
  family and is audited as `auth.token.reuse_detected`. Rejected refreshes are audited as
  `auth.token.refresh_failed`, at most once per reason, client and session per window.
- **Session lifetime (C9).** A session expires after 12 h without a refresh
  (`AUTH_SESSION_IDLE_TIMEOUT_SECONDS`). The timeout slides on each refresh and never
  extends the absolute refresh lifetime. Deactivation, password change and role downgrade
  revoke every session of the user through a per-user session index
  (`IdentityAccountService`, or the CLI `backend/scripts/revoke_user_sessions.py`). No
  REST endpoint was added for these operations.
- **Availability (C2).** A Redis/session-store outage returns 503
  `DEPENDENCY_UNAVAILABLE` with `Retry-After`, not 401. Clients keep the session and retry.
  The unused access-token deny-list lookup was removed.
- **Login throttling (C11).** Limits come from `RATE_LIMIT_LOGIN_MAX_ATTEMPTS` (5) and
  `RATE_LIMIT_LOGIN_WINDOW_SECONDS` (60):
  - the per-IP bucket counts every attempt;
  - the per-email bucket is keyed by a SHA-256 of the normalized address, counts failures
    and is cleared on success;
  - a throttled attempt returns 429, and only the first per window is audited
    (`auth.user.login_failed`, reason `rate_limited`, `limited_by` `ip` or `email`).
  The raw email is never logged or used as a key.
- **Password and input bounds (C11).** bcrypt considers only 72 bytes, so passwords over
  72 UTF-8 bytes can never match: login returns the generic 401, and hashing refuses them.
  Existing accounts with longer passwords need a reset. `refresh_token` is at most 4096
  characters and `email` at most 254.
- **Organizations (C6).** `OrgResponse.caller_role` (`Admin` | `Operator` | `Read-Only`)
  is present on org list, get, create and update. `GET /api/v1/organizations/{org_id}`
  returns the same 404 whether the organization is absent or the caller is not a member.
- **Audit (C7).** `GET /api/v1/audit/logs?scope=platform` (global Admin, unscoped token)
  returns platform events with no organization, such as authentication. The rules for
  `org_id`, workspace tokens, `page` and search are in `docs/features/Authentication.md` §9.
- **Audit-only actions.** New actions, not bus events: `auth.token.refresh_failed`,
  `auth.token.reuse_detected`, `auth.user.sessions_revoked`, `auth.user.deactivated`,
  `auth.user.password_changed` and `auth.user.roles_changed`, with resource types
  `auth_session` and `user`.
