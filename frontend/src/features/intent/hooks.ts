import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { samePageSeries } from "@/shared/lib/queryKeys";
import { executeIntent, getIntentDetail, validateIntent, listIntents } from "@/features/intent/api";
import { ExecuteIntentRequest, ValidateIntentRequest } from "@/shared/types/intent";
import { useEffect } from "react";
import { isIntentTerminalStatus } from "@/features/intent/logic";
import { useLiveStore } from "@/features/realtime/store";
import { ApiClientError } from "@/shared/lib/errors";
import { useSessionScope } from "@/features/auth/sessionScope";

const MAX_DETAIL_READS = 40;

export function useIntentHistory(token: string | null, workspaceId: string | null, networkId: string | null, page: number) {
  const session = useSessionScope();
  const queryKey = ["intent", session.key, session.authority, "history", page];
  return useQuery({
    queryKey,
    queryFn: ({ signal }) => session.read((credential) => listIntents(credential, workspaceId!, networkId, page, signal), signal).then((response) => response.data),
    enabled: Boolean(token && workspaceId),
    placeholderData: (previous, previousQuery) => samePageSeries(previousQuery?.queryKey, queryKey, 4) ? keepPreviousData(previous) : undefined,
  });
}

export function useValidateIntent(token: string | null) {
  const session = useSessionScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { request: ValidateIntentRequest; idempotencyKey?: string }) =>
      session.request((credential) => validateIntent(credential || token!, input.request, input.idempotencyKey)).then((response) => response.data),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: ["intent", session.key] }),
  });
}

export function useExecuteIntent(token: string | null) {
  const session = useSessionScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { request: ExecuteIntentRequest; idempotencyKey?: string }) =>
      session.request((credential) => executeIntent(credential || token!, input.request, input.idempotencyKey)).then((response) => response.data),
    retry: false,
    // A long-idle validated view may have exhausted its polling budget before dispatch.
    onSettled: async (_data, _error, { request }) => {
      try { session.assertCurrent(); } catch { return; }
      await client.resetQueries({
        queryKey: ["intent", session.key, session.authority, request.intent_id, request.workspace_id], exact: true,
      });
      void client.invalidateQueries({ queryKey: ["intent", session.key, session.authority, "history"] });
    },
  });
}

export function useIntentDetail(token: string | null, intentId: string | null, workspaceId: string | null) {
  const session = useSessionScope();
  const connection = useLiveStore((state) => state.digitalTwinStatus);
  const query = useQuery({
    queryKey: ["intent", session.key, session.authority, intentId, workspaceId],
    queryFn: ({ signal }) => session.read((credential) => getIntentDetail(credential, intentId as string, workspaceId as string, signal), signal).then((response) => response.data),
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
    if (connection === "open" && intentId && workspaceId) void refetch();
  }, [connection, intentId, workspaceId, refetch]);
  return query;
}
