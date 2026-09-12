import { afterEach, describe, expect, it, vi } from "vitest";
import { actOnOverride, createOverride, getOverrides } from "./overrideApi";
import { overrideFixture } from "./operatorFixtures";
const row = overrideFixture();
const envelope = (data: unknown) => ({ success: true, data, meta: {}, errors: null });
const input = { network_id: row.network_id, intent_id: row.intent_id, execution_id: row.execution_id, expected_revision: 0, duration_seconds: 300, reason: "Maintenance", return_mode: "monitor" as const };
describe("ADR018 override API", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("uses exact enrollment/cancel/explicit return contracts", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(Response.json(envelope({ network_id: row.network_id, control_revision: 1, overrides: [row], history_limit: 100 })))
      .mockImplementation(() => Promise.resolve(Response.json(envelope(row)))); vi.stubGlobal("fetch", fetch);
    await getOverrides("token", row.network_id, row.workspace_id);
    await createOverride("token", row.workspace_id, input);
    await actOnOverride("token", row.network_id, row.workspace_id, row.override_id, "cancel");
    await actOnOverride("token", row.network_id, row.workspace_id, row.override_id, "return", { expected_revision: 1, reason: "Return after readback" });
    expect(fetch.mock.calls[1][1].body).toBe(JSON.stringify(input));
    expect(fetch.mock.calls[2][0]).toContain(`/overrides/${row.override_id}/cancel`); expect(fetch.mock.calls[2][1].body).toBeUndefined();
    expect(fetch.mock.calls[3][1].body).toBe(JSON.stringify({ expected_revision: 1, reason: "Return after readback" }));
  });
  it.each([{ ...input, execution_id: "latest" }, { ...input, duration_seconds: 0 }, { ...input, duration_seconds: 3601 }, { ...input, expected_revision: 0.5 }])("rejects invalid enrollment %#", async (request) => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch); await expect(createOverride("token", row.workspace_id, request)).rejects.toThrow(); expect(fetch).not.toHaveBeenCalled();
  });
  it.each([{ network_id: "other" }, { workspace_id: "other" }, { override_id: row.intent_id }, { status: "expired_successfully" }, { command_sha256: null }])("rejects mismatched acknowledgements %#", async (patch) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(envelope({ ...row, ...patch }))));
    await expect(actOnOverride("token", row.network_id, row.workspace_id, row.override_id, "cancel")).rejects.toThrow();
  });
  it.each([403, 409, 503])("does not retry failed restoration/return requests %s", async (status) => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ success: false, data: null, meta: {}, errors: { code: "BLOCKED", message: "Restoration unconfirmed" } }, { status })); vi.stubGlobal("fetch", fetch);
    await expect(actOnOverride("token", row.network_id, row.workspace_id, row.override_id, "return", { expected_revision: 1, reason: "Return" })).rejects.toMatchObject({ status });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
