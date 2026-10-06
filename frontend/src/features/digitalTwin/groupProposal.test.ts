import { describe, expect, it } from "vitest";
import type { DeviceGroupRecord } from "@/shared/types/network";
import { describeGroupConflicts, deriveGroupProposal } from "./groupProposal";

const node = (id: string, persistedSpatialRefId: string | null) => ({ id, persistedSpatialRefId });
const group = (group_key: string, overrides: Partial<DeviceGroupRecord> = {}): DeviceGroupRecord => ({
  device_group_id: `row-${group_key}`, network_id: "n", group_key, name: "Existing", group_type: "functional", description: null,
  selector: { functional_group: "wireless" }, device_ids: ["a"], created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-02T10:00:00.123456Z", ...overrides,
});

describe("derived device-group proposal", () => {
  const nodes = [
    node("a", "campus-a/building-1/f01/wireless/ap-1"),
    node("b", "campus-a/building-1/f01/access/sw-1"),
    node("c", "campus-a/building-2/f02/wireless/ap-2"),
  ];

  it("uses the focused scope and lets the server resolve membership from selectors", () => {
    const proposal = deriveGroupProposal({ nodes, focus: { buildingId: "campus-a:building-1", floorKey: "f01" }, existingGroups: [] });
    expect(proposal.scope).toEqual({ source: "focus", sitePrefix: "campus-a/building-1/f01", buildingId: "campus-a:building-1", floorKey: "f01", label: "BUILDING-1 F01" });
    expect(proposal.groups.map((item) => item.input)).toEqual([
      { group_key: "wireless-campus-a-building-1-f01", name: "BUILDING-1 F01 Wireless", group_type: "functional",
        selector: { functional_group: "wireless", site_prefix: "campus-a/building-1/f01" }, device_ids: [] },
      { group_key: "ops-campus-a-building-1-f01", name: "BUILDING-1 F01 Operations", group_type: "operational",
        selector: { site_prefix: "campus-a/building-1/f01" }, device_ids: [] },
    ]);
    expect(proposal.groups.every((item) => item.action === "create" && !("expected_updated_at" in item.input))).toBe(true);
    expect(proposal.persistedDevicesInScope).toBe(2);
    expect(proposal.blockedReason).toBeNull();
  });

  it("ignores session-only sidecar mappings entirely", () => {
    // Only the persisted reference counts; b/c have session-only mappings (not visible here).
    const sessionHeavy = [node("a", "campus-a/building-9/f03/x/a"), node("b", null), node("c", null), node("d", null)];
    const proposal = deriveGroupProposal({ nodes: sessionHeavy, focus: { buildingId: null, floorKey: null }, existingGroups: [] });
    expect(proposal.scope).toMatchObject({ source: "persisted_majority", sitePrefix: "campus-a/building-9/f03" });
    expect(proposal.devicesWithoutPersistedRef).toBe(3);
    const focusedOnSessionBuilding = deriveGroupProposal({ nodes: sessionHeavy, focus: { buildingId: "campus-a:session-only", floorKey: null }, existingGroups: [] });
    expect(focusedOnSessionBuilding.blockedReason).toMatch(/persisted spatial_ref_id/);
    expect(focusedOnSessionBuilding.scope.sitePrefix).toBeNull();
  });

  it("uses the stored reference casing so the server's prefix comparison matches", () => {
    const proposal = deriveGroupProposal({ nodes: [node("a", "Campus A/Main Hall/F01/r1/a")], focus: { buildingId: null, floorKey: null }, existingGroups: [] });
    expect(proposal.scope.sitePrefix).toBe("campus a/main hall/f01");
    expect(proposal.groups[1].input.group_key).toBe("ops-campus-a-main-hall-f01");
  });

  it("falls back to network-wide groups with explicit members only when no selector applies", () => {
    const proposal = deriveGroupProposal({ nodes: [node("z", null), node("a", null), node("a", null)], focus: { buildingId: null, floorKey: null }, existingGroups: [] });
    expect(proposal.scope).toMatchObject({ source: "network", sitePrefix: null, label: "Network" });
    expect(proposal.groups[0].input).toMatchObject({ group_key: "wireless-network", selector: { functional_group: "wireless" }, device_ids: [] });
    expect(proposal.groups[1].input).toMatchObject({ group_key: "ops-network", selector: {}, device_ids: ["a", "z"] });
  });

  it("sends expected_updated_at verbatim for existing keys and previews the change", () => {
    const existing = [group("wireless-campus-a-building-1-f01", { name: "Old name" }), group("unrelated")];
    const proposal = deriveGroupProposal({ nodes, focus: { buildingId: "campus-a:building-1", floorKey: "f01" }, existingGroups: existing });
    expect(proposal.groups[0]).toMatchObject({ action: "update", input: { expected_updated_at: "2026-09-02T10:00:00.123456Z" } });
    expect(proposal.groups[0].changes).toEqual(['name "Old name" -> "BUILDING-1 F01 Wireless"', "selector changed", "members re-resolved by the server (currently 1)"]);
    expect(proposal.groups[1]).toMatchObject({ action: "create", existing: null });
    expect(proposal.groups[1].input).not.toHaveProperty("expected_updated_at");
  });

  it("blocks empty topologies", () => {
    expect(deriveGroupProposal({ nodes: [], focus: { buildingId: null, floorKey: null }, existingGroups: [] }).blockedReason).toBe("No devices in the current topology.");
  });
});

describe("group conflict diff", () => {
  it("reports created, deleted and modified groups with changed fields", () => {
    const before = [group("k1"), group("k2"), group("k4")];
    const after = [
      group("k1", { updated_at: "2026-09-03T00:00:00Z", name: "Renamed", device_ids: ["a", "b"] }),
      group("k3", { updated_at: "2026-09-03T00:00:00Z" }),
      group("k4"),
    ];
    expect(describeGroupConflicts(before, after, ["k1", "k2", "k3", "k4", "k5"])).toEqual([
      { groupKey: "k1", change: "modified", fields: ["name", "device_ids"], previousUpdatedAt: "2026-09-02T10:00:00.123456Z", currentUpdatedAt: "2026-09-03T00:00:00Z", previousMembers: 1, currentMembers: 2 },
      { groupKey: "k2", change: "deleted", fields: [], previousUpdatedAt: "2026-09-02T10:00:00.123456Z", currentUpdatedAt: null, previousMembers: 1, currentMembers: null },
      { groupKey: "k3", change: "created", fields: [], previousUpdatedAt: null, currentUpdatedAt: "2026-09-03T00:00:00Z", previousMembers: null, currentMembers: 1 },
    ]);
  });
});
