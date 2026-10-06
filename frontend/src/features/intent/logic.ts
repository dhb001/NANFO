import { IntentDetailResult } from "@/shared/types/intent";
import { displayValue } from "@/shared/lib/format";

export interface LabActionInput {
  operation: "reroute" | "multipath" | "shape" | "police" | "restore";
  sourceHost: string;
  destinationHost: string;
  paths: string;
  weights: string;
  rate: string;
  dscp: string;
}

export function buildLabIntent(input: LabActionInput) {
  const routing = input.operation === "reroute" || input.operation === "multipath";
  return {
    action: routing ? "reroute_path" : "throttle_qos",
    scope: { source_host: input.sourceHost, destination_host: input.destinationHost },
    constraints: {
      operation: input.operation,
      paths: routing ? input.paths.split("\n").filter((line) => line.trim()).map((line) => line.trim().split(/[\s,]+/)) : [],
      ...(routing && input.weights.trim() ? { weights: input.weights.trim().split(/[\s,]+/).map(Number) } : {}),
      rate_mbps: input.operation === "shape" || input.operation === "police" ? Number(input.rate) : null,
      dscp: input.dscp.trim() ? Number(input.dscp) : null,
    },
  };
}

export interface LifecycleEvent {
  key: string;
  label: string;
  status: "success" | "failed" | "pending";
  timestamp?: string | undefined;
}

export interface IntentExecutionDiagnostics {
  verificationStatus: string | null;
  rollbackStatus: string | null;
  rollbackAttempted: boolean;
  rollbackReferenceId: string | null;
  failureReason: string | null;
  eventPublicationWarning: string | null;
  readbackSha256: string | null;
  rollbackReadbackSha256: string | null;
  probeSummary: string | null;
  completionScope: string | null;
  noMutationVerified: boolean;
}

// Backend `intents.status` value set (intent/models.py INTENT_STATUSES).
const knownIntentStatuses = new Set([
  "draft",
  "validated",
  "rejected",
  "execution_started",
  "execution_completed",
  "execution_failed",
  "cancelled",
  "compensated",
  "execution_cancelled",
  "execution_compensated",
]);

// Settled intents cannot change the network any more (intent/models.py _SETTLED).
const terminalIntentStatuses = new Set([
  "rejected", "execution_completed", "execution_failed",
  "cancelled", "compensated", "execution_cancelled", "execution_compensated",
]);

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
      label: detail.status === "execution_failed" ? "Execution Failed" : detail.status === "execution_completed" ? "Execution Completed" : "Awaiting terminal readback",
      status: detail.status === "execution_failed" ? "failed" : detail.status === "execution_completed" ? "success" : "pending",
      timestamp: detail.status === "execution_completed" ? completedAt : detail.status === "execution_failed" ? failedAt : undefined,
    },
  ];
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
  const verification = evidenceObject(provenance.verification);
  const rollback = evidenceObject(provenance.rollback);
  const probe = evidenceObject(verification.probe);
  const readbackSha256 = evidenceText(verification.readback_sha256);
  const rollbackReadbackSha256 = evidenceText(rollback.readback_sha256);
  const readbackVerified = verification.readback_verified === true && /^[a-f0-9]{64}$/.test(readbackSha256 ?? "");
  const rollbackVerified = rollback.verified === true && /^[a-f0-9]{64}$/.test(rollbackReadbackSha256 ?? "");
  // Explicit evidence takes precedence over historical status strings, including false/malformed values.
  const verificationStatus = "readback_verified" in verification
    ? readbackVerified ? "readback verified" : "readback unverified"
    : evidenceText(verification.status);
  const rollbackStatus = "verified" in rollback
    ? rollbackVerified ? "verified" : "unverified"
    : evidenceText(rollback.status);
  const rollbackAttempted = rollback.attempted === true;
  const rollbackReferenceId = evidenceText(rollback.rollback_reference_id);
  const sent = typeof probe.sent === "number" && Number.isInteger(probe.sent) && probe.sent > 0 ? probe.sent : null;
  const received = typeof probe.received === "number" && Number.isInteger(probe.received) && probe.received >= 0 ? probe.received : null;
  const validProbe = sent !== null && received !== null && received <= sent;
  const probeSummary = validProbe ? `${received}/${sent} received` : null;
  const completionScope = evidenceText(verification.completion_scope) ?? evidenceText(provenance.completion_scope) ??
    (readbackVerified && validProbe && received === sent ? "config_readback_and_reachability" : null);

  const failureReason =
    typeof provenance.failure_reason === "string" && provenance.failure_reason.trim()
      ? provenance.failure_reason.trim()
      : null;

  const eventPublicationRaw = provenance.event_publication;
  const eventPublicationWarning =
    eventPublicationRaw && typeof eventPublicationRaw === "object" && "warning" in eventPublicationRaw
      ? displayValue((eventPublicationRaw as { warning?: unknown }).warning, "").trim() || null
      : null;

  return {
    verificationStatus,
    rollbackStatus,
    rollbackAttempted,
    rollbackReferenceId,
    failureReason,
    eventPublicationWarning,
    readbackSha256,
    rollbackReadbackSha256,
    probeSummary,
    completionScope,
    noMutationVerified: verification.no_mutation_verified === true,
  };
}

function evidenceObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function evidenceText(value: unknown): string | null {
  return typeof value === "string" ? value.trim() || null : null;
}

export function canCancelIntent(detail: IntentDetailResult | null | undefined, requestPending = false): boolean {
  if (!detail) return false;
  const provenance = detail.execution_provenance;
  const diagnostics = mapExecutionDiagnostics(detail);
  if ((provenance.phase === "cancelled" || provenance.phase === "failed") &&
    (diagnostics.rollbackStatus === "verified" || diagnostics.noMutationVerified)) return false;
  if (detail.status === "execution_started") return true;
  if (detail.status === "validated") return requestPending;
  if (detail.status !== "execution_completed" || provenance.phase !== "completed" ||
    !evidenceText(provenance.execution_id) || diagnostics.rollbackStatus === "verified" || diagnostics.noMutationVerified) return false;
  // No active-policy flag is exposed. A completed non-restore job may be compensated; the server decides ownership.
  return evidenceObject(detail.intent_payload?.constraints).operation !== "restore";
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
