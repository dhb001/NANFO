import { afterEach, describe, expect, it, vi } from "vitest";
import { executeIntent } from "@/features/intent/api";

describe("manual intent execute contract", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("accepts HTTP 202 as started, preserving additive booleans and the same retry/cancel identity", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
      success: true, data: { status: "execution_started", execution_provenance: { execution_id: "job-1" } },
      meta: { request_id: "request-1", timestamp: "2026-09-09T12:00:00Z" }, errors: null,
    }), { status: 202 })));
    vi.stubGlobal("fetch", fetchMock);
    const request = { workspace_id: "workspace", intent_id: "intent", idempotency_key: "same-key", manual_approval: true, cancel: false };
    const result = await executeIntent("token", request, "same-key");
    await executeIntent("token", request, "same-key");
    await executeIntent("token", { ...request, cancel: true }, "same-key");
    expect(result.data.status).toBe("execution_started");
    expect(fetchMock.mock.calls[0]).toEqual(fetchMock.mock.calls[1]);
    for (const [url, options] of fetchMock.mock.calls) {
      expect(url).toMatch(/\/api\/v1\/intents\/execute$/);
      expect(options.headers["Idempotency-Key"]).toBe("same-key");
      expect(JSON.parse(options.body)).toMatchObject({ workspace_id: "workspace", intent_id: "intent", idempotency_key: "same-key", manual_approval: true });
    }
    expect(JSON.parse(fetchMock.mock.calls[2][1].body).cancel).toBe(true);
  });
});
