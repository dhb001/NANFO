import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  disablePlugin,
  enablePlugin,
  installPlugin,
  listPlugins,
  uninstallPlugin,
} from "@/features/plugins/api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

describe("plugins api", () => {
  it("requires an authorized DELETE and propagates current permission denial", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await uninstallPlugin("token-1", "plugin-1");
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/v1/plugins/plugin-1"), expect.objectContaining({ method: "DELETE", headers: { Authorization: "Bearer token-1" } }));
    fetchMock.mockResolvedValueOnce(Response.json({ success: false, data: null, errors: { code: "DENIED", message: "Permission revoked" } }, { status: 403 }));
    await expect(uninstallPlugin("token-1", "plugin-1")).rejects.toMatchObject({ code: "DENIED", status: 403 });
    fetchMock.mockResolvedValueOnce(Response.json({ success: false, errors: { code: "DENIED", message: "Denied envelope" } }));
    await expect(uninstallPlugin("token-1", "plugin-1")).rejects.toMatchObject({ code: "DENIED" });
  });
  it("lists plugins with query parameters", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: {
          items: [],
          total: 0,
          status_counts: {
            installed: 0,
            enabled: 0,
            disabled: 0,
            failed: 0,
          },
        },
        meta: { request_id: "req-plugins-list", timestamp: "2026-08-14T12:00:00Z" },
        errors: null,
      }),
    });

    await listPlugins("token-1", {
      status: "installed",
      enabled: false,
      search: "safe",
      limit: 25,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [requestUrl, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toContain("/api/v1/plugins?");
    expect(requestUrl).toContain("status=installed");
    expect(requestUrl).toContain("enabled=false");
    expect(requestUrl).toContain("search=safe");
    expect(requestUrl).toContain("limit=25");
    expect(requestInit.headers).toMatchObject({ Authorization: "Bearer token-1" });
  });

  it("posts install action", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({
        success: true,
        data: {
          plugin_id: "00000000-0000-0000-0000-000000000701",
          plugin_key: "safe-plugin",
          name: "Safe Plugin",
          version: "1.0.0",
          manifest: {},
          signature_status: "declared_unverified",
          dependency_status: "declared_unverified",
          sandbox_status: "not_executed",
          status: "installed",
          enabled: false,
          failure_reason: null,
          queue_status: "queued",
          stream_entry_id: "701-0",
          warning: null,
          installed_at: "2026-08-14T12:00:00Z",
          updated_at: "2026-08-14T12:00:00Z",
          idempotent_replay: false,
        },
        meta: { request_id: "req-plugin-install", timestamp: "2026-08-14T12:00:00Z" },
        errors: null,
      }),
    });

    await installPlugin("token-1", {
      plugin_key: "safe-plugin",
      name: "Safe Plugin",
      version: "1.0.0",
      signer: "nanfo-labs",
      signature: "sig:abcdef1234567890",
      dependencies: {
        platform_version: "0.1.0",
        requires: ["core:telemetry"],
      },
      sandbox: {
        isolation_mode: "process",
        permissions: ["read:telemetry"],
      },
      metadata: {},
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [requestUrl, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toContain("/api/v1/plugins/install");
    expect(requestInit.method).toBe("POST");
  });

  it("posts enable and disable actions", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: {
          plugin_id: "00000000-0000-0000-0000-000000000701",
          plugin_key: "safe-plugin",
          name: "Safe Plugin",
          version: "1.0.0",
          manifest: {},
          signature_status: "declared_unverified",
          dependency_status: "declared_unverified",
          sandbox_status: "not_executed",
          status: "enabled",
          enabled: true,
          failure_reason: null,
          queue_status: "queued",
          stream_entry_id: "702-0",
          warning: null,
          installed_at: "2026-08-14T12:00:00Z",
          updated_at: "2026-08-14T12:00:00Z",
          idempotent_replay: false,
        },
        meta: { request_id: "req-plugin-action", timestamp: "2026-08-14T12:00:00Z" },
        errors: null,
      }),
    });

    await enablePlugin("token-1", "00000000-0000-0000-0000-000000000701");
    await disablePlugin("token-1", "00000000-0000-0000-0000-000000000701");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [enableUrl, enableInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [disableUrl, disableInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(enableUrl).toContain("/api/v1/plugins/00000000-0000-0000-0000-000000000701/enable");
    expect(enableInit.method).toBe("POST");
    expect(disableUrl).toContain("/api/v1/plugins/00000000-0000-0000-0000-000000000701/disable");
    expect(disableInit.method).toBe("POST");
  });
});
