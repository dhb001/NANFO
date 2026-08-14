import { IntentDetailResult } from "@/shared/types/intent";

export interface LifecycleEvent {
  key: string;
  label: string;
  status: "success" | "failed" | "pending";
  timestamp?: string;
}

const knownIntentStatuses = new Set([
  "validated",
  "rejected",
  "execution_started",
  "execution_completed",
  "execution_failed",
]);

const terminalIntentStatuses = new Set(["rejected", "execution_completed", "execution_failed"]);

export function mapIntentLifecycle(detail: IntentDetailResult): LifecycleEvent[] {
  const validationResult = detail.validation_result;
  const executionProvenance = detail.execution_provenance;
  const validatedAt = typeof validationResult.validated_at === "string" ? validationResult.validated_at : undefined;
  const startedAt =
    typeof executionProvenance.execution_started_at === "string" ? executionProvenance.execution_started_at : undefined;
  const completedAt =
    typeof executionProvenance.execution_completed_at === "string"
      ? executionProvenance.execution_completed_at
      : undefined;
  const failedAt =
    typeof executionProvenance.execution_failed_at === "string" ? executionProvenance.execution_failed_at : undefined;

  return [
    {
      key: "validated",
      label: "Validated",
      status: detail.status === "rejected" ? "failed" : "success",
      timestamp: validatedAt,
    },
    {
      key: "execution_started",
      label: "Execution Started",
      status: startedAt ? "success" : "pending",
      timestamp: startedAt,
    },
    {
      key: "execution_terminal",
      label: detail.status === "execution_failed" ? "Execution Failed" : "Execution Completed",
      status: detail.status === "execution_failed" ? "failed" : detail.status === "execution_completed" ? "success" : "pending",
      timestamp: completedAt ?? failedAt,
    },
  ];
}

export function resolveConfidenceTone(score: number): "ok" | "warn" | "danger" {
  if (score >= 0.8) {
    return "ok";
  }
  if (score >= 0.6) {
    return "warn";
  }
  return "danger";
}

export function explainabilitySummary(detail: IntentDetailResult): string {
  const explainability = detail.explainability;
  if (typeof explainability.execution_summary === "string" && explainability.execution_summary.trim()) {
    return explainability.execution_summary;
  }
  if (typeof explainability.summary === "string" && explainability.summary.trim()) {
    return explainability.summary;
  }
  return "No explainability summary provided.";
}

export function intentSceneObjectId(intentId: string): string {
  return `intent-${intentId}`;
}

export function isIntentTerminalStatus(status: string | undefined): boolean {
  if (!status) {
    return false;
  }
  return terminalIntentStatuses.has(status);
}

export function shouldRefetchIntentFromRealtime(
  currentStatus: string | undefined,
  realtimeStatus: string | undefined,
): boolean {
  if (!realtimeStatus || !knownIntentStatuses.has(realtimeStatus)) {
    return false;
  }
  if (!currentStatus) {
    return true;
  }
  return currentStatus !== realtimeStatus;
}
