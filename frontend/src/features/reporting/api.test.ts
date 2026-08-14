import { beforeEach, describe, expect, it, vi } from "vitest";

import { generateReport, getReport } from "@/features/reporting/api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

describe("reporting api", () => {
  it("posts generate report with idempotency key", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 202,
      json: async () => ({
        success: true,
        data: {
          report_id: "00000000-0000-0000-0000-000000000951",
          workspace_id: "00000000-0000-0000-0000-000000000222",
          network_id: null,
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
          stream_entry_id: "1000-0",
          warning: null,
          idempotency_key: "rep-1",
          correlation_id: "corr-1",
          requested_by_user_id: "00000000-0000-0000-0000-000000000123",
          requested_at: "2026-08-14T12:00:00Z",
          completed_at: null,
          created_at: "2026-08-14T12:00:00Z",
          updated_at: "2026-08-14T12:00:00Z",
          idempotent_replay: false,
        },
        meta: { request_id: "req-report-generate", timestamp: "2026-08-14T12:00:00Z" },
        errors: null,
      }),
    });

    await generateReport(
      "token-1",
      {
        workspace_id: "00000000-0000-0000-0000-000000000222",
        network_id: null,
        report_type: "executive_summary",
        format: "pdf",
        date_range: {
          start: "2026-08-01T00:00:00Z",
          end: "2026-08-14T00:00:00Z",
        },
        scope: { workspace: "all" },
        filters: { kpi: "latency" },
      },
      "rep-1",
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [requestUrl, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toContain("/api/v1/reports/generate");
    expect(requestInit.method).toBe("POST");
    expect(requestInit.headers).toMatchObject({
      Authorization: "Bearer token-1",
      "Idempotency-Key": "rep-1",
    });
  });

  it("fetches report by id and workspace query", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: {
          report_id: "00000000-0000-0000-0000-000000000951",
          workspace_id: "00000000-0000-0000-0000-000000000222",
          network_id: null,
          report_type: "executive_summary",
          format: "pdf",
          status: "generated",
          date_range: {
            start: "2026-08-01T00:00:00Z",
            end: "2026-08-14T00:00:00Z",
          },
          scope: { workspace: "all" },
          filters: { kpi: "latency" },
          artifacts: [],
          error: null,
          queue_status: "queued",
          stream_entry_id: "1001-0",
          warning: null,
          idempotency_key: "rep-1",
          correlation_id: "corr-1",
          requested_by_user_id: "00000000-0000-0000-0000-000000000123",
          requested_at: "2026-08-14T12:00:00Z",
          completed_at: "2026-08-14T12:00:05Z",
          created_at: "2026-08-14T12:00:00Z",
          updated_at: "2026-08-14T12:00:05Z",
        },
        meta: { request_id: "req-report-detail", timestamp: "2026-08-14T12:00:05Z" },
        errors: null,
      }),
    });

    await getReport(
      "token-1",
      "00000000-0000-0000-0000-000000000951",
      "00000000-0000-0000-0000-000000000222",
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [requestUrl, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toContain("/api/v1/reports/00000000-0000-0000-0000-000000000951");
    expect(requestUrl).toContain("workspace_id=00000000-0000-0000-0000-000000000222");
    expect(requestInit.method).toBe("GET");
    expect(requestInit.headers).toMatchObject({ Authorization: "Bearer token-1" });
  });
});
