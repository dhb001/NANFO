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
Current foundation behavior: no renderer is installed. Processing requests yields
`failed` with `REPORT_RENDERER_UNAVAILABLE` and no artifacts. Historical fabricated
baseline references are suppressed on reads/replays. Generation requires current
write capability and org write membership; status reads require membership.

- [ ] Reports generated with consistent structure and metadata.
- [ ] Failed jobs provide actionable error context.

## Tests
- Unit: report configuration validation.
- Integration: queue-to-artifact pipeline.
