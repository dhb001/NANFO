import { describe, expect, it } from "vitest";
import {
  intentSceneObjectId,
  isIntentTerminalStatus,
  mapIntentLifecycle,
  resolveConfidenceTone,
  shouldRefetchIntentFromRealtime,
} from "@/features/intent/logic";
import { IntentDetailResult } from "@/shared/types/intent";

function createDetail(overrides: Partial<IntentDetailResult> = {}): IntentDetailResult {
  return {
    intent_id: "97e5432b-2994-47f0-8590-7a37b66c8fd5",
    workspace_id: "d8a790f8-c15d-4a4b-b8fd-5f6f56d7abf3",
    network_id: "9460722f-89a2-442d-9e5c-5f8503f6097e",
    status: "execution_started",
    intent_kind: "reroute_path",
    intent_payload: { action: "reroute_path" },
    validation_result: {
      validated_at: "2026-08-13T10:00:00Z",
    },
    execution_provenance: {
      execution_started_at: "2026-08-13T10:01:00Z",
      execution_completed_at: "2026-08-13T10:02:00Z",
    },
    explainability: { summary: "ready" },
    confidence: {
      score: 0.82,
      band: "high",
      approval_required: false,
    },
    idempotency_key: "idem-1",
    queue_status: "queued",
    stream_entry_id: "174",
    warning: null,
    correlation_id: "cdabcfbd-ef5d-4470-a2e2-c9d451dba32f",
    requested_by_user_id: "d4f12e4d-8a67-4825-a50f-cfa0bf26db53",
    requested_at: "2026-08-13T10:00:00Z",
    created_at: "2026-08-13T10:00:00Z",
    updated_at: "2026-08-13T10:02:00Z",
    ...overrides,
  };
}

describe("intent logic", () => {
  it("maps lifecycle for terminal success", () => {
    const lifecycle = mapIntentLifecycle(createDetail({ status: "execution_completed" }));
    expect(lifecycle).toHaveLength(3);
    expect(lifecycle[0].status).toBe("success");
    expect(lifecycle[2].label).toBe("Execution Completed");
    expect(lifecycle[2].status).toBe("success");
  });

  it("maps lifecycle for rejection and failure", () => {
    const rejected = mapIntentLifecycle(
      createDetail({
        status: "rejected",
        execution_provenance: {},
      }),
    );
    expect(rejected[0].status).toBe("failed");
    expect(rejected[2].status).toBe("pending");

    const failed = mapIntentLifecycle(
      createDetail({
        status: "execution_failed",
        execution_provenance: {
          execution_started_at: "2026-08-13T10:01:00Z",
          execution_failed_at: "2026-08-13T10:03:00Z",
        },
      }),
    );
    expect(failed[2].label).toBe("Execution Failed");
    expect(failed[2].status).toBe("failed");
  });

  it("resolves confidence tones", () => {
    expect(resolveConfidenceTone(0.9)).toBe("ok");
    expect(resolveConfidenceTone(0.64)).toBe("warn");
    expect(resolveConfidenceTone(0.33)).toBe("danger");
  });

  it("maps scene object id", () => {
    expect(intentSceneObjectId("abc-123")).toBe("intent-abc-123");
  });

  it("tracks terminal statuses", () => {
    expect(isIntentTerminalStatus("validated")).toBe(false);
    expect(isIntentTerminalStatus("execution_started")).toBe(false);
    expect(isIntentTerminalStatus("rejected")).toBe(true);
    expect(isIntentTerminalStatus("execution_completed")).toBe(true);
    expect(isIntentTerminalStatus("execution_failed")).toBe(true);
    expect(isIntentTerminalStatus(undefined)).toBe(false);
  });

  it("decides whether to refetch from realtime deltas", () => {
    expect(shouldRefetchIntentFromRealtime(undefined, "execution_started")).toBe(true);
    expect(shouldRefetchIntentFromRealtime("execution_started", "execution_started")).toBe(false);
    expect(shouldRefetchIntentFromRealtime("execution_started", "execution_failed")).toBe(true);
    expect(shouldRefetchIntentFromRealtime("execution_started", "unknown_state")).toBe(false);
    expect(shouldRefetchIntentFromRealtime("execution_started", undefined)).toBe(false);
  });
});
