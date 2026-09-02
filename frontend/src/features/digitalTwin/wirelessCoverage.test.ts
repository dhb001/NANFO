import { describe, expect, it } from "vitest";
import {
  deriveWirelessCoverageCells,
  WIRELESS_COVERAGE_POLICY_VERSION,
} from "@/features/digitalTwin/wirelessCoverage";
import type { TwinNode } from "@/features/digitalTwin/sceneAdapter";

function node(input: Partial<TwinNode> & { id: string; type: string }): TwinNode {
  return {
    id: input.id,
    hostname: input.hostname ?? input.id,
    type: input.type,
    status: input.status ?? "active",
    x: input.x ?? 0,
    y: input.y ?? 0,
    z: input.z ?? 0,
    spatialRefId: input.spatialRefId ?? null,
    congestion: input.congestion ?? {
      severity: "neutral",
      score: null,
      metrics: [],
      policyVersion: "v2.0.0",
      primaryPolicyId: null,
    },
  };
}

describe("wirelessCoverage", () => {
  it("derives coverage cells from wireless AP nodes only", () => {
    const cells = deriveWirelessCoverageCells([
      node({
        id: "ap-1",
        type: "wireless_ap",
        x: 2,
        y: 3,
        z: 4,
        congestion: {
          severity: "low",
          score: 0.2,
          metrics: [],
          policyVersion: "v2.0.0",
          primaryPolicyId: null,
        },
      }),
      node({ id: "sw-1", type: "access_switch" }),
    ]);

    expect(cells).toHaveLength(1);
    expect(cells[0].id).toBe("coverage:ap-1");
    expect(cells[0].sourceNodeId).toBe("ap-1");
    expect(cells[0].syntheticEstimate).toBe(true);
  });

  it("keeps deterministic ordering and bounded values", () => {
    const cells = deriveWirelessCoverageCells([
      node({ id: "ap-b", type: "wireless_ap", congestion: { severity: "high", score: 0.9, metrics: [], policyVersion: "v2.0.0", primaryPolicyId: null } }),
      node({ id: "ap-a", type: "wireless_ap", congestion: { severity: "neutral", score: null, metrics: [], policyVersion: "v2.0.0", primaryPolicyId: null } }),
    ]);

    expect(cells.map((cell) => cell.sourceNodeId)).toEqual(["ap-a", "ap-b"]);
    for (const cell of cells) {
      expect(cell.radius).toBeGreaterThanOrEqual(2.8);
      expect(cell.radius).toBeLessThanOrEqual(11.4);
      expect(cell.intensity).toBeGreaterThanOrEqual(0.18);
      expect(cell.intensity).toBeLessThanOrEqual(0.94);
    }
  });

  it("publishes the wireless coverage policy version", () => {
    expect(WIRELESS_COVERAGE_POLICY_VERSION).toBe("rf.material_attenuation.v1");
  });

  it("uses campus building attenuation metadata when provided", () => {
    const cells = deriveWirelessCoverageCells(
      [
        node({
          id: "ap-1",
          type: "wireless_ap",
          spatialRefId: "campus-a/building-1/f01/rack-1/ap-1",
          congestion: {
            severity: "neutral",
            score: null,
            metrics: [],
            policyVersion: "v2.0.0",
            primaryPolicyId: null,
          },
        }),
      ],
      {
        campusBuildings: [
          {
            id: "campus-a:building-1",
            campusKey: "campus-a",
            buildingKey: "building-1",
            label: "Building 1",
            geometry: "box",
            x: 0,
            z: 0,
            baseY: -2.3,
            width: 8,
            depth: 8,
            height: 8,
            floors: 3,
            nodeCount: 0,
            metadata: {
              floorKeys: ["f01", "f02", "f03"],
              nodeIds: [],
              wallMaterial: "concrete",
              attenuationDb: 14,
              source: "geojson",
            },
            footprint: [
              [-4, -4],
              [4, -4],
              [4, 4],
              [-4, 4],
            ],
          },
        ],
      },
    );

    expect(cells).toHaveLength(1);
    expect(cells[0].wallMaterial).toBe("concrete");
    expect(cells[0].attenuationDb).toBe(14);
    expect(cells[0].solverMode).toBe("rf_material_baseline");
  });
});
