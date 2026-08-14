import { IntentDetailResult } from "@/shared/types/intent";

export interface LifecycleEvent {
  key: string;
  label: string;
  status: "success" | "failed" | "pending";
  timestamp?: string;
}

export interface IntentExecutionDiagnostics {
  verificationStatus: string | null;
  rollbackStatus: string | null;
  rollbackAttempted: boolean;
  rollbackReferenceId: string | null;
  failureReason: string | null;
  eventPublicationWarning: string | null;
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

export function mapExecutionDiagnostics(detail: IntentDetailResult): IntentExecutionDiagnostics {
  const provenance = detail.execution_provenance;

  const verificationRaw = provenance.verification;
  const verificationStatus =
    verificationRaw && typeof verificationRaw === "object" && "status" in verificationRaw
      ? String((verificationRaw as { status?: unknown }).status ?? "").trim() || null
      : null;

  const rollbackRaw = provenance.rollback;
  const rollbackStatus =
    rollbackRaw && typeof rollbackRaw === "object" && "status" in rollbackRaw
      ? String((rollbackRaw as { status?: unknown }).status ?? "").trim() || null
      : null;
  const rollbackAttempted =
    rollbackRaw && typeof rollbackRaw === "object" && "attempted" in rollbackRaw
      ? Boolean((rollbackRaw as { attempted?: unknown }).attempted)
      : false;
  const rollbackReferenceId =
    rollbackRaw && typeof rollbackRaw === "object" && "rollback_reference_id" in rollbackRaw
      ? String((rollbackRaw as { rollback_reference_id?: unknown }).rollback_reference_id ?? "").trim() || null
      : null;

  const failureReason =
    typeof provenance.failure_reason === "string" && provenance.failure_reason.trim()
      ? provenance.failure_reason.trim()
      : null;

  const eventPublicationRaw = provenance.event_publication;
  const eventPublicationWarning =
    eventPublicationRaw && typeof eventPublicationRaw === "object" && "warning" in eventPublicationRaw
      ? String((eventPublicationRaw as { warning?: unknown }).warning ?? "").trim() || null
      : null;

  return {
    verificationStatus,
    rollbackStatus,
    rollbackAttempted,
    rollbackReferenceId,
    failureReason,
    eventPublicationWarning,
  };
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
