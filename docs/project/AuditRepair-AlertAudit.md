# Workstream 5 — Alert and Audit Repair

Scope: ADR-026 and audit findings A07/A08/A10. Owns frontend reliability/audit,
their types/tests, Alert list service/repository/router and owning documentation.

## Delivered contracts and behavior

- Alert list adds optional workspace/network UUID selection. Owning Network and
  Organization services enforce live membership and selected/token scope. Scope
  and existing status/search/source/severity predicates precede LIMIT; final
  per-record access rechecks remain. No schema changes or cross-module SQL.
- Existing callers without selection retain all-authorized semantics. Counts
  retain their existing **bounded returned-items** meaning. Deterministic ordering
  adds alert UUID after updated/created time. Contract: `docs/api/Alerts.md`.
- Reliability requires selected workspace, optionally selected network, aligned
  with realtime selection. Text filters submit; status applies immediately.
  Origin labels show recorded source/org/workspace/network, including legacy
  nested payloads. No invented source or global count. Identity/tenant/scope
  changes reset filters/details; token rotation keeps drafts.
- Alert history paging was considered: existing list/history contracts provide
  no cursor/offset. Kept documented 200-item UI cap and explicit refine-filters
  guidance. No undocumented endpoint or fabricated page count.
- Audit uses existing GET `/api/v1/audit/logs` with `org_id`, `actor_id` UUID,
  `resource_type`, `page`, `page_size`, and agent1's ADR026 optional `search`.
  Text filters submit together, resetting page 1. Query keys include scope and
  every applied filter. The view requires a selected organization.
- Audit renders a semantic bounded 50-row ordered list with natural row heights;
  no fixed-stride overlapping virtual rows. Previous/next controls use server
  total/page/page_size. Expandable keyboard-accessible native details expose
  actor/resource/log/org IDs, correlation, timestamp and full recorded metadata
  (including before/after evidence). Null fields are explicitly not recorded.
- Feature-local wrapping/layout supports long event names, UUIDs and metadata.
  Empty, loading, error/retry states remain explicit. Organization/identity
  switches reset paging/filters/details; rotating access tokens preserve drafts.

## Ownership and integration

Agent1 owns audit GET search implementation, Identity and audit-consumer changes.
This workstream consumes that approved contract without editing those modules.
Tracking is recorded here instead of shared sprint/journal/decision files, per
parallel ownership instruction. Existing audit heading wording and other
pre-existing changes were preserved.

## Verification

- Backend targeted unit/router suite: **45 passed** (`test_alert_service.py`,
  `test_alert_scope_filters.py`, `test_alerts_endpoints.py`). Includes malformed
  scope UUID validation, claims preserved separately from selection, selected
  resource owner denial before query, and existing action/read envelopes.
- Disposable PostgreSQL regression: **2 passed** in
  `test_alert_scope_postgres.py`. Actual SQL retrieves an older active behind 201
  newer resolved rows, narrows another authorized network before LIMIT, retains
  unfiltered semantics and rejects foreign/mismatched/claim-conflicting/revoked
  scope through real owning services. Test fixture corrections during verification
  accounted for ORM update timestamps and `deleted_at` membership soft deletion.
- Frontend targeted Vitest: **24 passed** across reliability/audit and existing
  `RealtimesBridge.test.tsx` (including malformed/disconnect/authorization paths).
  Audit fixture covers 125 records, final page controls, details, actor/resource/
  server-search submission, tenant reset and token-rotation draft retention.
- Chromium: **4 passed** across the two new `alert-audit-repair.spec.ts` cases and
  two existing `vs11-alerts-lifecycle.spec.ts` cases. New browser fixtures verify
  older-active server filtering, selected request scope/origin, 125-record audit
  paging, keyboard-expanded metadata, long rows, narrow overflow and 200% text
  layout. Existing cases passed on the first run; new cases passed after refining
  the zoom assertion to distinguish the shared-shell defect recorded below.
- Scoped Ruff, ESLint, TypeScript and `git diff --check`: **passed**. Scoped
  TypeScript uses `/tmp/opencode/alert-audit-ws5-tsconfig.json`, extending the real
  frontend compiler settings and including both owned features/types and their
  transitive imports. Full `npm run typecheck` currently reports three unrelated
  TS2352 errors in the parallel workstream's
  `frontend/src/features/digitalTwin/GuidedEditing.test.tsx` at 43, 44 and 132;
  no owned-file diagnostics remain.

Commands (from owning frontend/backend directory):

```sh
poetry run pytest --no-cov tests/unit/test_alert_service.py tests/unit/test_alert_scope_filters.py tests/integration/test_alerts_endpoints.py -q
ALERT_TEST_DSN=postgresql+asyncpg://ws5@127.0.0.1:56435/postgres poetry run pytest --no-cov tests/integration/test_alert_scope_postgres.py -q
npm test -- src/features/reliability src/features/audit src/features/realtime/RealtimesBridge.test.tsx
npx playwright test tests/e2e/alert-audit-repair.spec.ts tests/e2e/vs11-alerts-lifecycle.spec.ts --retries=0 --workers=2
npx eslint src/features/reliability src/features/audit src/shared/types/alerts.ts src/shared/types/audit.ts tests/e2e/alert-audit-repair.spec.ts
npx tsc -p /tmp/opencode/alert-audit-ws5-tsconfig.json --noEmit
```

Browser fixtures verify request/interaction/layout behavior, not deployed backend
acceptance. PostgreSQL tests use only an owned disposable local cluster and the
existing alert migration fixture through 0025 (not a claim of repository-head
migration verification). Cluster uses `/tmp/opencode/alert-audit-ws5-pg`, stopped
after testing; per-test schemas are removed by fixture teardown. No shared service
migrations or commits. Agent1's audit GET now exposes `search` with max length 200,
matching the UI contract; its backend implementation remains agent1-owned.

### Shared-shell finding for the owner

At 390px and root text size 200%, `.mobile-menu` extends to x=406.16px, outside
the viewport. Audit-owned content stays within the viewport and rows do not
overlap; the normal 390px whole document has no horizontal overflow. The new
browser regression checks normal whole-document overflow plus audit-local
200% text layout. The shared navigation/styles were not edited by this workstream.
