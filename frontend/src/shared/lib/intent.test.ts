import { describe, expect, it } from "vitest";
import { canExecuteIntent, normalizeIntentStatus } from "@/shared/lib/intent";
import { IntentDetailResult } from "@/shared/types/intent";

function createDetail(status: string): IntentDetailResult {
  return {
    intent_id: "97e5432b-2994-47f0-8590-7a37b66c8fd5",
    workspace_id: "d8a790f8-c15d-4a4b-b8fd-5f6f56d7abf3",
    network_id: "9460722f-89a2-442d-9e5c-5f8503f6097e",
    status,
    intent_kind: "reroute_path",
    intent_payload: { action: "reroute_path" },
    validation_result: {},
    execution_provenance: {},
    explainability: {},
    confidence: { score: 0.8, band: "high", approval_required: false },
    idempotency_key: null,
    queue_status: "queued",
    stream_entry_id: null,
    warning: null,
    correlation_id: "cdabcfbd-ef5d-4470-a2e2-c9d451dba32f",
    requested_by_user_id: "d4f12e4d-8a67-4825-a50f-cfa0bf26db53",
    requested_at: "2026-08-13T10:00:00Z",
    created_at: "2026-08-13T10:00:00Z",
    updated_at: "2026-08-13T10:02:00Z",
  };
}

describe("intent helpers", () => {
  it("allows execute only on active statuses", () => {
    expect(canExecuteIntent(createDetail("validated"))).toBe(true);
    expect(canExecuteIntent(createDetail("execution_started"))).toBe(true);
    expect(canExecuteIntent(createDetail("execution_completed"))).toBe(false);
    expect(canExecuteIntent(createDetail("execution_failed"))).toBe(false);
    expect(canExecuteIntent(undefined)).toBe(false);
  });

  it("normalizes shorthand statuses", () => {
    expect(normalizeIntentStatus("completed")).toBe("execution_completed");
    expect(normalizeIntentStatus("failed")).toBe("execution_failed");
    expect(normalizeIntentStatus("execution_started")).toBe("execution_started");
  });
});
