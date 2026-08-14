import { useMutation, useQuery } from "@tanstack/react-query";
import { executeIntent, getIntentDetail, validateIntent } from "@/features/intent/api";
import { ExecuteIntentRequest, ValidateIntentRequest } from "@/shared/types/intent";

export function useValidateIntent(token: string | null) {
  return useMutation({
    mutationFn: (input: { request: ValidateIntentRequest; idempotencyKey?: string }) =>
      validateIntent(token as string, input.request, input.idempotencyKey).then((response) => response.data),
  });
}

export function useExecuteIntent(token: string | null) {
  return useMutation({
    mutationFn: (input: { request: ExecuteIntentRequest; idempotencyKey?: string }) =>
      executeIntent(token as string, input.request, input.idempotencyKey).then((response) => response.data),
  });
}

export function useIntentDetail(token: string | null, intentId: string | null, workspaceId: string | null) {
  return useQuery({
    queryKey: ["intent", token, intentId, workspaceId],
    queryFn: () => getIntentDetail(token as string, intentId as string, workspaceId as string).then((response) => response.data),
    enabled: Boolean(token && intentId && workspaceId),
    refetchInterval: 8_000,
  });
}
