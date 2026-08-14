import { apiRequest } from "@/shared/lib/api";
import {
  ExecuteIntentRequest,
  ExecuteIntentResult,
  IntentDetailResult,
  ValidateIntentRequest,
  ValidateIntentResult,
} from "@/shared/types/intent";

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

export function getIntentDetail(token: string, intentId: string, workspaceId: string) {
  return apiRequest<IntentDetailResult>(`/api/v1/intents/${intentId}?workspace_id=${workspaceId}`, {
    token,
  });
}
