import { describe, expect, it } from "vitest";
import { normalizeOrgSlug, shouldClearWorkspace } from "@/features/organizations/tenancy-logic";

describe("tenancy logic", () => {
  it("normalizes slug from explicit value", () => {
    expect(normalizeOrgSlug("ignored", " North America NOC ")).toBe("north-america-noc");
  });

  it("falls back to organization name and trims to max length", () => {
    const longName = "a".repeat(80);
    expect(normalizeOrgSlug(longName, "")).toHaveLength(63);
  });

  it("clears workspace only when org context is missing", () => {
    expect(shouldClearWorkspace(null, "workspace-1")).toBe(true);
    expect(shouldClearWorkspace("org-1", "workspace-1")).toBe(false);
    expect(shouldClearWorkspace(null, null)).toBe(false);
  });
});
