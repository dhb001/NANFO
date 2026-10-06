import { describe, expect, it } from "vitest";
import { etagSha256 } from "@/shared/lib/etag";

const hex = "ab".repeat(32);

describe("etagSha256 (ADR-028 C4/C5)", () => {
  it("reads the digest from current, legacy and weak validators", () => {
    expect(etagSha256(`"sha256:${hex}"`)).toBe(hex);
    expect(etagSha256(`W/"sha256:${hex}"`)).toBe(hex);
    expect(etagSha256(`"${hex}"`)).toBe(hex);
    expect(etagSha256(`W/"${hex.toUpperCase()}"`)).toBe(hex);
    expect(etagSha256(` "sha256:${hex}" `)).toBe(hex);
  });

  it("treats absent, opaque and malformed validators as no digest", () => {
    for (const value of [null, undefined, "", '"opaque"', `sha256:${hex}`, `"sha256:${hex.slice(1)}"`, `"md5:${hex}"`, `"sha256:${hex}0"`, `w/"${hex}"`]) {
      expect(etagSha256(value)).toBeNull();
    }
  });
});
