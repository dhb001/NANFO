# ADR026 audit repair — integrated completion

## Delivered scope

Implemented the user-authorized parallel repair of A01–A17 and the explicitly
requested missing workflows. Seven initial owners covered Identity/Organization,
Network, inventory/tenancy UI, session/history, alert/audit, Twin and verification;
performance integration and independent review followed. Existing experimental
changes in the shared worktree were preserved. No commits or live deployment.

| Audit area | Implemented outcome | Detailed handoff |
|---|---|---|
| A01 | Credential-independent feature/query lifetime, preserved drafts/pending IDs/STOP, explicit approval revocation, scoped realtime reconciliation after rotation | AuditRepair-SessionHistory.md |
| A02,A03,A09 | Real inventory forms, full fields, edit/delete, pages/totals, retained errors and ambiguous-outcome reconciliation, device41 selector | AuditRepair-InventoryUI.md; AuditRepair-Network.md |
| A04,A05 | Authoritative org scope on inventory events; event-specific actor/resource mapping; durable deduplicated audit | AuditRepair-Identity.md; AuditRepair-Network.md |
| A06,A12–A16 | Transactional member restoration, approved Operator capabilities, role-aware controls, IP/CIDR/page/name validation, reserved slug409, keyboard slug generation, atomic organization audits | AuditRepair-Identity.md; AuditRepair-InventoryUI.md |
| A07,A08,A10 | Server alert filters/scope before limit, origin labels, paged searchable audit with actor/resource/metadata and nonoverlapping details | AuditRepair-AlertAudit.md |
| A11 | Organization/workspace edit and confirmed delete, dependent-resource conflicts and context cleanup | AuditRepair-InventoryUI.md |
| Missing histories | Authorized Simulation/Intent list APIs, browser history pages/deep links with no auto-execution | AuditRepair-SessionHistory.md; ../api/WorkflowHistory.md |
| Guided Twin | Object/geometry editor, custom groups and paginated members, explicit chosen asset restore/retirement, confirmed group/building cleanup | AuditRepair-Twin.md |
| A17 | Current schema versus historical release separation, current DB fixtures, clean lint, regular isolated CI and bounded local DB runner | AuditRepair-Verification.md |
| Performance | Retained features within original bundle cap; Three catalogue/tree shaking with production render checks | AuditRepair-Performance.md |

Deletion is soft and dependency-aware: active effects must be resolved, referenced
scene/group/asset records cleared explicitly; verified exact restoration can release
intent dependencies. Asset retirement preserves bytes and history. Org membership
discovery automatically reaches the current user beyond the first page, rather than
requiring manual paging to enable legitimate controls. Member/admin locks fence
mutations without deadlocking measured alert fresh-authority sessions.

## Independent review and integration fixes

Independent review found three P2 issues and then independently verified all three
closed: opaque request-ID audit normalization preserving original identity;
canonical new/legacy UUID asset mapping dependency checks; retryable scene drafts
on ORG_AUTHORITY_BUSY distinct from actual SPATIAL_REVISION_CONFLICT.

Parent review additionally repaired rotating-query-key/realtime invalidation
integration and automatic membership-page resolution. Browser selectors were made
specific for newly added Edit/Delete controls, not weakened. Shared test-role
fixture matches backend Operator capabilities.200% text-size mobile menu overflow
was fixed and asserted. The70-test full browser run includes global uncaught-error
and unhandled-promise checks. Desktop/tablet/mobile screenshots were inspected;
fixture screenshots are not live backend acceptance.

## Final observed checks

| Gate | Result |
|---|---|
| Frontend typecheck and lint | PASS |
| Frontend full unit/component suite | **575 passed,95 files** |
| Full Chromium suite, no retries | **70 passed** |
| Post-review affected browser/layout/Twin run | **11 passed**, no retries |
| Production build and original bundle safeguards | **PASS,387.96KiB /410.16KiB** total JS gzip |
| Backend Ruff app/tests/scripts | PASS |
| Final backend full suite | **3632 passed,289 skipped,0 failed** |
| Full default isolated PostgreSQL suite | **253 passed,12 skipped,0 failed** |
| Deployment unit/integration logic suite | **248 passed** |
| Runtime/readiness/historical-verifier/runner subset | **87 passed** |

Counts are overlapping snapshots, not additive unique totals. Backend counts grew
during concurrent experimental work; the last full source run is the3632/289 result.
The local DB runner completed all265 selected cases and cleaned owned processes,
ports and private roots. Earlier failing and incomplete attempts remain documented
in handoffs. PostgreSQL resource-bounded harness settings and sanitized bounded
diagnostics resolved reproducibility; original discarded-log crash cause is unknown.

Commands from frontend: `npm run typecheck`, `npm run lint`, `npm test`,
`npm run perf:bundle`, `npx playwright test --retries=0 --workers=2`.
Backend: `poetry run ruff check app tests scripts`,
`poetry run pytest tests -q --no-cov`, and
`poetry run python -m scripts.audit_isolated_suite --timeout 1200`.
Deployment from backend:
`PYTHONPATH=..:. poetry run pytest -c pyproject.toml ../deploy/tests ../deploy/test_lifecycle.py -q --no-cov`.

## Explicit remaining verification and historical-data boundaries

- Local Redis/Valkey7+ is absent. The12 isolated skips are4 Intent Redis locks,
  1 Report replay,1 login limiter,3 real role login/rotation and3 actual HTTP smoke
  profiles. CI supplies isolated services and enforces zero skips; it has not been
  remotely run in this session. Full browser→real HTTP→real Redis acceptance remains
  unclaimed. Existing289 full-suite skips are reported, never counted as passes.
- Existing malformed historical audit rows are not rewritten. Future events/atomic
  audits are fixed; owner-reviewed append-only historical correction remains an
  explicit data-remediation operation, not an automatic mutation of evidence.
- Concurrent migration0029 invalidates old experimental telemetry-coverage claims.
  It is preserved unchanged. Current readiness/deployment now consistently targets
  0029; historical0027/0028 acceptance evidence is retained. No existing database was
  migrated and no current-source live deployment/backup acceptance is claimed.
- Physical RF, enterprise GPU/load qualification, admitted live model/safety/native
  execution and private experimental activation remain their separate qualification
  scopes. No new public experimental mode or training changes were introduced.
