import { IntentDetailResult } from "@/shared/types/intent";

const activeStatuses = new Set(["validated", "execution_started"]);

export function canExecuteIntent(detail: IntentDetailResult | null | undefined): boolean {
  if (!detail) {
    return false;
  }
  return activeStatuses.has(detail.status);
}

export function normalizeIntentStatus(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (normalized === "completed") {
    return "execution_completed";
  }
  if (normalized === "failed") {
    return "execution_failed";
  }
  return normalized;
}
