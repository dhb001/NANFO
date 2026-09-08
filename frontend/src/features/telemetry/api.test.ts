import { afterEach, expect, it, vi } from "vitest";
import { getDeviceTelemetry, getTelemetryHistory } from "./api";

afterEach(() => vi.unstubAllGlobals());

it("serializes raw defaults unchanged and forwards device time bounds", async () => {
  const fetchMock = vi.fn().mockImplementation(async () => Response.json({ success: true, data: { items: [] }, meta: {}, errors: null }));
  vi.stubGlobal("fetch", fetchMock);
  await getTelemetryHistory("token", { workspaceId: "workspace" });
  const raw = new URL(String(fetchMock.mock.calls[0][0]), "http://localhost");
  expect([...raw.searchParams.keys()]).toEqual(["workspace_id", "page", "page_size"]);
  await getDeviceTelemetry("token", "device", 2, 10, "queue_backlog_bytes", { startTime: "2026-09-08T00:00:00Z", endTime: "2026-09-08T01:00:00Z" });
  const device = new URL(String(fetchMock.mock.calls[1][0]), "http://localhost");
  expect(Object.fromEntries(device.searchParams)).toEqual({ page: "2", page_size: "10", metric: "queue_backlog_bytes", start_time: "2026-09-08T00:00:00Z", end_time: "2026-09-08T01:00:00Z" });
});
