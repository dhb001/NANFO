# ADR019 Reports

Report owns `reports`, immutable bounded snapshots, leased rendering, artifact
receipts and `report_outbox`. Migration `0017` follows `0016`. Historical generated
placeholders remain masked; legacy pending jobs without source snapshots are failed
conservatively, never reconstructed from a fictitious cursor. No cross-module SQL
is used in application code. The verifier seeds disposable fixtures only.

## API / Frontend Handoff

Existing POST `/api/v1/reports/generate` returns 202 and the standard JSON envelope.
Request (unknown keys/types/filters are rejected):

```json
{
  "workspace_id": "uuid",
  "network_id": null,
  "report_type": "executive_summary",
  "format": "pdf",
  "date_range": {"start": "2026-09-01T00:00:00Z", "end": "2026-09-02T00:00:00Z"},
  "scope": {"workspace": "all", "simulation_ids": [], "intent_ids": []},
  "filters": {"metric": null, "alert_status": null, "alert_severity": null, "max_rows": 100}
}
```

- Types: `executive_summary`, `operational_summary`, `telemetry`, `alerts`,
  `simulation`, `intent`. Formats: `csv`, `pdf`.
- Timezone required, UTC normalized, increasing start-inclusive/end-exclusive range,
  maximum 31 days; end may be at most five minutes in the future.
- Each source ID array: maximum 20 unique UUIDs. IDs are necessary for Intent and
  Simulation; no hidden global discovery. Out-of-range IDs are explicit omissions,
  inaccessible/mismatched-network IDs reject acceptance.
- `max_rows`: strict integer 1..500 per section, default 100. `metric`: 1..100
  letters/digits/underscore/dot/colon/hyphen. Alert status: active/acknowledged/resolved.
  Severity: info/warning/critical/low/medium/high. Irrelevant section filters reject.
- Optional `Idempotency-Key`: 1..128 printable ASCII; different payload OR owner
  conflicts with 409. Replays retain the original frozen snapshot.
- GET `/api/v1/reports/{report_id}?workspace_id=uuid` retains the status schema.
- GET `/api/v1/reports?workspace_id=uuid&page=1&page_size=20` returns
  `data: {items: ReportRecord[], total: number, page: number, page_size: number}`.
  Page size 1..100, page 1..1000000. Exact total is scoped to current user/workspace,
  including empty pages, ordered requested_at/report_id descending.
- GET `/api/v1/reports/{report_id}/download?workspace_id=uuid` is binary on success,
  JSON envelope on errors. Fetch with Authorization and consume Blob, not a public
  URL link. `Content-Disposition`, `Content-Length`, SHA256 ETag, no-store, nosniff.
- Status: requested/running/generated/failed. `queue_status` is outbox_pending or
  queued, not evidence of rendering. Poll status while requested/running.
- New status fields: `artifact_version: number`, `status_version: number`,
  `snapshot_sha256: string|null`, `snapshot_summary: Record<section, summary>`.
  Summary contains `row_count`, `total: number|null`, `truncated: boolean`,
  `omissions: string[]`, `time_field`, optionally `source_limit`.
- Generated artifacts: `{artifact_id, uri, filename, media_type, checksum_sha256,
  size_bytes, generated_at}`. URI is the authorized download endpoint, never storage.
- Errors include REPORT_REQUEST_INVALID, REPORT_SOURCE_TIMEOUT/INVALID,
  REPORT_SNAPSHOT_TOO_LARGE, REPORT_IDEMPOTENCY_CONFLICT, REPORT_AUTHORITY_REVOKED,
  REPORT_GENERATION_FAILED, REPORT_ARTIFACT_UNVERIFIED/UNAVAILABLE/INVALID.
  Schema-invalid HTTP input follows the existing 422 JSON-envelope handler.

All reads require authenticated current `read:telemetry`, current workspace/org
membership, exact workspace claim narrowing, and report ownership. Admin is NOT an
ownership bypass. Generation additionally requires current write:config and org
Admin/Operator. Worker rechecks current identity/roles/membership/network and explicit
source IDs without depending on the original login session. Logout does not cancel
authorized jobs, but logged-out credentials cannot download. Revocation does block.

## Snapshot / Rendering Limits

Bounded source reads occur during acceptance (20s source timeout, 1MiB snapshot),
not rendering. Each owner service supplies its existing public read contract.
Snapshot consistency is explicitly a bounded request-time collection, not an atomic
cross-store/time-travel snapshot. No credential or arbitrary payload/tag export.
Telemetry contains actual persisted rows/units/provenance. Alerts export lifecycle
and allowlisted measured fields; source list is capped at 500 BEFORE date/network
postfilters, so totals are unknown and the incompleteness warning is always visible.
Simulation exports verified configured-model summary metrics/hash/provenance, not
physical results; per-flow trace/config omissions are explicit. Intent exports
typed approved action and evidence identities/hashes; raw verification/free text
are explicitly omitted.

CSV is standard UTF-8 csv.writer output with columns section,row,field,value and
JSON-pointer field paths. Every cell passes formula neutralization. Values are
lossless JSON, including escaped non-ASCII. PDF uses pinned ReportLab 4.4.10 with
Courier and wrapped text, not cropped tables. Non-ASCII uses reversible JSON escapes
because default fonts lack full Unicode coverage. This limitation is printed in
every PDF. Maximum 30000 cells, 600 PDF pages, configured output byte cap; oversize
fails visibly, never silently drops text.

## Deployment

Install only into the backend environment, never a frozen AI environment:

```bash
env -u VIRTUAL_ENV -u CONDA_PREFIX -u PYTHONPATH poetry env info
env -u VIRTUAL_ENV -u CONDA_PREFIX -u PYTHONPATH poetry install --only main,dev
env -u VIRTUAL_ENV -u CONDA_PREFIX -u PYTHONPATH poetry run python -m scripts.run_report_worker
```

Verified interpreter: backend Poetry Python 3.14.7. ReportLab 4.4.10, Pillow 12.3.0,
pypdf 6.8.0 imports verified; pypdf is dev-only, optional at unit-test import time.
Lockfile changed only for those additions and ReportLab's charset-normalizer.

Operator must provision `REPORTS_STORAGE_PATH` (default `/var/lib/nanfo/reports`),
absolute, outside repository/static roots, no symlink components, backend UID owner,
mode0700. API/worker must share this filesystem and UID. Files mode0600, bounded,
fsync + atomic rename and directory fsync. Never serve the directory statically.
`REPORTS_MAX_BYTES` defaults 8MiB (1KiB..16MiB); lease defaults120s (30..300).
Reads reject symlinks/nonregular files/wrong owner/permissions/hardlinks, read actual
bounded bytes, verify length/SHA256, then stream the immutable verified byte buffer.
Receipt binds artifact identity, snapshot hash and status version. Status checks
receipt integrity; download additionally checks current bytes.

Outbox commits requested/terminal transitions atomically. Stable event UUID/envelope,
ordered per-report replay, stored XADD receipt; at-least-once, not exactly-once.
Worker leases use PostgreSQL time, SKIP LOCKED and fenced terminal CAS. Lost workers
are reclaimable after expiry, each attempt gets a fresh artifact identity. Orphan
attempt files can remain after crash/lease loss; retention/quota and safe operator
orphan cleanup are deployment responsibilities. No automatic deletion of evidence.

Apply migration0017 only to an approved deployment. The combined current Alert
service also requires its separately owned0018. No shared DB was migrated here.

## Disposable Verification

```bash
env -u VIRTUAL_ENV -u CONDA_PREFIX -u PYTHONPATH poetry run python -m scripts.verify_reports --live
env -u VIRTUAL_ENV -u CONDA_PREFIX -u PYTHONPATH poetry run pytest tests -q --no-cov
```

Verifier creates only UUID-owned PostgreSQL/Redis/Neo4j containers, authenticated
API and independent report worker, private storage under `/tmp/opencode`, and cleans
owned processes/containers/volumes. No lab, driver, training or shared Redis stream.
PostgreSQL migration/lease/outbox tests stop at0017; live four-source integration
also applies0018 for current Alert service. Fixtures are explicitly not measured
network acceptance. Evidence JSON contains commands' test counts and artifact hashes.
