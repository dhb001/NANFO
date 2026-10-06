import { afterEach, describe, expect, it, vi } from "vitest";
import { diagnoseModel, getModelDiagnostics } from "./modelApi";
import { modelFixture, modelRecordFixture } from "./operatorFixtures";

const envelope = (data: unknown) => ({ success: true, data, meta: {}, errors: null });
const data = modelFixture();
describe("ADR018 frozen model API", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("uses scoped registry reads and explicit history IDs only", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(Response.json(envelope(data))).mockResolvedValueOnce(Response.json(envelope(modelRecordFixture())));
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    await getModelDiagnostics("token", data.network_id, data.workspace_id, controller.signal);
    await diagnoseModel("token", data.network_id, data.workspace_id, "measured-history-1");
    expect(fetch.mock.calls[0][0]).toMatch(/\/autonomy\/model\?network_id=/);
    // The caller's signal is composed with the default request timeout: aborting it aborts the fetch.
    const passed = fetch.mock.calls[0][1].signal as AbortSignal;
    expect(passed.aborted).toBe(false);
    controller.abort();
    expect(passed.aborted).toBe(true);
    expect(fetch.mock.calls[1][1]).toMatchObject({ method: "POST", headers: { Authorization: "Bearer token" },
      body: JSON.stringify({ network_id: data.network_id, history_reference: "measured-history-1" }) });
  });
  it.each(["/tmp/model.pt", "../history", "", "https://model"])("rejects paths and invalid references %s", async (reference) => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    await expect(diagnoseModel("token", data.network_id, data.workspace_id, reference)).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
  });
  it.each([{ network_id: "other" }, { workspace_id: "other" }, { safety_authorized: true }, { production_dispatch: true },
    { live_history_status: "ready" }, { diagnostics: [null] }, { model: { ...data.model, history_references: ["/tmp/history"] } }])("rejects unsafe/incompatible registry %#", async (patch) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(envelope({ ...data, ...patch }))));
    await expect(getModelDiagnostics("token", data.network_id, data.workspace_id)).rejects.toThrow();
  });
  it.each([{ live: true }, { safety_authorized: true }, { execution: "applied" }, { probabilities_are_safety_confidence: true },
    { input_sha256: "unknown" }, { probabilities: [0.1, 0.1] }, { action: 0 }, { inference_seconds: -1 }, { history_reference: "different" }])("rejects unsafe or mismatched inference %#", async (patch) => {
    const record = modelRecordFixture();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(envelope({ ...record, result: { ...record.result, ...patch } }))));
    await expect(diagnoseModel("token", data.network_id, data.workspace_id, "measured-history-1")).rejects.toThrow();
  });
  it.each([403, 409, 503])("surfaces mutation failure %s without retry or invented inference", async (status) => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ success: false, data: null, meta: {}, errors: { code: "DENIED", message: "Inference unavailable" } }, { status }));
    vi.stubGlobal("fetch", fetch);
    await expect(diagnoseModel("token", data.network_id, data.workspace_id, "measured-history-1")).rejects.toMatchObject({ status });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
