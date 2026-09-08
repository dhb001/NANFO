import { useQuery } from "@tanstack/react-query";
import { getDeviceTelemetry, getTelemetryHealth, getTelemetryHistory } from "@/features/telemetry/api";
import { useAuthStore } from "@/shared/state/auth-store";
import { canReadTelemetryHealth } from "@/features/auth/permissions";
import { TelemetryHistoryQuery, TelemetryTimeRange } from "@/shared/types/telemetry";

export function useTelemetryHistory(
  token: string | null,
  query: TelemetryHistoryQuery,
  enabled = true,
) {
  return useQuery({
    queryKey: ["telemetry", "history", token, query],
    queryFn: async () => {
      const response = await getTelemetryHistory(token as string, query);
      return response.data;
    },
    enabled: Boolean(token && (query.networkId || query.workspaceId)) && enabled,
  });
}

export function useDeviceTelemetry(token: string | null, deviceId: string | null, range: TelemetryTimeRange = {}, metric?: string, enabled = true) {
  return useQuery({
    queryKey: ["telemetry", "device", token, deviceId, range, metric],
    queryFn: async () => {
      const response = await getDeviceTelemetry(token as string, deviceId as string, 1, 100, metric, range);
      return response.data;
    },
    enabled: Boolean(token && deviceId) && enabled,
  });
}

export function useTelemetryHealth(token: string | null) {
  const allowed = useAuthStore((state) => canReadTelemetryHealth(state.profile));
  return useQuery({
    queryKey: ["telemetry", "health", token],
    queryFn: async () => {
      const response = await getTelemetryHealth(token as string);
      return response.data;
    },
    enabled: Boolean(token && allowed),
    refetchInterval: 10_000,
  });
}
