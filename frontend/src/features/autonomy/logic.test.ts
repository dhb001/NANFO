import { describe, expect, it } from "vitest";
import { buildAutonomyUpdate } from "./logic";

describe("autonomy input boundary", () => {
  const now = Date.parse("2026-09-09T12:00:00Z");
  it("defaults non-actuating configuration to nullable approval fields", () => {
    expect(buildAutonomyUpdate("network", "monitor", "", "", 7, now)).toEqual({
      network_id: "network", expected_revision: 7, mode: "monitor", checkpoint_sha256: null, approval_expires_at: null,
    });
  });
  it.each(["/models/best.json", "a".repeat(63), "g".repeat(64), "a".repeat(65)])("rejects invalid checkpoint %s", (hash) => {
    expect(() => buildAutonomyUpdate("network", "recommend", hash, "", 0, now)).toThrow(/64 hexadecimal/);
  });
  it.each(["invalid", "2026-09-09T12:00:00Z", "2026-09-08T12:00:00Z"])("rejects invalid or expired approval %s", (expiry) => {
    expect(() => buildAutonomyUpdate("network", "autonomous", "a".repeat(64), expiry, 0, now)).toThrow(/future/);
  });
  it.each(["monitor", "recommend"] as const)("discards expiry for non-actuating %s", (mode) => {
    expect(buildAutonomyUpdate("network", mode, "", "2026-09-08T12:00:00Z", 0, now).approval_expires_at).toBeNull();
  });
  it("requires exact model and expiry for autonomous requests and sends UTC", () => {
    expect(() => buildAutonomyUpdate("network", "autonomous", "", "", 0, now)).toThrow(/requires/);
    expect(buildAutonomyUpdate("network", "autonomous", "a".repeat(64), "2026-09-09T16:00:00+03:00", 12, now))
      .toEqual({ network_id: "network", expected_revision: 12, mode: "autonomous", checkpoint_sha256: "a".repeat(64), approval_expires_at: "2026-09-09T13:00:00.000Z" });
  });
  it.each([-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])("rejects invalid revision %s", (revision) => {
    expect(() => buildAutonomyUpdate("network", "monitor", "", "", revision, now)).toThrow(/revision/);
  });
});
