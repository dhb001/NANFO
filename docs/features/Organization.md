# Feature PRD: Organization & Workspace Management

## 1. Purpose
To provide multi-tenant organizational scoping for the NANFO platform. Every network resource (networks, devices, topologies) must be owned by a workspace, which belongs to an organization. This enforces strict data isolation between tenants and enables role-based access scoping at the organization boundary.

## 2. Requirements
* Create and manage organizations, identified by a unique URL-safe slug.
* Create and manage workspaces within organizations.
* Manage organization membership: assign users to organizations with an explicit organizational role.
* Enforce that no network resource may be created without a valid, active workspace reference.
* All organization and workspace lifecycle events must append records to the immutable Audit Log.
* Validate workspace existence and active status via the Organization Service before accepting network resource creation in the Network module.

## 3. API Endpoints
All endpoints must adhere to the standard REST envelope defined in `docs/api/API_STANDARD.md`.

### 3.1 Organizations
* `POST /api/v1/organizations` — Create a new organization.
* `GET /api/v1/organizations` — List organizations accessible to the authenticated user.
* `GET /api/v1/organizations/{org_id}` — Retrieve a single organization.
* `PATCH /api/v1/organizations/{org_id}` — Update organization name or metadata.
* `DELETE /api/v1/organizations/{org_id}` — Soft-delete an organization (204 No Content).

### 3.2 Workspaces
* `POST /api/v1/organizations/{org_id}/workspaces` — Create a workspace within an organization.
* `GET /api/v1/organizations/{org_id}/workspaces` — List workspaces within an organization.
* `GET /api/v1/organizations/{org_id}/workspaces/{workspace_id}` — Retrieve a single workspace.
* `PATCH /api/v1/organizations/{org_id}/workspaces/{workspace_id}` — Update workspace metadata.
* `DELETE /api/v1/organizations/{org_id}/workspaces/{workspace_id}` — Soft-delete a workspace (204 No Content).

### 3.3 Membership
* `POST /api/v1/organizations/{org_id}/members` — Add a user to an organization with an org-level role.
* `GET /api/v1/organizations/{org_id}/members` — List organization members.
* `DELETE /api/v1/organizations/{org_id}/members/{user_id}` — Remove a user from the organization.

> Request and response schemas must follow the `{ "success", "data", "meta", "errors" }` envelope per `docs/api/API_STANDARD.md` §2. HTTP codes per `API_STANDARD.md` §3: POST→201, GET→200, PATCH→200, DELETE→204.

## 4. Database Schema & Ownership
This feature strictly owns the following tables in the PostgreSQL relational store (per `docs/.agents/rules/database.md` §1). No other module may query these tables directly; cross-module access occurs exclusively via domain events or API contracts (ADR-004).

| Table | Minimum Columns | Notes |
|:--|:--|:--|
| `organizations` | `org_id UUID PK`, `name TEXT NOT NULL`, `slug TEXT UNIQUE NOT NULL`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ`, `deleted_at TIMESTAMPTZ` | Soft-delete via `deleted_at` |
| `workspaces` | `workspace_id UUID PK`, `org_id UUID NOT NULL` (FK within module), `name TEXT NOT NULL`, `description TEXT`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ`, `deleted_at TIMESTAMPTZ` | `org_id` is an intra-module FK; active status = `deleted_at IS NULL` |
| `org_members` | `org_id UUID NOT NULL`, `user_id UUID NOT NULL` (logical reference to Identity module), `org_role TEXT NOT NULL`, `created_at TIMESTAMPTZ`, `deleted_at TIMESTAMPTZ`, `PRIMARY KEY (org_id, user_id)` | `user_id` is a stored reference; no SQL join to Identity module's `users` table |

> **Cross-module reference rule (ADR-004):** `user_id` in `org_members` is a stored UUID reference to the Identity module. The Organization Service must validate `user_id` via an Identity Service API call before persisting membership, not via a SQL join.

> All schema changes require versioned Alembic migrations per `.agents/rules/database.md` §2.

## 5. Event Contracts
All events must follow the mandatory envelope defined in `docs/api/EventAPI.md` §2 (fields: `event_id`, `event_type`, `timestamp`, `source`, `correlation_id`, `version`, `payload`).

| Event Type | Producer | Consumer(s) | Payload Fields |
|:--|:--|:--|:--|
| `org.organization.created` | Organization module | Audit Log Writer | `org_id`, `name`, `slug`, `actor_id` |
| `org.organization.updated` | Organization module | Audit Log Writer | `org_id`, `changed_fields: {}`, `actor_id` |
| `org.organization.deleted` | Organization module | Audit Log Writer | `org_id`, `actor_id` |
| `org.workspace.created` | Organization module | Audit Log Writer, Network module (validates workspace references) | `workspace_id`, `org_id`, `name`, `actor_id` |
| `org.workspace.updated` | Organization module | Audit Log Writer | `workspace_id`, `org_id`, `changed_fields: {}`, `actor_id` |
| `org.workspace.deleted` | Organization module | Audit Log Writer, Network module (must mark networks in deleted workspace as suspended) | `workspace_id`, `org_id`, `actor_id` |
| `org.member.added` | Organization module | Audit Log Writer | `org_id`, `user_id`, `org_role`, `actor_id`, `restored: boolean` |
| `org.member.removed` | Organization module | Audit Log Writer | `org_id`, `user_id`, `actor_id` |

> Event type names follow `module.entity.action` per `docs/api/EventAPI.md` §1.
> Consumer idempotency on `event_id` is mandatory per `docs/api/EventAPI.md` §4.
> These events are published to the `stream:org` Redis Stream.

## 6. Risks

### Authorization Baseline

Organization/workspace/member administration requires global `write:config` and
current organization `Admin` membership. Tenant-resource writes additionally
require current org `Admin` or `Operator` membership; global privileges do not
override an org Read-Only role. Reads require active membership and active parent
organization/workspace. Optional token claims restrict, never expand, that scope.


- **Descendant deletion (ADR-026):** Organization deletion rejects active workspaces (`409 ORG_HAS_WORKSPACES`). Workspace deletion asks NetworkService for active inventory and rejects it (`409 WORKSPACE_HAS_NETWORKS`). Remove descendants explicitly first; immutable history is retained. This does not rely on best-effort event delivery to suspend descendants.
- **Cross-org data leakage:** API routes must enforce that the authenticated user's `org_id` (from JWT) matches the `org_id` in the path parameter for all org-scoped endpoints. Missing this check exposes multi-tenant data.
- **`user_id` reference integrity:** Since `org_members.user_id` is a logical reference without a SQL FK to Identity's `users` table, it is possible to add a non-existent user. The Organization Service must validate via Identity API before inserting a membership row.
- **Slug uniqueness enforcement at application layer:** `slug UNIQUE` is enforced in PostgreSQL, but slug normalisation (lowercase, hyphen-only) must be validated at the Pydantic layer before the DB write to surface user-friendly errors via 422 rather than a raw DB constraint violation.

## 7. Acceptance Criteria
- [ ] `POST /api/v1/organizations` creates an organization and returns 201 with the canonical envelope.
- [ ] A duplicate `slug` returns 409 Conflict with error code `ORG_SLUG_CONFLICT`.
- [ ] `POST /api/v1/organizations/{org_id}/workspaces` creates a workspace scoped to the org and returns 201.
- [ ] `POST /api/v1/networks` with a `workspace_id` that belongs to a soft-deleted workspace returns 404 with error code `WORKSPACE_NOT_FOUND`.
- [ ] Organization creation emits `org.organization.created` and the Audit Log records the event.
- [ ] Workspace deletion emits `org.workspace.deleted` and the Network module receives and processes the event.
- [ ] A user not in the organization cannot access `GET /api/v1/organizations/{org_id}` — returns the same 404 as an absent organization (ADR-028 C6; was 403). Internal membership checks that guard other resources still answer a uniform 403.
- [ ] Org membership add validates `user_id` via Identity API before persisting.

## 8. Testing Requirements
* Refer to `.agents/rules/testing.md` for standards.
* Write unit tests for slug normalisation and uniqueness validation.
* Write integration tests for all CRUD endpoints using an injected test database.
* Write integration test verifying that `workspace_id` validation in the Network module correctly rejects soft-deleted workspaces.
* Write event contract tests asserting that `org.organization.created` and `org.workspace.created` payloads match the envelope defined in `docs/api/EventAPI.md` §2.

## 9. ADR-026 repair contract

- Organization/workspace names are trimmed, nonblank, maximum255 characters;
  workspace descriptions maximum4000. Slugs normalize lowercase/whitespace and
  require3..63 alphanumeric/hyphen characters, no leading/trailing hyphen.
- Deleted slugs remain reserved. Pre-existing and concurrent conflicts return
  `409 ORG_SLUG_CONFLICT`.
- PATCH requires at least one supplied field. Name cannot be null. Workspace
  description omission preserves its value; explicit null clears it.
- Organization/workspace/member public lists accept page>=1 and page_size1..200;
  existing `{items,total}` data envelope remains. Rows order by created_at then UUID.
- Roles are exactly `Admin`, `Operator`, `Read-Only`. Re-adding a removed member
  restores the original row/created_at with the requested role and emits
  `org.member.added` with `restored=true`; active duplicates return409.
- Tenant mutations acquire the organization row lock before rechecking current
  membership. Concurrent restores serialize; a completed revocation denies a
  waiting actor. Removing the last usable Admin returns `409 ORG_LAST_ADMIN`;
  another Admin must have an active Identity account and global write:config.
- Every lifecycle mutation appends through Identity's public audit boundary in
  the same transaction. Redis publication follows commit with the same event_id;
  consumer replay is deduplicated by the existing unique audit event_id. Audit
  failure rolls back the mutation; publication failure retains the durable audit.
- Membership audit actor is actor_id and resource is affected user_id. Workspace
  resource is workspace_id. Old audit evidence is never updated on replay.

## 10. ADR-028 contract changes (C6)

- `OrgResponse.caller_role` (`Admin` | `Operator` | `Read-Only`) reports the caller's
  current org role on list, get, create and update. The list gets it from one joined
  query.
- `GET /api/v1/organizations/{org_id}` returns the same 404 ("Organization not found.")
  whether the organization is absent, deleted, or the caller is not a member. Internal
  checks through `OrgService.require_membership` answer a uniform 403. The slug-conflict
  message no longer echoes the slug.
- Every org lock is taken only after a plain-read authorization check passes, and
  authority is re-checked under the lock.
- List `page` is 1..10000 (shared `PageNumber`).
- Workspace deletion asks the Network owner's `has_active_networks` existence probe
  instead of listing networks. The network module is imported lazily through a
  `WorkspaceInventory` port, which removes the import cycle.
