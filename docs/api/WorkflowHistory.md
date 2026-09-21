# Durable simulation and intent history — ADR026

`GET /api/v1/simulations` and `GET /api/v1/intents` require `read:topology`
and current active workspace membership. Organization/workspace token claims narrow
access. Scope is authorized through the owning services before counting/paging.

| Query | Contract |
|---|---|
| `workspace_id` | Required UUID |
| `network_id` | Optional UUID; NetworkService verifies active network in that workspace |
| `page` | Integer ≥1; default1 |
| `page_size` | Integer1–200; default20 |

Canonical success envelope: `success=true`, `data={items,total,page,page_size}`,
`meta` as API_STANDARD, `errors=null`. Invalid UUIDs/page bounds return422;
unauthenticated401; denied membership/capability/claim scope403; missing/deleted
owner scope404. Owner service conventions govern exact denial messages.

Simulation item:
```json
{
  "simulation_id": "UUID", "network_id": "UUID", "workspace_id": "UUID",
  "scenario_name": "Configured baseline", "status": "queued",
  "created_at": "2026-09-20T10:00:00Z", "updated_at": "2026-09-20T10:00:00Z"
}
```

Intent item:
```json
{
  "intent_id": "UUID", "network_id": null, "workspace_id": "UUID",
  "action": "reroute_path", "status": "validated",
  "created_at": "2026-09-20T10:00:00Z", "updated_at": "2026-09-20T10:00:00Z"
}
```

Intent `network_id` and `action` may be null. `action` is the first120 characters
of the existing payload action; full payload/evidence remain on detail. Lifecycle
status is the existing persisted value, not a new summary-only enumeration.
Simulation output/checkpoint and intent execution provenance are not loaded by lists.

Order is `created_at DESC, simulation_id DESC` / `created_at DESC, intent_id DESC`.
Each response counts and selects from one PostgreSQL statement/snapshot with identical
scope predicates. Empty/out-of-range pages retain the authoritative count. Offset
pages are not a cross-request snapshot: new inserts may move page boundaries.
Workspace-only history includes retained records for historical networks; selecting
an explicit network requires its current active owner access.

UI pages offer previous/next and explicit refresh; selections live in `simulation_id`,
`baseline_id`, and `intent_id` URL query parameters. Tenant changes clear locally bound
selection. Deep links cannot authorize actions: existing detail and explicit current
approval/lifecycle controls remain required. History can recover server-created IDs
after a lost response but does not imply a failed request had no effect.
