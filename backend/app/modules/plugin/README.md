# Metadata-Only Registry (ADR019)

No package is fetched, loaded or executed. Signer/signature syntax, dependency
declarations and permission allowlists are metadata admission checks, not proof
of cryptographic authenticity, installed dependencies or sandbox enforcement.

## Response Contract

Existing record fields remain. Every list item and install/enable/disable action
has these exact fields (also declared in `schemas.py`):

- `registry_only: true`
- `execution_supported: false`
- `lifecycle_semantics: "registry_flags_only"`
- `signature_status: "declared_unverified"`
- `dependency_status: "declared_unverified"`
- `sandbox_status: "not_executed"`
- `permissions_status: "declared_unverified"`
- `status: "installed" | "enabled" | "disabled" | "failed" | "uninstalled"`
- `uninstalled_at: ISO8601 timestamp | null`

List data also has the first three capability fields, plus existing `items`,
`total` and `status_counts` (including `uninstalled`). Historical stored claims
are masked on serialization, not rewritten. Manifest declarations remain intact.
Existing lifecycle event payload status fields use the same truthful values.

Install replay requires the same canonical complete JSON manifest, including
signer, signature/digest metadata, dependencies and permissions. Object key order
does not matter; array order and JSON types do. Top-level strings are stripped
and plugin_key is lowercased. Changed version returns `PLUGIN_VERSION_CONFLICT`
(409); other changes return `PLUGIN_MANIFEST_CONFLICT` (409).

Enable and disable only change registry flags. DELETE `/api/v1/plugins/{id}`
returns 204 with no body, requires current global Admin + `write:config` and the
same active org/workspace membership checks as other mutations. Unknown ID is
404; repeat uninstall is 204 without another audit write. Default lists exclude
uninstalled records; `?status=uninstalled` returns retained records. Enable/disable
of uninstalled records returns `PLUGIN_UNINSTALLED` (409).

Plugin-owned migration0019 after Alert-owned0018 adds nullable `uninstalled_at`.
Keep the existing global unique plugin_key, not a partial unique index. Identical
explicit reinstall restores the same ID to installed/disabled flag false and
clears uninstalled_at, preserving installed_at and immutable audit history.
Concurrent lifecycle mutations serialize using database locks; install also locks
the key before creation. No lifecycle epoch or executable runtime is introduced.

Uninstall and its audit append commit in one transaction. Identity owns the public
`append_audit_log` service and its repository. Audit-only record type
`plugin.registry.removed` carries resource_type `plugin`, resource ID, actor,
correlation and metadata `{registry_only: true, previous_status, status:
"uninstalled"}`. It is not a domain event; no `plugin.uninstalled` event is emitted.
## ADR-028

- Lifecycle transitions commit first (row `queue_status=deferred`,
  `warning=event_queue_unavailable`), then publish with a deterministic event ID
  `uuid5(plugin_id, "<event_type>:<updated_at>")`; only a successful publication is
  recorded, and only if no later transition committed meanwhile. The simulation
  worker process sweeps deferred rows every 30 s (no plugin worker exists);
  republished payloads carry `requested_by_user_id=null` and
  `delivery="deferred_republish"` because registry rows do not persist the actor.
- `plugin.failed` events for rejected installs (no record) are rate-limited: one per
  (actor, plugin_key, failure code) per `PLUGIN_FAILED_EVENT_WINDOW_SECONDS`
  (default 60) and at most `PLUGIN_FAILED_EVENT_MAX_PER_ACTOR` (default 10) per
  actor per window.
- Signer/signature are *declarations*: prefix/length/allowlist admission only, never
  cryptographic verification; responses always report `declared_unverified`. The
  historical error code `PLUGIN_SIGNATURE_INVALID` is kept for compatibility.
- Correlation uses `normalize_audit_correlation`; opaque ids are kept as `request_id`.

## Verification

Scoped registry/energy tests plus Identity auth, audit consumer and event-contract
regressions: 149 passed. Includes three real PostgreSQL tests with migrations
through0019, downgrade to0018 and re-upgrade, historical claim retention,
concurrent install/uninstall, enable/uninstall serialization and failed-audit
rollback. Executed only on an owned disposable PostgreSQL container; no shared
database migration or deployment. Scoped Ruff passed. Repeat database tests with
`PLUGIN_TEST_DSN` set to an explicitly disposable database; each test creates and
drops its own UUID-named schema. No full-backend or frontend gate is claimed.
