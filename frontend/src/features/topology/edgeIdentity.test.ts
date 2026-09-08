import { describe, expect, it } from "vitest";
import { topologyEdgeIdentity } from "./edgeIdentity";

const base = { source_id: "a", target_id: "b", edge_type: "connected_to" };

describe("topology edge identity", () => {
  it("uses owner, edge key and both ports without transient metadata", () => {
    const metadata = { observation_owner: "lab", edge_key: "link", source_port: 0, target_port: 2 };
    const id = topologyEdgeIdentity({ ...base, metadata });
    expect(topologyEdgeIdentity({ ...base, metadata: { ...metadata, observed_at: "later" } })).toBe(id);
    for (const [key, value] of Object.entries(metadata)) {
      expect(topologyEdgeIdentity({ ...base, metadata: { ...metadata, [key]: `${value}-other` } })).not.toBe(id);
    }
    expect(topologyEdgeIdentity({ ...base, metadata: { source_port: 0 } })).not.toBe(topologyEdgeIdentity({ ...base, metadata: {} }));
  });
  it("only deduplicates identical legacy metadata, independent of object key order", () => {
    const id = topologyEdgeIdentity({ ...base, metadata: { a: 1, nested: { b: 2, c: 3 } } });
    expect(topologyEdgeIdentity({ ...base, metadata: { nested: { c: 3, b: 2 }, a: 1 } })).toBe(id);
    expect(topologyEdgeIdentity({ ...base, metadata: { a: 1 } })).not.toBe(id);
    expect(topologyEdgeIdentity({ ...base, metadata: { a: 2 } })).not.toBe(id);
  });
  it("keeps direction and delimiter-bearing endpoint identities distinct", () => {
    expect(topologyEdgeIdentity({ ...base, metadata: {} })).not.toBe(topologyEdgeIdentity({ ...base, source_id: "b", target_id: "a", metadata: {} }));
    expect(topologyEdgeIdentity({ ...base, source_id: "a:b", target_id: "c", metadata: {} })).not.toBe(topologyEdgeIdentity({ ...base, source_id: "a", target_id: "b:c", metadata: {} }));
  });
});
