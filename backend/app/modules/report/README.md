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
  Page size 1..100, page 1..10000 (shared `PageNumber`, ADR-028). Exact total is
  scoped to current user/workspace, including empty pages, ordered
  requested_at/report_id descending. History rows are a summary projection: the
  database computes `snapshot_summary` and never returns snapshots; receipts are
  checked against the recorded `snapshot_sha256` (detail, replay and download also
  re-hash the frozen snapshot, off the event loop).
- GET `/api/v1/reports/{report_id}/download?workspace_id=uuid` is binary on success,
  JSON envelope on errors. Fetch with Authorization and consume Blob, not a public
  URL link. `Content-Disposition`, `Content-Length`, `ETag: "sha256:<hex>"` (C5,
  **BREAKING format**; was the bare hex), no-store, nosniff. `If-None-Match`
  (strong/weak, lists, `*`) matching the digest returns `304` without reading the
  file. Clients accept both ETag formats; the body SHA-256 remains authoritative.
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
  REPORT_GENERATION_FAILED, REPORT_ATTEMPTS_EXHAUSTED (`reason:
  "attempts_exhausted"`), REPORT_ARTIFACT_UNVERIFIED/UNAVAILABLE/INVALID,
  REPORT_STORAGE_UNAVAILABLE (503, global reserve) and REPORT_ORG_QUOTA_EXCEEDED
  (507, per-organisation quota, ADR-028 C26).
  Schema-invalid HTTP input follows the existing 422 JSON-envelope handler.
- C26 storage fairness: besides the global free-space reserve, a new report is
  admitted only while its organisation's recorded artifact bytes (generated
  receipts) plus one full `REPORTS_MAX_BYTES` reservation per requested/running
  job plus one more full artifact stay within `REPORTS_MAX_BYTES_PER_ORG`
  (default 536870912 = 512 MiB, never below one artifact). A cheap pre-check runs
  before any source read; the authoritative check runs after the sources under a
  per-organisation transaction advisory lock held until the new row commits, so
  concurrent requests cannot overshoot. Idempotent replays are never refused. The
  organisation's workspaces come from the Organization owner's live membership
  read; reports of deleted workspaces are no longer attributed to it.
- Request provenance is not part of the frozen snapshot (ADR-028): identical
  sources give an identical `snapshot_sha256` and identical artifact bytes for any
  `X-Request-ID`. The shared `app.core.correlation` mapping sets `correlation_id`;
  an opaque/non-canonical original is carried as `request_id` in the
  `report.requested` event payload (and therefore in its audit metadata).

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
and allowlisted measured fields; Alert's scoped SQL applies the network, date
range and status/severity filters before its `max_rows` limit and returns an exact
`total` with `truncated = total > row_count` (ADR-028; historical snapshots keep
their recorded `source_limit`/omission fields).
Simulation exports verified configured-model summary metrics/hash/provenance, not
physical results; per-flow trace/config omissions are explicit. Intent exports
typed approved action and evidence identities/hashes; raw verification/free text
are explicitly omitted.

CSV is standard UTF-8 csv.writer output with columns section,row,field,value and
JSON-pointer field paths. Every cell passes formula neutralization. Values are
lossless JSON, including escaped non-ASCII (CSV bytes are unchanged by ADR-028).
PDF uses pinned ReportLab 4.4.10 with an embedded, integrity-checked DejaVu Sans
Mono TrueType subset (`fonts/README.md`) and wrapped text, not cropped tables.
Names in Latin, Greek, Cyrillic and other covered scripts render as text; cells are
JSON (values) or JSON string bodies (sections/paths), and characters the font
cannot show, right-to-left, control, format, private-use and unassigned characters
are reversible JSON `\uXXXX` escapes (astral characters as surrogate pairs). This
rule is printed on the first line of every PDF. If the font file is missing,
unreadable, altered (SHA-256 mismatch) or not monospaced, PDFs fall back to
ReportLab's bundled standard Courier with printable-ASCII coverage (the pre-ADR-028
rendering: everything else escaped), logged once as `report_pdf_font_fallback`;
unverified font bytes are never embedded. Maximum 30000 cells, 600 PDF pages,
configured output byte cap; oversize fails visibly, never silently drops text.

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
Reads reject symlinks/nonregular files/wrong owner/permissions/hardlinks, verify
actual length/SHA256 in bounded chunks, then stream the same verified descriptor
by offset (never the path again; memory is O(64 KiB) per download). The final block
is withheld if the bytes change after verification, so an altered file never
completes a download. Receipt binds artifact identity, snapshot hash and status
version. Status checks receipt integrity; download additionally checks current bytes.

Outbox commits requested/terminal transitions atomically. Stable event UUID/envelope,
ordered per-report replay, stored XADD receipt; at-least-once, not exactly-once.
Worker leases use PostgreSQL time, SKIP LOCKED and fenced terminal CAS. Lost workers
are reclaimable after expiry, each attempt gets a fresh artifact identity.

ADR-028 worker hardening:

- Every claim increments `reports.claim_attempts` (migration 0030). A job already
  claimed `REPORTS_MAX_CLAIM_ATTEMPTS` times (default 5, 1..100) becomes terminal
  `failed` with `error.reason = "attempts_exhausted"` in its own transaction and
  emits `report.failed`; it is never leased again.
- `python -m scripts.run_report_worker` isolates each iteration: an exception is
  logged by type only, the job keeps its lease until expiry (natural backoff) and
  consecutive failures back off exponentially (0.5 s .. 30 s, jittered). `--once`
  still exits non-zero on failure.
- The lease is renewed every `REPORTS_LEASE_SECONDS / 3` while rendering; a lost
  lease aborts the attempt without a terminal write. An attempt whose terminal CAS
  loses (or that fails after writing) deletes its own file.
- Hourly (`REPORTS_MAINTENANCE_INTERVAL_SECONDS`, default 3600) the worker removes
  attempt files that no row references and that are older than
  `REPORTS_ORPHAN_GRACE_SECONDS` (default 86400, minimum 3600). Active jobs do not
  block this: every requested/running job's current `<report>-<lease>` file is
  protected. Registered artifacts, symlinks, foreign/non-private files and unknown
  names are never touched. The offline `ReportOperationsService.cleanup` operator
  tool keeps its stricter stopped-writer contract.
- Optional retention: `REPORTS_RETENTION_DAYS` (default 0 = keep forever) deletes
  generated reports completed more than N days ago (rows first, then files; rows
  with unpublished outbox events are kept until delivered). This removes the
  report from history; telemetry pins are released by the owner reconciliation.
- Published outbox rows older than `REPORT_OUTBOX_RETENTION_DAYS` (default 30;
  `0` keeps them) are deleted in bounded batches (500, at most 10 per run):
  published at least N days ago and, with migration 0030's
  `report_outbox.created_at`, created at least N days ago. Unpublished rows (the
  delivery queue that also orders per-report publication) are never touched.
- Maintenance steps (retention, orphan files, outbox) are isolated: one failing
  step is logged (`report_maintenance_step_deferred`) and retried next interval.
- These optional settings are read with `getattr` and clamped; until they are
  declared in `Settings` they use the defaults above.
- `report.requested` notifications without a UUID `report_id` are poison: the
  consumer raises `DeterministicEventError` (dead-lettered on first delivery,
  ADR-028 C14); transient failures stay pending.

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
