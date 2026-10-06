# Feature PRD: Reporting

## Purpose
Generate operational and executive reports from telemetry, incidents, and simulation outcomes.

## Business Goal
Provide evidence-driven decision support and audit-ready summaries.

## Functional Requirements
- Generate PDF/CSV report outputs.
- Support date-range and scope filters.
- Include KPI summaries and trend slices.

## Non-Functional Requirements
- Asynchronous generation for heavy reports.
- Stable output schemas for automation.

## API
- `POST /api/v1/reports/generate`
- `GET /api/v1/reports/{id}`
- `GET /api/v1/reports?workspace_id=UUID` - owner-scoped paginated history.
- `GET /api/v1/reports/{id}/download?workspace_id=UUID` - authenticated binary
  CSV/PDF; errors use the canonical JSON envelope (ADR-019). Since ADR-028 C5
  (**BREAKING format**) the download sends `ETag: "sha256:<hex>"` (was `"<hex>"`), and a
  matching `If-None-Match` returns 304. Generation beyond the per-organisation quota
  (`REPORTS_MAX_BYTES_PER_ORG`, C26) returns 507 `REPORT_ORG_QUOTA_EXCEEDED`.

## Database
- Report metadata and artifact references.

## Events
- `report.requested`, `report.generated`, `report.failed`

## Risks
- Long-running report jobs impacting worker pools.

## Acceptance Criteria
ADR019 backend implementation: real CSV/ReportLab PDF artifacts from bounded frozen
owner-service snapshots, durable leased worker and lifecycle outbox. Historical
fabricated references remain suppressed. Generation rechecks current write authority;
status/history/download require current membership and report ownership. Authorized
downloads verify actual bytes/length/SHA256 before streaming. No public storage URI.
Request schemas, limits, explicit source omissions, deployment and verification:
`backend/app/modules/report/README.md`.

- [x] Backend reports generated with consistent structure and metadata.
- [x] Failed jobs provide actionable error context.

## Tests
- Unit: report configuration validation.
- Integration: queue-to-artifact pipeline.
