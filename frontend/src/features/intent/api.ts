import { apiRequest } from "@/shared/lib/api";
import {
  ExecuteIntentRequest,
  ExecuteIntentResult,
  IntentDetailResult,
  ValidateIntentRequest,
  ValidateIntentResult,
  IntentHistory,
} from "@/shared/types/intent";

export function listIntents(token: string, workspaceId: string, networkId: string | null, page = 1, signal?: AbortSignal) {
  const params = new URLSearchParams({ workspace_id: workspaceId, page: String(page), page_size: "20" });
  if (networkId) params.set("network_id", networkId);
  return apiRequest<IntentHistory>(`/api/v1/intents?${params}`, { token, signal });
}

export function validateIntent(token: string, body: ValidateIntentRequest, idempotencyKey?: string) {
  return apiRequest<ValidateIntentResult>("/api/v1/intents/validate", {
    method: "POST",
    body,
    token,
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
  });
}

export function executeIntent(token: string, body: ExecuteIntentRequest, idempotencyKey?: string) {
  return apiRequest<ExecuteIntentResult>("/api/v1/intents/execute", {
    method: "POST",
    body,
    token,
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
  });
}

export function getIntentDetail(token: string, intentId: string, workspaceId: string, signal?: AbortSignal) {
  return apiRequest<IntentDetailResult>(`/api/v1/intents/${intentId}?workspace_id=${workspaceId}`, {
    token,
    signal,
  });
}
