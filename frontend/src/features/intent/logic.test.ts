import { describe, expect, it } from "vitest";
import {
  explainabilitySummary,
  intentSceneObjectId,
  isIntentTerminalStatus,
  mapExecutionDiagnostics,
  mapIntentLifecycle,
  shouldRefetchIntentFromRealtime,
  buildLabIntent,
  canCancelIntent,
} from "@/features/intent/logic";
import { intentConfidenceBandTone } from "@/shared/lib/statusTones";
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
  it("maps actual lab readback, reachability and rollback independently of legacy status", () => {
    const diagnostics = mapExecutionDiagnostics(createDetail({ execution_provenance: {
      verification: { readback_verified: true, readback_sha256: "a".repeat(64), probe: { sent: 3, received: 3 } },
      rollback: { verified: true, readback_sha256: "b".repeat(64) },
    } }));
    expect(diagnostics).toMatchObject({ verificationStatus: "readback verified", rollbackStatus: "verified",
      readbackSha256: "a".repeat(64), rollbackReadbackSha256: "b".repeat(64), probeSummary: "3/3 received",
      completionScope: "config_readback_and_reachability", noMutationVerified: false, rollbackAttempted: false });
  });

  it.each([false, "true", true])("does not promote incomplete or malformed explicit evidence (%s) via legacy fallback", (flag) => {
    expect(mapExecutionDiagnostics(createDetail({ execution_provenance: {
      verification: { readback_verified: flag, status: "passed", no_mutation_verified: "true", probe: { sent: 0, received: 0 } },
      rollback: { verified: flag, status: "completed", attempted: "true" },
    } }))).toMatchObject({ verificationStatus: "readback unverified", rollbackStatus: "unverified",
      completionScope: null, noMutationVerified: false, probeSummary: null, rollbackAttempted: false });
  });

  it("does not infer completion scope or rollback from no-mutation proof", () => {
    expect(mapExecutionDiagnostics(createDetail({ status: "execution_failed", execution_provenance: {
      verification: { no_mutation_verified: true }, rollback: null,
    } }))).toMatchObject({ noMutationVerified: true, verificationStatus: null, rollbackStatus: null, completionScope: null });
    expect(mapExecutionDiagnostics(createDetail({ execution_provenance: {} }))).toMatchObject({
      noMutationVerified: false, verificationStatus: null, rollbackStatus: null, completionScope: null,
    });
  });

  it("keeps explicit completion scope without inferring improvement from probes", () => {
    expect(mapExecutionDiagnostics(createDetail({ execution_provenance: { verification: {
      readback_verified: true, readback_sha256: "a".repeat(64), probe: { sent: 3, received: 2 },
    } } }))).toMatchObject({ probeSummary: "2/3 received", completionScope: null });
    expect(mapExecutionDiagnostics(createDetail({ execution_provenance: { verification: {
      completion_scope: "config_readback_and_reachability",
    } } })).completionScope).toBe("config_readback_and_reachability");
  });

  it("allows completed policy compensation but not restored, safely cancelled, or failed executions", () => {
    const completed = createDetail({ status: "execution_completed", execution_provenance: { execution_id: "job-1", phase: "completed" } });
    expect(canCancelIntent(completed)).toBe(true);
    expect(canCancelIntent({ ...completed, intent_payload: { constraints: { operation: "restore" } } })).toBe(false);
    expect(canCancelIntent({ ...completed, execution_provenance: { phase: "completed" } })).toBe(false);
    expect(canCancelIntent({ ...completed, status: "execution_failed" })).toBe(false);
    expect(canCancelIntent(createDetail({ execution_provenance: { phase: "cancelled", rollback: { verified: true, readback_sha256: "a".repeat(64) } } }))).toBe(false);
    expect(canCancelIntent(createDetail({ execution_provenance: { phase: "failed", verification: { no_mutation_verified: true } } }))).toBe(false);
    expect(canCancelIntent(createDetail({ execution_provenance: { phase: "uncertain", rollback: { verified: false } } }))).toBe(true);
  });

  it("builds complete paths and weights with optional DSCP using only ADR-010 fields", () => {
    expect(buildLabIntent({ operation: "multipath", sourceHost: "h1", destinationHost: "h4", paths: "s1 s2 s4\ns1,s3,s4", weights: "2, 1", rate: "", dscp: "63" })).toEqual({
      action: "reroute_path", scope: { source_host: "h1", destination_host: "h4" },
      constraints: { operation: "multipath", paths: [["s1", "s2", "s4"], ["s1", "s3", "s4"]], weights: [2, 1], rate_mbps: null, dscp: 63 },
    });
  });

  it.each(["shape", "police", "restore"] as const)("builds %s without stale routing parameters", (operation) => {
    expect(buildLabIntent({ operation, sourceHost: "h1", destinationHost: "h2", paths: "s1 s2", weights: "2", rate: "12.5", dscp: "" }).constraints).toEqual({
      operation, paths: [], rate_mbps: operation === "restore" ? null : 12.5, dscp: null,
    });
  });

  it("omits unspecified weights rather than inventing policy", () => {
    expect(buildLabIntent({ operation: "reroute", sourceHost: "h1", destinationHost: "h2", paths: "s1 s2", weights: "", rate: "", dscp: "" }).constraints).toEqual({
      operation: "reroute", paths: [["s1", "s2"]], rate_mbps: null, dscp: null,
    });
  });

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

  it("resolves confidence tones from the backend band, not a re-derived score threshold", () => {
    expect(intentConfidenceBandTone("95-100")).toBe("ok");
    expect(intentConfidenceBandTone("80-94")).toBe("ok");
    expect(intentConfidenceBandTone("60-79")).toBe("warn");
    expect(intentConfidenceBandTone("below_60")).toBe("danger");
    expect(intentConfidenceBandTone("high")).toBe("neutral");
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
    // The rest of the backend settled set (intent/models.py _SETTLED) also stops polling.
    for (const status of ["cancelled", "compensated", "execution_cancelled", "execution_compensated"]) {
      expect(isIntentTerminalStatus(status)).toBe(true);
    }
    expect(isIntentTerminalStatus("completed")).toBe(false);
  });

  it("decides whether to refetch from realtime deltas", () => {
    expect(shouldRefetchIntentFromRealtime(undefined, "execution_started")).toBe(true);
    expect(shouldRefetchIntentFromRealtime("execution_started", "execution_started")).toBe(false);
    expect(shouldRefetchIntentFromRealtime("execution_started", "execution_failed")).toBe(true);
    expect(shouldRefetchIntentFromRealtime("execution_started", "execution_cancelled")).toBe(true);
    expect(shouldRefetchIntentFromRealtime("execution_started", "unknown_state")).toBe(false);
    expect(shouldRefetchIntentFromRealtime("execution_started", undefined)).toBe(false);
  });

  it("maps verification and rollback diagnostics from execution provenance", () => {
    const diagnostics = mapExecutionDiagnostics(
      createDetail({
        status: "execution_failed",
        execution_provenance: {
          verification: { status: "failed" },
          rollback: {
            attempted: true,
            status: "completed",
            rollback_reference_id: "rbk-1",
          },
          failure_reason: "post_change_verification_failed",
          event_publication: { warning: "event_queue_unavailable" },
        },
      }),
    );

    expect(diagnostics.verificationStatus).toBe("failed");
    expect(diagnostics.rollbackStatus).toBe("completed");
    expect(diagnostics.rollbackAttempted).toBe(true);
    expect(diagnostics.rollbackReferenceId).toBe("rbk-1");
    expect(diagnostics.failureReason).toBe("post_change_verification_failed");
    expect(diagnostics.eventPublicationWarning).toBe("event_queue_unavailable");
  });

  it("prefers execution_summary over summary in explainability", () => {
    const summary = explainabilitySummary(
      createDetail({
        explainability: {
          summary: "fallback",
          execution_summary: "execution specific",
        },
      }),
    );
    expect(summary).toBe("execution specific");
  });
});
