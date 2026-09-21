# Alerts API

Owner: Alert module. ADR-019 lifecycle and ADR-026 query narrowing apply.
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
| `search` | Optional trimmed case-insensitive substring/SQL ILIKE pattern over key, source, correlation UUID, serialized payload |
| `limit` | Integer 1–500; default 200 |
| `workspace_id` | Optional UUID; current active workspace/membership and org claim checked; must match workspace claim if present |
| `network_id` | Optional UUID; current Network service access checked; must belong to selected/claimed workspace if present |

All scope and content predicates run before `LIMIT` on Alert-owned data. Selection
only narrows the existing authorized scopes. A network selection excludes
workspace-only/org-only records; workspace selection excludes org-only records and
includes authorized network records within it, including legacy network-only and
nested payload scopes. Omitting both preserves existing all-authorized-scope
semantics. Final per-row owner rechecks remain in place for authority changes.
No cross-module SQL joins or schema migration.

Rows sort by `updated_at DESC, created_at DESC, alert_id DESC`.
Data remains `{items: AlertRecordResponse[], total: number, status_counts: object}`.
**Both counts describe only returned bounded matches**, not all matches or global
incidents. There is no page/offset/cursor contract. Invalid UUIDs or limit return
422; unauthorized selection returns 403; missing/deleted selected resources 404.
Error responses retain the canonical envelope.

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
