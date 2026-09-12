import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { acknowledgeAlert, listAlerts, resolveAlert, getAlert, getAlertHistory } from "@/features/reliability/api";

interface UseAlertsQueryOptions {
  status?: "active" | "acknowledged" | "resolved";
  severity?: string;
  source?: string;
  correlationId?: string;
  search?: string;
  limit?: number;
}

export function useAlertsQuery(token: string | null, options: UseAlertsQueryOptions = {}) {
  return useQuery({
    queryKey: ["alerts", token, options],
    queryFn: async () => {
      const response = await listAlerts(token as string, options);
      return response.data;
    },
    enabled: Boolean(token),
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
  return useMutation({
    mutationFn: async (alertId: string) => {
      if (!token) {
        throw new Error("Authentication token is required.");
      }
      const response = await action(token, alertId);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts", token] });
    },
  });
}

export function useAlertDetail(token: string | null, id: string) {
  return useQuery({
    queryKey: ["alerts", token, "detail", id],
    queryFn: async () => (await getAlert(token as string, id)).data,
    enabled: Boolean(token),
  });
}

export function useAlertHistory(token: string | null, id: string) {
  return useQuery({
    queryKey: ["alerts", token, "history", id],
    queryFn: async () => (await getAlertHistory(token as string, id)).data,
    enabled: Boolean(token),
  });
}
