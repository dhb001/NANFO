import { afterEach, describe, expect, it, vi } from "vitest";
import { getSpatialScene, putSpatialScene, getSpatialHistory, getSpatialRevision } from "./spatialApi";
import { EMPTY_SPATIAL_SCENE } from "./spatialScene";

describe("spatial wire integration", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("unwraps the canonical envelope and sends the exact revision-guarded replacement", async () => {
    const snapshot = { ...EMPTY_SPATIAL_SCENE, revision: 1 };
    const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ success: true, data: snapshot, meta: {}, errors: null })));
    vi.stubGlobal("fetch", fetch);
    expect(await getSpatialScene("spatial-test-token", "n/1")).toEqual(snapshot);
    expect(fetch.mock.calls[0][0]).toContain("/api/v1/networks/n%2F1/spatial-scene");
    const body = { expected_revision: 0, scene: EMPTY_SPATIAL_SCENE };
    await putSpatialScene("spatial-test-token", "n", body);
    expect(fetch.mock.calls[1][1]).toMatchObject({ method: "PUT", body: JSON.stringify(body), headers: { Authorization: "Bearer spatial-test-token", "Content-Type": "application/json" } });
  });
  it("rejects malformed snapshots and retains HTTP conflict identity", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ success: true, data: { ...EMPTY_SPATIAL_SCENE, revision: "1" }, meta: {}, errors: null })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: false, data: null, meta: {}, errors: { code: "SPATIAL_REVISION_CONFLICT", message: "Conflict" } }), { status: 409 }));
    vi.stubGlobal("fetch", fetch);
    await expect(getSpatialScene("spatial-test-token", "n")).rejects.toThrow("Invalid scene revision");
    await expect(putSpatialScene("spatial-test-token", "n", { expected_revision: 0, scene: EMPTY_SPATIAL_SCENE })).rejects.toMatchObject({ status: 409 });
  });
  it("uses documented history pagination and validates revision-body identity", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ success: true, data: { items: [], total: 21, page: 2, page_size: 20 }, meta: {}, errors: null })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: true, data: { ...EMPTY_SPATIAL_SCENE, revision: 9 }, meta: {}, errors: null })));
    vi.stubGlobal("fetch", fetch);
    expect((await getSpatialHistory("spatial-test-token", "n", 2)).total).toBe(21);
    expect(fetch.mock.calls[0][0]).toContain("/spatial-scene/history?page=2&page_size=20");
    await expect(getSpatialRevision("spatial-test-token", "n", 1)).rejects.toThrow("revision mismatch");
  });
});
