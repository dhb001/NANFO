import { describe, expect, it } from "vitest";
import {
  DETERMINISTIC_SPATIAL_PROJECTION_PROVIDER,
  deriveDeterministicPlacement,
  parseSpatialRefPath,
} from "@/features/digitalTwin/spatialProjection";

describe("spatialProjection", () => {
  it("parses canonical spatial_ref_id hierarchy", () => {
    const parsed = parseSpatialRefPath("strathmore/sbs/f01/core/rtr-1");
    expect(parsed).not.toBeNull();
    expect(parsed?.campus).toBe("strathmore");
    expect(parsed?.building).toBe("sbs");
    expect(parsed?.floor).toBe("f01");
    expect(parsed?.rack).toBe("core");
    expect(parsed?.device).toBe("rtr-1");
  });

  it("returns deterministic projection from spatial_ref_id", () => {
    const first = deriveDeterministicPlacement("strathmore/sbs/f01/core/rtr-1", "device-a");
    const second = deriveDeterministicPlacement("strathmore/sbs/f01/core/rtr-1", "device-b");

    expect(first.mode).toBe("spatial_ref");
    expect(second.mode).toBe("spatial_ref");
    expect(first.x).toBeCloseTo(second.x, 10);
    expect(first.y).toBeCloseTo(second.y, 10);
    expect(first.z).toBeCloseTo(second.z, 10);
  });

  it("uses hash fallback when spatial_ref_id is missing", () => {
    const first = deriveDeterministicPlacement(null, "device-1");
    const second = deriveDeterministicPlacement(undefined, "device-1");

    expect(first.mode).toBe("hash_fallback");
    expect(second.mode).toBe("hash_fallback");
    expect(first.x).toBeCloseTo(second.x, 10);
    expect(first.y).toBeCloseTo(second.y, 10);
    expect(first.z).toBeCloseTo(second.z, 10);
  });

  it("exposes deterministic provider identity", () => {
    expect(DETERMINISTIC_SPATIAL_PROJECTION_PROVIDER.id).toBe("deterministic.spatial_ref.v1");
  });
});
