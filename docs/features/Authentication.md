# Feature PRD: User Authentication & RBAC

## 1. Purpose
To provide secure, stateless identity verification and strict Role-Based Access Control (RBAC) across the NANFO platform[cite: 1]. This ensures that only authorized administrators and specialized engineers can execute high-impact network configurations.

## 2. Requirements
* Use signed JWTs with Redis-backed revocable session families. JWT verification
  alone does not authorize a request.
* Support token lifecycle management (issue, refresh, revoke/logout).
* Enforce fine-grained RBAC for different user personas (e.g., Enterprise NOC Engineers, SDN & Wireless Engineers, Tertiary Users)[cite: 1].
* All authentication events must append records to the immutable Audit Log[cite: 1].

## 3. API Endpoints
All endpoints must adhere to the standard REST envelope defined in `docs/api/API_STANDARD.md`.
* `POST /api/v1/auth/login` - Authenticate user and issue JWT[cite: 1].
* `POST /api/v1/auth/logout` - Invalidate current session/token[cite: 1].
* `POST /api/v1/auth/refresh` - Issue a new JWT using a valid refresh token[cite: 1].
* `GET /api/v1/auth/me` - Retrieve current user profile and active permissions[cite: 1].

## 4. Database Schema Requirements
This feature strictly owns the following tables within the PostgreSQL relational store[cite: 1]:
* `users`: Stores UUID, email, hashed password, and status.
* `roles`: Defines system roles (e.g., Admin, Read-Only, Operator).
* `permissions`: Defines granular capabilities (e.g., `execute:rollback`, `write:config`).
* `user_roles`: Mapping table for user-to-role relationships[cite: 1].
* `audit_logs`: Immutable, append-only table for recording login successes, failures, and token issuances[cite: 1].

## 5. Security & Validation (Edge Cases)
* **Passwords:** Must never be logged or returned in any API response. bcrypt considers only
  72 bytes, so passwords over 72 UTF-8 bytes are refused when hashing and always fail login
  with the generic 401 (ADR-028 C11). Existing accounts with longer passwords need a reset.
* **Brute Force:** Login is throttled in fixed windows of `RATE_LIMIT_LOGIN_WINDOW_SECONDS`
  (60) with `RATE_LIMIT_LOGIN_MAX_ATTEMPTS` (5), returning 429 (ADR-028 C11):
  - a per-IP bucket counts every attempt;
  - a per-email bucket, keyed by SHA-256 of the normalized address, counts failures only
    and is cleared on success;
  - only the first throttled attempt per window is audited.
* **Validation:** Reject malformed email formats or weak passwords with a `422 Unprocessable Entity` before hitting the Service Layer.
* **Token Expiration:** Access tokens should have a short lifespan (e.g., 15 minutes); refresh tokens should handle long-lived sessions.

## 6. Acceptance Criteria
- [ ] Submitting valid credentials to `/login` returns a 200 OK with a valid JWT and standard meta envelope.
- [ ] Submitting invalid credentials returns a `401 Unauthorized` without specifying whether the email or password was wrong.
- [ ] Accessing a protected route without a JWT returns a `401 Unauthorized`.
- [ ] Accessing a protected route with insufficient RBAC permissions returns a `403 Forbidden`.
- [ ] Successful and failed authentication attempts are successfully written to the `audit_logs` table.

## 7. Testing Requirements
* Refer to `.agents/rules/testing.md` for standards.
* Write isolated unit tests for the JWT encoding/decoding utility functions.
* Write integration tests for the FastAPI router endpoints using an injected test database.

## 8. JWT Claim Baseline

All JWTs issued by `POST /api/v1/auth/login` and `POST /api/v1/auth/refresh` must contain the following claims.

### 8.1 Required Claims

| Claim | Type | Description |
|:--|:--|:--|
| `sub` | UUID (string) | Subject: the authenticated `user_id`. Primary identity reference. |
| `email` | string | User email address. Included for display and audit purposes; never used for authorization decisions. |
| `roles` | string[] | Array of role names assigned to the user (e.g., `["Admin", "Operator"]`). RBAC middleware uses this array to evaluate route-level permissions. |
| `permissions` | string[] | Array of granular permission strings (e.g., `["write:config", "execute:rollback"]`). Used for fine-grained capability checks within services. |
| `iat` | Unix timestamp | Issued-at time. Set by the token issuer. |
| `exp` | Unix timestamp | Expiry time. Access tokens: 15 minutes from `iat`. |
| `jti` | UUID (string) | JWT ID: a unique identifier for this specific token instance. Used for token revocation lookup. |
| `iss` | string | Always `"nanfo-api"` (ADR-028 C10). Required on decode. |
| `aud` | string | Always `"nanfo"` (ADR-028 C10). Required on decode. |

Decoding requires `exp`, `iat`, `sub`, `jti`, `iss` and `aud`, allows 30 s leeway and
accepts only the configured HS256/384/512 algorithm (PyJWT). Tokens issued before
ADR-028 lack `iss`/`aud` and are rejected (**BREAKING for pre-deploy tokens**).
Verification also accepts the verify-only `JWT_PREVIOUS_SECRET_KEYS` during a key
rotation (C19); signing always uses `JWT_SECRET_KEY`.

### 8.2 Optional Claims

| Claim | Type | Condition | Description |
|:--|:--|:--|:--|
| `org_id` | UUID (string) | Present if user has an active organization context | The organization the token is scoped to. Absent for users not yet assigned to an organization. |
| `workspace_id` | UUID (string) | Present only if the client explicitly selects a workspace at login | The active workspace context. Downstream services use this to scope resource visibility. |

### 8.3 Tenant and Org/Workspace Scoping Behaviour

- **Single-org per token:** A token may carry at most one `org_id`. A user who is a member of multiple organizations must obtain a new token (via `/api/v1/auth/login` with an explicit `org_id` parameter, or via a future `/api/v1/auth/switch-org` endpoint) to switch organization context. Multi-org membership is supported at the data layer; the token scope is always single-org.
- **Workspace scoping:** `workspace_id` is optional in the token. If absent, the client must provide `workspace_id` as a query parameter where required (e.g., `GET /api/v1/networks?workspace_id=<uuid>`). If present, downstream services may use it to pre-filter results without requiring an explicit query parameter.
- **RBAC evaluation order:** The RBAC middleware evaluates `roles` first (coarse-grained route access), then `permissions` (fine-grained capability access). Both arrays must be present in the token; an empty `permissions` array is valid for read-only roles.
- **Token revocation:** Access and refresh tokens require `sid` (session UUID) and
  `token_type` (`access` or `refresh`). Logout deletes the Redis session family;
  all its tokens become invalid. ADR-028 removed the access-token deny-list lookup,
  which had no writer. Deactivation, password change and role downgrade revoke every
  session of the user through a per-user session index (C9). Sessionless legacy tokens
  require a fresh login.
- **Refresh rotation:** Refresh returns a full TokenPair (`access_token`,
  `refresh_token`, `token_type`, `expires_in`). Refresh tokens are single-use.
  Re-presenting a token rotated at most 20 s ago returns the *same* pair while that pair
  is still the newest in its family (C9 retry grace); any other replay revokes the family
  (`auth.token.reuse_detected`). Sessions expire after 12 h without a refresh
  (`AUTH_SESSION_IDLE_TIMEOUT_SECONDS`). Absolute session expiry is not extended by
  rotation.
- **Current authorization:** Every authenticated request reloads active identity,
  roles, and permissions; JWT role snapshots cannot preserve removed privileges.
- **Browser ownership:** Sessions are tab-local (`sessionStorage`); legacy shared
  local-storage credentials are discarded. Logout clears query/realtime/context
  state, and attempts refresh before revocation if the access token has expired.
- **Availability:** Redis/session failures deny access with 503 `DEPENDENCY_UNAVAILABLE`
  and `Retry-After`, never 401 (ADR-028 C2). Clients keep the session, retry and must not
  silently substitute local logout for confirmed backend revocation.

### 8.4 Claims That Must Never Appear in a JWT

- `hashed_password` or any credential derivative.
- Raw internal database row IDs other than `user_id`.
- Any data classified as sensitive PII beyond `email`.

## 9. ADR-026 capability and audit contract

| Global role | Capabilities |
|:--|:--|
| Admin | All seeded permissions |
| Operator | read:topology, read:telemetry, write:config, execute:rollback |
| Read-Only | read:topology, read:telemetry |

Current organization membership further restricts writes. Global Operator is not
platform Admin; organization administration still requires local Admin membership.

`GET /api/v1/audit/logs` retains global Admin authorization, current organization
membership and narrowing claim checks. Query fields: org_id, actor_id,
resource_type, page 1..10000 (ADR-028 `PageNumber`), page_size1..200 (default50),
optional search<=200 characters and `scope` (ADR-028 C7):

- `scope=org` (default) requires `org_id` or an org-scoped token, plus current membership
  of that organization.
- `scope=platform` returns the unscoped (`org_id IS NULL`) platform events, such as
  authentication. It is restricted to a global Admin with an unscoped token: combining it
  with `org_id` is 422, and an org-scoped token is 403.
- A workspace-scoped token is always denied (403), because audit rows carry no workspace
  attribution.

Search (ADR-028): a UUID term matches `correlation_id`, `resource_id`, `actor_id`,
`event_id` or `log_id` exactly; UUID columns are never cast to text. Any other term is a
case-insensitive literal substring of `event_type` or `resource_type`, or an exact match
on the correlation UUID that an opaque request id maps to. Whitespace-only search is
ignored. Search and existing filters apply together before counting/pagination, within
the selected scope. Ordering is timestamp descending then log_id descending. Success data
is `{items,total,page,page_size,scope}` with existing actor/resource/metadata fields.

Identity's public `append_audit_log` accepts optional event_id. Organization uses
this boundary to atomically commit lifecycle audits with its mutations, without a
migration. Direct append and consumer delivery share event identity. Historical
unscoped/misattributed rows remain immutable; replay never silently corrects them.
Any future historical repair requires verified owner scope and an explicit linked,
append-only correction operation. No automated historical recovery is introduced.
