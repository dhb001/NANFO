import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { acknowledgeAlert, listAlerts, resolveAlert } from "@/features/reliability/api";

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
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (alertId: string) => {
      if (!token) {
        throw new Error("Authentication token is required.");
      }
      const response = await acknowledgeAlert(token, alertId);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts", token] });
    },
  });
}

export function useResolveAlert(token: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (alertId: string) => {
      if (!token) {
        throw new Error("Authentication token is required.");
      }
      const response = await resolveAlert(token, alertId);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts", token] });
    },
  });
}
