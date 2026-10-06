import { describe, expect, it } from "vitest";
import { formatCappedTotal, formatPageCount, formatRecordTotal, hasNextPage } from "./totals";

describe("telemetry totals (ADR-028 C12)", () => {
  it("shows capped totals as lower bounds", () => {
    expect(formatCappedTotal(10_000, true)).toBe("≥ 10000");
    expect(formatCappedTotal(42, false)).toBe("42");
    expect(formatCappedTotal(42, undefined)).toBe("42");
    expect(formatPageCount(10_000, 120, true)).toBe("≥ 84");
    expect(formatPageCount(0, 120, false)).toBe("1");
  });

  it("allows paging past a capped total only while pages are full", () => {
    expect(hasNextPage(84, 120, 10_000, 120, true)).toBe(true);
    expect(hasNextPage(85, 120, 10_000, 40, true)).toBe(false);
    expect(hasNextPage(1, 120, 122, 120, false)).toBe(true);
    expect(hasNextPage(2, 120, 122, 2, false)).toBe(false);
  });

  it("marks planner estimates", () => {
    expect(formatRecordTotal({ total_records: 5, total_records_estimated: true })).toBe("≈ 5");
    expect(formatRecordTotal({ total_records: 5 })).toBe("5");
  });
});
