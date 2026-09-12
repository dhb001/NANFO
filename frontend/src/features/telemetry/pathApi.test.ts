import { afterEach, describe, expect, it, vi } from "vitest";
import { getProbePaths, probeEvidenceFresh } from "./pathApi";
import { pathsFixture } from "./pathFixtures";
const data = pathsFixture();
describe("measured paths API", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("uses only the approved read with current network scope", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ success: true, data, meta: {}, errors: null })); vi.stubGlobal("fetch", fetch);
    expect(await getProbePaths("token", data.network_id, data.workspace_id)).toEqual(data);
    expect(fetch.mock.calls[0][0]).toContain(`/telemetry/paths?network_id=${data.network_id}`); expect(fetch.mock.calls[0][1].method).toBe("GET");
  });
  it.each([{ network_id: "other" }, { workspace_id: "other" }, { scope: "all_flows" }, { evidence_verification: null }, { window_start: null },
    { paths: [null] }, { max_age_seconds: 300 }, { paths: [{ ...data.paths[0], observed_hops: [{ device_id: "guessed-name" }] }] }])("rejects incompatible or unbound evidence %#", async (patch) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ success: true, data: { ...data, ...patch }, meta: {}, errors: null })));
    await expect(getProbePaths("token", data.network_id, data.workspace_id)).rejects.toThrow();
  });
  it("expires the full measured window without resetting server age", () => {
    expect(probeEvidenceFresh(data, 1000, 1001)).toBe(true);
    expect(probeEvidenceFresh(data, 1000, 29001)).toBe(false);
    expect(probeEvidenceFresh(data, 1000, 999)).toBe(false);
    expect(probeEvidenceFresh({ ...data, freshness: "stale" }, 1000, 1001)).toBe(false);
  });
});
