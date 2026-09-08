import { describe, expect, it } from "vitest";
import { validateHistoryFilters } from "./historyFilters";

describe("history filters", () => {
  it.each([
    ["bad", "", "", "", 60],
    ["2026-09-08T00:00:00Z", "2026-09-08T00:00:00Z", "", "", 60],
    ["2026-09-09T00:00:00Z", "2026-09-08T00:00:00Z", "", "", 60],
    ["", "", "cpu", "avg", 60],
    ["2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", " ", "avg", 60],
    ["2026-09-01T00:00:00Z", "2026-09-08T00:00:01Z", "cpu", "avg", 60],
    ["2026-09-08T00:00:00Z", "2026-09-08T01:00:00Z", "cpu", "avg", 0],
    ["2026-09-08T00:00:00Z", "2026-09-08T01:00:00Z", "cpu", "avg", 86401],
    ["2026-09-08T00:00:00Z", "2026-09-08T01:00:00Z", "cpu", "avg", 1.5],
  ] as const)("rejects invalid inputs %s %s %s %s %s", (start, end, metric, aggregation, bucket) => {
    expect(validateHistoryFilters(start, end, metric, aggregation, bucket)).not.toBeNull();
  });
  it("allows raw open bounds and exact maximum aggregation window", () => {
    expect(validateHistoryFilters("", "", "", "", 60)).toBeNull();
    expect(validateHistoryFilters("", "2026-09-08T00:00:00Z", "", "", 60)).toBeNull();
    expect(validateHistoryFilters("2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", "cpu", "avg", 86400)).toBeNull();
  });

  it("rejects flow aggregation but permits raw flow history", () => {
    expect(validateHistoryFilters("", "", "flow_byte_count", "sum", 60)).toContain("no durable flow match identity");
    expect(validateHistoryFilters("", "", "flow_byte_count", "", 60)).toBeNull();
  });
});
