import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { executeIntent, getIntentDetail, validateIntent } from "@/features/intent/api";
import { ExecuteIntentRequest, ValidateIntentRequest } from "@/shared/types/intent";
import { useEffect } from "react";
import { isIntentTerminalStatus } from "@/features/intent/logic";
import { useLiveStore } from "@/features/realtime/store";
import { ApiClientError } from "@/shared/lib/errors";

const MAX_DETAIL_READS = 40;

export function useValidateIntent(token: string | null) {
  return useMutation({
    mutationFn: (input: { request: ValidateIntentRequest; idempotencyKey?: string }) =>
      validateIntent(token as string, input.request, input.idempotencyKey).then((response) => response.data),
  });
}

export function useExecuteIntent(token: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { request: ExecuteIntentRequest; idempotencyKey?: string }) =>
      executeIntent(token as string, input.request, input.idempotencyKey).then((response) => response.data),
    // A long-idle validated view may have exhausted its polling budget before dispatch.
    onSettled: (_data, _error, { request }) => client.resetQueries({
      queryKey: ["intent", token, request.intent_id, request.workspace_id], exact: true,
    }),
  });
}

export function useIntentDetail(token: string | null, intentId: string | null, workspaceId: string | null) {
  const connection = useLiveStore((state) => state.digitalTwinStatus);
  const query = useQuery({
    queryKey: ["intent", token, intentId, workspaceId],
    queryFn: () => getIntentDetail(token as string, intentId as string, workspaceId as string).then((response) => response.data),
    enabled: Boolean(token && intentId && workspaceId),
    retry: false,
    refetchInterval: (query) => {
      const { data, error, dataUpdateCount, errorUpdateCount } = query.state;
      const reads = dataUpdateCount + errorUpdateCount;
      if (isIntentTerminalStatus(data?.status) || reads >= MAX_DETAIL_READS ||
        (error instanceof ApiClientError && (error.status === 401 || error.status === 403))) return false;
      return Math.min(1_000 * 2 ** Math.min(reads, 4), 15_000);
    },
  });
  const { refetch } = query;
  useEffect(() => {
    if (connection === "open" && token && intentId && workspaceId) void refetch();
  }, [connection, token, intentId, workspaceId, refetch]);
  return query;
}
