import { describe, expect, it } from "vitest";
import { displayValue } from "@/shared/lib/format";

describe("displayValue", () => {
  it("renders primitives as text and never '[object Object]'", () => {
    expect(displayValue("s1")).toBe("s1");
    expect(displayValue(0)).toBe("0");
    expect(displayValue(false)).toBe("false");
    expect(displayValue(null)).toBe("unavailable");
    expect(displayValue(undefined, "-")).toBe("-");
    expect(displayValue("")).toBe("unavailable");
    expect(displayValue({ port: 1 })).toBe('{"port":1}');
    expect(displayValue(["a"])).toBe('["a"]');
    expect(displayValue({ long: "x".repeat(500) })).toHaveLength(200);
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    expect(displayValue(cyclic)).toBe("unavailable");
  });
});
