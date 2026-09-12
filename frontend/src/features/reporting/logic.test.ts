import { describe, expect, it } from "vitest";

import {
  inferReportErrorMessage,
  isReportTerminal,
  mapQueueTone,
  mapReportStatusTone,
  normalizeReportStatus,
  summarizeArtifactKinds,
} from "@/features/reporting/logic";
import { ReportRecord } from "@/shared/types/reporting";

function makeReport(overrides: Partial<ReportRecord> = {}): ReportRecord {
  return {
    report_id: "00000000-0000-0000-0000-000000000951",
    workspace_id: "00000000-0000-0000-0000-000000000222",
    network_id: "00000000-0000-0000-0000-000000000333",
    report_type: "executive_summary",
    format: "pdf",
    status: "requested",
    date_range: {
      start: "2026-08-01T00:00:00Z",
      end: "2026-08-14T00:00:00Z",
    },
    scope: { workspace: "all" },
    filters: { kpi: "latency" },
    artifacts: [],
    error: null,
    queue_status: "queued",
    stream_entry_id: "900-0",
    warning: null,
    idempotency_key: "rep-1",
    correlation_id: "corr-1",
    requested_by_user_id: "00000000-0000-0000-0000-000000000123",
    requested_at: "2026-08-14T12:00:00Z",
    completed_at: null,
    created_at: "2026-08-14T12:00:00Z",
    updated_at: "2026-08-14T12:00:00Z",
    ...overrides,
  };
}

describe("reporting logic", () => {
  it("normalizes and classifies report statuses", () => {
    expect(normalizeReportStatus(" Generated ")).toBe("generated");
    expect(isReportTerminal("generated")).toBe(true);
    expect(isReportTerminal("failed")).toBe(true);
    expect(isReportTerminal("requested")).toBe(false);
  });

  it("maps status and queue tones", () => {
    expect(mapReportStatusTone("generated")).toBe("ok");
    expect(mapReportStatusTone("failed")).toBe("danger");
    expect(mapReportStatusTone("requested")).toBe("info");
    expect(mapReportStatusTone("mystery")).toBe("warn");

    expect(mapQueueTone("queued")).toBe("ok");
    expect(mapQueueTone("replayed")).toBe("ok");
    expect(mapQueueTone("deferred")).toBe("warn");
    expect(mapQueueTone("pending")).toBe("info");
  });

  it("extracts error messages from report payload", () => {
    expect(inferReportErrorMessage(null)).toBeNull();
    expect(inferReportErrorMessage(makeReport())).toBeNull();
    expect(inferReportErrorMessage(makeReport({ error: { code: "REPORT_GENERATION_FAILED", message: "Queue timed out" } }))).toBe("Queue timed out");
    expect(inferReportErrorMessage(makeReport({ error: { code: "REPORT_GENERATION_FAILED", message: "" } }))).toBe("REPORT_GENERATION_FAILED");
  });

  it("summarizes artifact types from media types", () => {
    expect(summarizeArtifactKinds([])).toBe("none");
    expect(
      summarizeArtifactKinds([
        {
          artifact_id: "a1",
          uri: "/api/v1/reports/a1/download",
          media_type: "application/pdf",
          checksum_sha256: "x",
          size_bytes: 1,
          generated_at: "2026-08-14T12:00:00Z",
        },
        {
          artifact_id: "a2",
          uri: "/api/v1/reports/a2/download",
          media_type: "text/csv",
          checksum_sha256: "y",
          size_bytes: 2,
          generated_at: "2026-08-14T12:00:00Z",
        },
      ]),
    ).toBe("csv, pdf");
  });
});
