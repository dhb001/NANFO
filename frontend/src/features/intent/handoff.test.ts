import { describe, expect, it } from "vitest";
import { intentConflictGuidance, isUnknownOutcome } from "./conflicts";
import { INTENT_HANDOFF_STATE_KEY, intentHandoffState, readIntentHandoffState, readUntrustedIntentQuery } from "./handoff";
import { ApiClientError } from "@/shared/lib/errors";

describe("intent conflict guidance (ADR-028 C3/C18)", () => {
  it("maps each documented 409 code to operator guidance", () => {
    const codes = ["IDEMPOTENCY_KEY_REUSED", "INTENT_IDEMPOTENCY_CONFLICT", "APPROVAL_BINDING_MISMATCH", "DISTINCT_APPROVER_REQUIRED",
      "SIMULATION_REQUIRED", "SIMULATION_POLICY_VIOLATION", "SIMULATION_EVIDENCE_REJECTED", "INTENT_ALREADY_EXECUTING"];
    for (const code of codes) {
      const guidance = intentConflictGuidance(new ApiClientError("m", code, 409));
      expect(guidance?.code).toBe(code);
      expect(guidance?.title).toBeTruthy();
    }
    expect(intentConflictGuidance(new ApiClientError("m", "APPROVAL_BINDING_MISMATCH", 409))).toMatchObject({ refetchDetail: true, revokeApproval: true });
    expect(intentConflictGuidance(new ApiClientError("m", "IDEMPOTENCY_KEY_REUSED", 409))).toMatchObject({ refetchDetail: false, revokeApproval: false });
    // Unknown codes, other statuses and non-API errors get no invented guidance.
    expect(intentConflictGuidance(new ApiClientError("m", "SOMETHING_NEW", 409))).toBeNull();
    expect(intentConflictGuidance(new ApiClientError("m", "APPROVAL_BINDING_MISMATCH", 400))).toBeNull();
    expect(intentConflictGuidance(new Error("x"))).toBeNull();
  });

  it("treats lost responses, timeouts and server errors as unknown outcomes, refusals as known", () => {
    expect(isUnknownOutcome(new TypeError("Failed to fetch"))).toBe(true);
    expect(isUnknownOutcome(new ApiClientError("t", "API_TIMEOUT", 0))).toBe(true);
    expect(isUnknownOutcome(new ApiClientError("bad", "API_INVALID_RESPONSE", 200))).toBe(true);
    expect(isUnknownOutcome(new ApiClientError("down", "DEPENDENCY_UNAVAILABLE", 503))).toBe(true);
    expect(isUnknownOutcome(new ApiClientError("x", "HTTP_502", 502))).toBe(true);
    expect(isUnknownOutcome(new ApiClientError("no", "INTENT_NOT_EXECUTABLE", 409))).toBe(false);
    expect(isUnknownOutcome(new ApiClientError("no", "VALIDATION_ERROR", 422))).toBe(false);
    expect(isUnknownOutcome(new ApiClientError("no", "API_AUTHORITY_CHANGED", 403))).toBe(false);
    expect(isUnknownOutcome(new ApiClientError("no", "API_NO_SESSION"))).toBe(false);
  });
});

describe("intent handoff transport", () => {
  const prefill = { source: "digital-twin" as const, action: null, scopeJson: "{}", constraintsJson: "{}", contextSummary: "device=a" };

  it("round-trips router state as trusted in-app content", () => {
    const state = intentHandoffState(prefill);
    expect(Object.keys(state)).toEqual([INTENT_HANDOFF_STATE_KEY]);
    expect(readIntentHandoffState(state)).toEqual({ ...prefill, untrusted: false });
    expect(readIntentHandoffState(null)).toBeNull();
    expect(readIntentHandoffState({ intentHandoff: { ...prefill, source: "elsewhere" } })).toBeNull();
    expect(readIntentHandoffState({ intentHandoff: "nope" })).toBeNull();
  });

  it("marks query-string prefills untrusted and bounds their content", () => {
    const query = new URLSearchParams({ source: "digital-twin", action: "throttle_qos", scope: "{\"a\":1}", constraints: "{}", context_summary: "x".repeat(900) });
    const reading = readUntrustedIntentQuery(`?${query}`);
    expect(reading).toMatchObject({ untrusted: true, action: "throttle_qos", scopeJson: "{\"a\":1}" });
    expect(reading?.contextSummary).toHaveLength(500);
    expect(readUntrustedIntentQuery("?source=elsewhere&scope=%7B%7D")).toBeNull();
    // Unknown actions and oversized payloads are dropped, never forwarded.
    const hostile = new URLSearchParams({ source: "digital-twin", action: "drop_all_traffic", scope: "x".repeat(70_000) });
    expect(readUntrustedIntentQuery(`?${hostile}`)).toMatchObject({ action: null, scopeJson: "" });
  });
});
