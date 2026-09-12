import { describe, expect, it } from "vitest";
import { resolveChordNavigation, shouldIgnoreHotkeyTarget } from "@/shared/lib/hotkeys";

describe("hotkeys", () => {
  it("resolves autonomy navigation without changing the audit shortcut", () => {
    expect(resolveChordNavigation(null, "n").path).toBe("/ops/autonomy");
    expect(resolveChordNavigation("g", "n").path).toBe("/ops/autonomy");
    expect(resolveChordNavigation("g", "a").path).toBe("/ops/audit");
  });
  it("ignores editable input targets", () => {
    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    const select = document.createElement("select");

    expect(shouldIgnoreHotkeyTarget(input)).toBe(true);
    expect(shouldIgnoreHotkeyTarget(textarea)).toBe(true);
    expect(shouldIgnoreHotkeyTarget(select)).toBe(true);
  });

  it("resolves single-key navigation", () => {
    expect(resolveChordNavigation(null, "o")).toEqual({
      nextPrefix: null,
      path: "/ops/overview",
    });
    expect(resolveChordNavigation(null, "x")).toEqual({
      nextPrefix: null,
      path: null,
    });
    expect(resolveChordNavigation(null, "p")).toEqual({
      nextPrefix: null,
      path: "/ops/topology-analysis",
    });
    expect(resolveChordNavigation(null, "l")).toEqual({
      nextPrefix: null,
      path: "/ops/reliability",
    });
    expect(resolveChordNavigation(null, "u")).toEqual({
      nextPrefix: null,
      path: "/ops/plugins",
    });
    expect(resolveChordNavigation(null, "y")).toEqual({
      nextPrefix: null,
      path: "/ops/reports",
    });
  });

  it("resolves g-prefixed chord navigation", () => {
    expect(resolveChordNavigation(null, "g")).toEqual({
      nextPrefix: "g",
      path: null,
    });
    expect(resolveChordNavigation("g", "t")).toEqual({
      nextPrefix: null,
      path: "/ops/telemetry",
    });
    expect(resolveChordNavigation("g", "z")).toEqual({
      nextPrefix: null,
      path: null,
    });
    expect(resolveChordNavigation("g", "p")).toEqual({
      nextPrefix: null,
      path: "/ops/topology-analysis",
    });
    expect(resolveChordNavigation("g", "l")).toEqual({
      nextPrefix: null,
      path: "/ops/reliability",
    });
    expect(resolveChordNavigation("g", "u")).toEqual({
      nextPrefix: null,
      path: "/ops/plugins",
    });
    expect(resolveChordNavigation("g", "y")).toEqual({
      nextPrefix: null,
      path: "/ops/reports",
    });
  });
});
