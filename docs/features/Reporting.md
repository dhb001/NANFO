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

## Database
- Report metadata and artifact references.

## Events
- `report.requested`, `report.generated`, `report.failed`

## Risks
- Long-running report jobs impacting worker pools.

## Acceptance Criteria
- [ ] Reports generated with consistent structure and metadata.
- [ ] Failed jobs provide actionable error context.

## Tests
- Unit: report configuration validation.
- Integration: queue-to-artifact pipeline.
