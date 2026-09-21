import { describe, expect, it } from "vitest";
import { diffSpatialScenes } from "./spatialHistory";
import { rfFixtureScene } from "./rfFixture.test-data";

describe("spatial restore diff", () => {
  it("shows additions/removals and changed fields in the restore direction, ignoring object ordering", () => {
    const target = structuredClone(rfFixtureScene);
    target.objects[0].position.x++;
    target.objects[0].parent_id = null;
    target.objects[1].object_id = "replacement-floor";
    expect(diffSpatialScenes(rfFixtureScene, target)).toEqual({
      added: ["replacement-floor"], removed: ["canonical floor / 1"],
      changed: [{ id: "canonical AP / 1", fields: ["parent_id", "position"] }],
    });
    expect(diffSpatialScenes(rfFixtureScene, { ...rfFixtureScene, objects: [...rfFixtureScene.objects].reverse() })).toEqual({ added: [], removed: [], changed: [] });
  });
});
