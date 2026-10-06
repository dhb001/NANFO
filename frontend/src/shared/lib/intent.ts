import { IntentDetailResult } from "@/shared/types/intent";

const activeStatuses = new Set(["validated", "execution_started"]);

export function canExecuteIntent(detail: IntentDetailResult | null | undefined): boolean {
  if (!detail) {
    return false;
  }
  return activeStatuses.has(detail.status);
}
