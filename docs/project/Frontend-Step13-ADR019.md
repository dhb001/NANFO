# Step13 Frontend Integration

## Scope

Reports, Reliability and Plugins consume ADR019 backend contracts. No backend,
AI, emulation, energy page or power-control toggle is implemented by this
frontend workstream. Energy has no existing page and remains CLI research only.
Browser fixtures are contract evidence, not report-worker or measured-network
acceptance. Parent integration must verify the deployed services separately.

## Schemas Relied Upon

- `backend/app/modules/report/schemas.py`: `GenerateReportRequest`,
  `ReportScope`, `ReportFilters`, `ReportRecordResponse`, `ReportHistoryResponse`.
- `backend/app/modules/report/artifacts.py`: artifact version 1, status version
  at least 2, actual SHA-256/length receipt semantics; historical metadata masking.
- `backend/app/modules/report/service.py`: `snapshot_summary` section row count,
  total, truncation, time field and omissions. No arbitrary artifact URI is shown.
- `backend/app/modules/alert/schemas.py`: existing records and new history entries.
- `backend/app/modules/alert/detector.py`, `measured.py`, `README.md`: rule version,
  breach/recover comparison, sustained window, minimum samples, max age/gap,
  observed time, units, source/method/quality, exact tenant/device/port/peer/run
  recovery scope. UI does not evaluate detector rules.
- `backend/app/modules/plugin/schemas.py` and `api/v1/plugins.py`: metadata-only
  declarations, registry flags, masked historical safety claims and 204 uninstall.

## New Consumed Routes

| Route | Contract |
| --- | --- |
| `GET /api/v1/reports?workspace_id=...&page=...&page_size=20` | Canonical history envelope; workspace history, not network-filtered |
| `GET /api/v1/reports/{id}/download?workspace_id=...` | Bearer-authenticated binary PDF/CSV; JSON errors |
| `GET /api/v1/alerts/{id}` | Authorized record envelope; scope comes from backend authority, no invented query field |
| `GET /api/v1/alerts/{id}/history` | Authorized chronological immutable history envelope |
| `DELETE /api/v1/plugins/{id}` | Admin + write permission + current membership, exact 204 success |

Existing report generate/detail, alert list/ack/resolve and registry
list/install/enable/disable routes remain. No new frontend route is required:
the existing `/ops/reports`, `/ops/reliability`, `/ops/plugins` parents own the UI.

## Integration Notes

- Report form exposes only schema fields, resets incompatible filters on type
  changes, defaults to current last-24h dates and selected workspace/network.
  Detailed validation, UUID checks and source/filter applicability remain backend
  owned. Failed retry creates a new key and requires form review and submission.
- Generated status without versioned hash/positive-size metadata is not a success
  presentation. Binary fetch never follows artifact URIs or redirects. Actual
  received length must match metadata; exposed Content-Length and ETag must match.
  Browser SHA-256 verification defaults on and can be explicitly disabled, which
  is disclosed in the result. Secure-context WebCrypto is required when enabled.
- Download uses the current bearer and one refresh retry, rejects session/scope
  changes, aborts on unmount and revokes temporary Blob URLs. Filename is sanitized
  and its extension follows the media type. Browser allocation is capped at 32 MiB.
- For cross-origin deployment, allow the existing bearer CORS flow and expose
  `ETag` and `Content-Disposition` if header comparison/server filename is desired.
  Their absence does not bypass metadata hash or actual-length verification.
- Alert detail/history keys use `["alerts", token, ...]`, preserving existing
  realtime lifecycle/reconnect/backpressure invalidation without bridge edits.
  No historical missing lifecycle entry or missing measurement is fabricated.
- Registry labels always say declared_unverified/not_executed, including legacy
  overclaims. Uninstall requires explicit confirmation and exact authorized 204;
  failures stay visible. Inline status avoids mobile toast obstruction.
- Parent deployment owns report worker/storage and Alert worker/migrations.
  No shared service was migrated or started by this frontend workstream.

## Verification

Full frontend typecheck, lint, unit, production build, unchanged bundle budget
and no-retry Chromium suite are the closure gates. Browser PDF and CSV fixtures
contain actual deterministic bytes; tests read the downloaded stream and compare
both bytes and SHA-256. Fixtures are generated in memory, not committed artifacts.
Additional tests cover tampering, empty/oversized/truncated bytes, denial, token
refresh, context change, safe filenames, Blob cleanup, missing artifacts, history
pagination, detector provenance and mobile/keyboard uninstall/history workflows.

Final gates: 487 unit tests, typecheck, lint, production build and bundle check passed. Total JS
gzip is 410.09 KiB against the unchanged 410.16 KiB limit; all other bundle checks
passed. Full Chromium passed 41/41 with two workers and retries disabled on the
standalone rerun. Initial mobile toast obstruction was fixed; one later concurrent
build/test run timed out before login, with no test retry or timeout relaxation.
