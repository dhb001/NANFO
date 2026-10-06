import { afterEach, describe, expect, it, vi } from "vitest";
import { getConfiguration, putConfiguration } from "./configurationApi";
import { configurationFixture } from "./operatorFixtures";
const data = configurationFixture();
const input = { network_id: data.network_id, expected_revision: data.revision, reason: "Maintenance", operational: data.operational, training: data.requested_training };
const envelope = (value: unknown) => ({ success: true, data: value, meta: {}, errors: null });
describe("ADR018 versioned configuration API", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("sends exact bounded settings and separate requested training with a revision", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(Response.json(envelope(data)))); vi.stubGlobal("fetch", fetch);
    await getConfiguration("token", data.network_id, data.workspace_id);
    await putConfiguration("token", data.workspace_id, input);
    expect(fetch.mock.calls[0][0]).toContain(`/autonomy/configuration?network_id=${data.network_id}`);
    expect(fetch.mock.calls[1][1]).toMatchObject({ method: "PUT", body: JSON.stringify(input) });
  });
  it.each([{ ...input, expected_revision: -1 }, { ...input, reason: " " },
    { ...input, operational: { ...data.operational, online_learning: false } },
    { ...input, operational: { ...data.operational, max_observation_age_seconds: 31 } },
    { ...input, operational: { ...data.operational, min_route_hold_seconds: 2 } },
    { ...input, operational: { ...data.operational, decision_interval_seconds: 1.5 } },
    { ...input, operational: { ...data.operational, min_confidence: 0.9 } },
    { ...input, operational: { ...data.operational, allow_uncalibrated_confidence: "yes" as unknown as boolean } },
    { ...input, operational: Object.fromEntries(Object.entries(data.operational).filter(([key]) => key !== "min_confidence")) as unknown as typeof data.operational },
    { ...input, training: { reward_weights: { goodput: NaN } } },
    { ...input, training: { reward_weights: { "unsupported/path": 1 } } },
    { ...input, production_dispatch: false },
  ])("rejects unsupported fields even when false and invalid settings %#", async (request) => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    await expect(putConfiguration("token", data.workspace_id, request)).rejects.toThrow(); expect(fetch).not.toHaveBeenCalled();
  });
  it.each([{ workspace_id: "other" }, { effective_training: { reward_weights: {} } }, { safety_merge: "disabled" }, { history: [null] },
    { allow_uncalibrated_confidence_honoured: undefined }, { operational: { ...data.operational, min_confidence: 0.5 } }])("fails closed on incompatible response %#", async (patch) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(envelope({ ...data, ...patch }))));
    await expect(getConfiguration("token", data.network_id, data.workspace_id)).rejects.toThrow();
  });
  it("does not retry revision conflict", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ success: false, data: null, meta: {}, errors: { code: "CONFIGURATION_REVISION_CONFLICT", message: "Refresh configuration" } }, { status: 409 })); vi.stubGlobal("fetch", fetch);
    await expect(putConfiguration("token", data.workspace_id, input)).rejects.toMatchObject({ status: 409 }); expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("accepts signed requested reward weights from the final backend schema", async () => {
    const signed = { ...data, requested_training: { reward_weights: { loss: -100, goodput: 100 } } };
    const fetch = vi.fn().mockResolvedValue(Response.json(envelope(signed))); vi.stubGlobal("fetch", fetch);
    expect((await putConfiguration("token", data.workspace_id, { ...input, training: signed.requested_training })).requested_training).toEqual(signed.requested_training);
  });
});
