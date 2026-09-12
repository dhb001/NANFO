import { describe, expect, it } from "vitest";
import { mapMeasuredPath } from "./measuredPathMapping";
import type { TwinLink, TwinNode } from "./sceneAdapter";

const nodes = [{ id: "a", x: 0, y: 0, z: 0 }, { id: "b", x: 2, y: 0, z: 1 }] as TwinNode[];
const links = [{ id: "canonical-link", sourceId: "a", targetId: "b" }] as TwinLink[];
describe("measured path scene mapping", () => {
  it("preserves the observed direction even on a reverse-oriented scene link", () => {
    expect(mapMeasuredPath(["b", "a"], ["canonical-link"], nodes, links)).toEqual([
      { id: "0:canonical-link", source: [2, 0, 1], target: [0, 0, 0] },
    ]);
  });
  it.each([
    [["a", null], ["canonical-link"]], [["a", "unknown"], ["canonical-link"]],
    [["a", "b"], ["a:b"]], [["a", "b"], []], [["a", "a"], ["canonical-link"]],
  ])("retains list fallback for missing/unaligned canonical identities %j", (nodeIds, linkIds) => {
    expect(mapMeasuredPath(nodeIds, linkIds, nodes, links)).toBeNull();
  });
  it("rejects ambiguous or mismatched scene edges", () => {
    expect(mapMeasuredPath(["a", "b"], ["canonical-link"], nodes, [...links, ...links])).toBeNull();
    expect(mapMeasuredPath(["a", "b"], ["canonical-link"], nodes, [{ ...links[0], targetId: "c" }])).toBeNull();
    expect(mapMeasuredPath(["a", "b"], ["canonical-link"], [nodes[0], { ...nodes[1], x: NaN }], links)).toBeNull();
  });
});
