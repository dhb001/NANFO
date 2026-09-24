import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { acknowledgeAlert, listAlerts, resolveAlert, getAlert, getAlertHistory } from "@/features/reliability/api";
import { useSessionScope } from "@/features/auth/sessionScope";
import { scopedKey } from "@/shared/lib/queryKeys";
import { useAuthStore } from "@/shared/state/auth-store";
import type { AlertListParams } from "@/shared/types/alerts";

// Keys: ["alerts", sessionKey, authority, options] and
// ["alerts", sessionKey, authority, "detail" | "history", id] (ADR-028: never the token).

export function useAlertsQuery(token: string | null, options: AlertListParams = {}, enabled = true) {
  const scope = useSessionScope();
  return useQuery({
    queryKey: scopedKey(scope, "alerts", options),
    queryFn: async ({ signal }) => (await scope.read((credential) => listAlerts(credential, options, signal), signal)).data,
    enabled: Boolean(token) && enabled,
  });
}

export function useAcknowledgeAlert(token: string | null) {
  return useAlertAction(token, acknowledgeAlert);
}

export function useResolveAlert(token: string | null) {
  return useAlertAction(token, resolveAlert);
}

function useAlertAction(token: string | null, action: typeof resolveAlert) {
  const queryClient = useQueryClient();
  const scope = useSessionScope();
  return useMutation({
    mutationFn: async (alertId: string) => {
      const credential = useAuthStore.getState().accessToken ?? token;
      if (!credential) {
        throw new Error("Authentication token is required.");
      }
      const response = await action(credential, alertId);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: scopedKey(scope, "alerts") });
    },
  });
}

export function useAlertDetail(token: string | null, id: string) {
  const scope = useSessionScope();
  return useQuery({
    queryKey: scopedKey(scope, "alerts", "detail", id),
    queryFn: async ({ signal }) => (await scope.read((credential) => getAlert(credential, id, signal), signal)).data,
    enabled: Boolean(token),
  });
}

export function useAlertHistory(token: string | null, id: string) {
  const scope = useSessionScope();
  return useQuery({
    queryKey: scopedKey(scope, "alerts", "history", id),
    queryFn: async ({ signal }) => (await scope.read((credential) => getAlertHistory(credential, id, signal), signal)).data,
    enabled: Boolean(token),
  });
}
