import { beforeEach, describe, expect, it, vi } from "vitest";
import { acknowledgeAlert, listAlerts, resolveAlert, getAlert, getAlertHistory } from "@/features/reliability/api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

describe("reliability api", () => {
  it("reads authorized detail and history without invented query scope", async () => {
    fetchMock.mockImplementation(async () => Response.json({ success: true, data: { alert_id: "a1", items: [], total: 0 }, meta: {}, errors: null }));
    await getAlert("token-1", "a1"); await getAlertHistory("token-1", "a1");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/v1\/alerts\/a1$/);
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/api\/v1\/alerts\/a1\/history$/);
    expect(fetchMock.mock.calls[1][1].headers).toEqual({ Authorization: "Bearer token-1" });
  });
  it("lists alerts with query parameters", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: {
          items: [],
          total: 0,
          status_counts: {
            active: 0,
            acknowledged: 0,
            resolved: 0,
          },
        },
        meta: { request_id: "req-1", timestamp: "2026-08-14T12:00:00Z" },
        errors: null,
      }),
    });

    await listAlerts("token-1", {
      status: "active",
      severity: "critical",
      source: "telemetry",
      correlationId: "00000000-0000-0000-0000-000000000111",
      search: "threshold",
      limit: 50,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [requestUrl, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toContain("/api/v1/alerts?");
    expect(requestUrl).toContain("status=active");
    expect(requestUrl).toContain("severity=critical");
    expect(requestUrl).toContain("source=telemetry");
    expect(requestUrl).toContain("correlation_id=00000000-0000-0000-0000-000000000111");
    expect(requestUrl).toContain("search=threshold");
    expect(requestUrl).toContain("limit=50");
    expect(requestInit.headers).toMatchObject({ Authorization: "Bearer token-1" });
  });

  it("posts acknowledge action", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: {
          alert_id: "00000000-0000-0000-0000-000000000222",
          alert_key: "telemetry_runtime_adapter_slo_threshold_breach",
          source: "telemetry",
          status: "acknowledged",
          severity: "critical",
          correlation_id: "00000000-0000-0000-0000-000000000223",
          payload: {},
          acknowledged_by_user_id: "00000000-0000-0000-0000-000000000224",
          resolved_by_user_id: null,
          acknowledged_at: "2026-08-14T12:00:00Z",
          resolved_at: null,
          created_at: "2026-08-14T11:59:00Z",
          updated_at: "2026-08-14T12:00:00Z",
          queue_status: "queued",
          stream_entry_id: "800-0",
          warning: null,
          idempotent_replay: false,
        },
        meta: { request_id: "req-ack", timestamp: "2026-08-14T12:00:00Z" },
        errors: null,
      }),
    });

    await acknowledgeAlert("token-1", "00000000-0000-0000-0000-000000000222");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [requestUrl, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toContain("/api/v1/alerts/00000000-0000-0000-0000-000000000222/ack");
    expect(requestInit.method).toBe("POST");
  });

  it("posts resolve action", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: {
          alert_id: "00000000-0000-0000-0000-000000000333",
          alert_key: "telemetry_runtime_adapter_slo_threshold_breach",
          source: "telemetry",
          status: "resolved",
          severity: "critical",
          correlation_id: "00000000-0000-0000-0000-000000000334",
          payload: {},
          acknowledged_by_user_id: "00000000-0000-0000-0000-000000000335",
          resolved_by_user_id: "00000000-0000-0000-0000-000000000336",
          acknowledged_at: "2026-08-14T11:58:00Z",
          resolved_at: "2026-08-14T12:00:00Z",
          created_at: "2026-08-14T11:57:00Z",
          updated_at: "2026-08-14T12:00:00Z",
          queue_status: "queued",
          stream_entry_id: "801-0",
          warning: null,
          idempotent_replay: false,
        },
        meta: { request_id: "req-resolve", timestamp: "2026-08-14T12:00:00Z" },
        errors: null,
      }),
    });

    await resolveAlert("token-1", "00000000-0000-0000-0000-000000000333");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [requestUrl, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toContain("/api/v1/alerts/00000000-0000-0000-0000-000000000333/resolve");
    expect(requestInit.method).toBe("POST");
  });
});
