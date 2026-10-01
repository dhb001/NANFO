# Alerts API

Owner: Alert module. ADR-019 lifecycle, ADR-026 query narrowing and ADR-028 counts,
tenancy columns and platform-scoped alerts apply.
Every response uses `{success,data,meta,errors}` as defined in `API_STANDARD.md`.

## GET `/api/v1/alerts`

Requires `read:telemetry` and current owning-service organization/workspace/network
access. Optional JWT org/workspace claims narrow authority, never grant membership.

| Query | Contract |
| --- | --- |
| `status` | Optional `active`, `acknowledged`, `resolved`; invalid status returns 400 |
| `severity` | Optional exact normalized severity |
| `source` | Optional exact normalized source |
| `correlation_id` | Optional UUID |
| `search` | Optional, at most 200 characters (422 above). Trimmed, literal case-insensitive substring (`%`, `_`, `\` escaped) over key, source, correlation UUID and the payload text fields `message`, `title`, `metric`, `device_id`, `peer_host`, `severity_reason`, `runbook_playbook`, `resolution_reason`, `measurement_method`. Never the whole serialized payload (ADR-028). |
| `limit` | Integer 1–500; default 200 |
| `workspace_id` | Optional UUID; current active workspace/membership and org claim checked; must match workspace claim if present |
| `network_id` | Optional UUID; current Network service access checked; must belong to selected/claimed workspace if present |

All scope and content predicates run before `LIMIT` on Alert-owned data. Selection
only narrows the existing authorized scopes. A network selection excludes
workspace-only/org-only records; workspace selection excludes org-only records and
includes authorized network records within it, including legacy network-only and
nested payload scopes. Omitting both preserves existing all-authorized-scope
semantics. Final owner rechecks remain in place for authority changes; ADR-028 batches
them per request instead of per row. No cross-module SQL joins.

Rows sort by `updated_at DESC, alert_id DESC` (ADR-028: the index order; `created_at` is no
longer a tie-breaker).
Data remains `{items: AlertRecordResponse[], total: number, status_counts: object}`.
ADR-028 changes the count semantics: `total` and `status_counts` count **every**
authorized match of the filters (an exact SQL aggregate), while `items` stays bounded by
`limit`. Rows removed by the final recheck are subtracted, and no count is ever below the
number of returned items. There is no page/offset/cursor contract. Invalid UUIDs or limit
return 422; unauthorized selection returns 403; missing/deleted selected resources 404.
Error responses retain the canonical envelope.

Tenancy is read from Alert-owned `org_id`/`workspace_id`/`network_id` columns (migration
0030, backfilled from the payload). The historical JSON scope predicate applies only to
rows whose three columns are all NULL.

Example: `/api/v1/alerts?workspace_id=UUID&network_id=UUID&status=active&search=latency&limit=200`.

## Existing detail, history and actions

- `GET /api/v1/alerts/{id}` → `AlertRecordResponse`, `read:telemetry`.
- `GET /api/v1/alerts/{id}/history` → `{alert_id,items,total}` in chronological
  immutable lifecycle order, `read:telemetry`. No pagination query is defined.
- `POST /api/v1/alerts/{id}/ack` and `/resolve` → `AlertActionResponse`,
  `write:config` and current writable membership. Replays remain idempotent;
  acknowledgement of a resolved incident returns 409.

These routes authorize the record's actual scope and token claims. Their payloads,
events and authorization semantics are unchanged. Complete field/evidence and
durable delivery definitions: `backend/app/modules/alert/README.md`.

## Platform-scoped alerts (ADR-028)

Telemetry runtime-adapter SLO alerts carry top-level `alert_scope: "platform"` and no
workspace or network (C12):

- They are never visible to tenants, not even to members of an organization that the
  payload may name.
- A global Admin (live Identity role `Admin`) using a token without org or workspace
  claims can list them (only when no `workspace_id`/`network_id` selection narrows the
  list) and read their detail and history.
- They are read-only: their lifecycle belongs to the SLO evaluator, so acknowledge and
  resolve return 403 for every caller.
- The payload, including `evaluation_window`, passes through unchanged. Report sources
  never include these alerts.
