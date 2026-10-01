import { describe, expect, it } from "vitest";
import { ApiClientError, describeApiError, parseErrorDetails, toErrorMessage } from "@/shared/lib/errors";

describe("describeApiError (ADR-028 C2)", () => {
  it("adds actionable context for size, quota, outage and validation errors plus the request reference", () => {
    expect(describeApiError(new ApiClientError("Too large", "REQUEST_TOO_LARGE", 413))).toBe("Too large Reduce the size of the submitted content and try again.");
    expect(describeApiError(new ApiClientError("Quota", "REPORT_ORG_QUOTA_EXCEEDED", 507, { requestId: "req-1" })))
      .toBe("Quota The storage quota is exhausted. Remove unused items or ask an administrator to raise the quota; retrying will not help. Reference: req-1.");
    expect(describeApiError(new ApiClientError("Down", "DEPENDENCY_UNAVAILABLE", 503, { retryAfterMs: 2_500 }))).toBe("Down Retry in about 3 s.");
    expect(describeApiError(new ApiClientError("Down", "DEPENDENCY_UNAVAILABLE", 503))).toBe("Down Retry shortly.");
    expect(describeApiError(new ApiClientError("Invalid", "VALIDATION_ERROR", 422, { details: [{ loc: ["body", "filters", "max_rows"], type: "less_than_equal" }] })))
      .toBe("Invalid Check: filters.max_rows.");
    expect(describeApiError(new Error("plain"))).toBe("plain");
    expect(toErrorMessage("nope")).toBe("Unexpected error");
  });

  it("keeps only well-formed bounded location/type details (never input values)", () => {
    const details = parseErrorDetails([{ loc: ["body", 1, { x: 1 }], type: "missing", input: "secret" }, "junk", { loc: "body", type: "x" },
      ...Array.from({ length: 30 }, () => ({ loc: ["q"], type: "t" }))]);
    expect(details[0]).toEqual({ loc: ["body", 1], type: "missing" });
    expect(details).toHaveLength(18);
    expect(JSON.stringify(details)).not.toContain("secret");
  });
});
