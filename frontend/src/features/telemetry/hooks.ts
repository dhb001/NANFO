import { useQuery } from "@tanstack/react-query";
import { getDeviceTelemetry, getTelemetryHealth, getTelemetryHistory } from "@/features/telemetry/api";

export function useTelemetryHistory(
  token: string | null,
  query: { networkId?: string; workspaceId?: string; metric?: string; page?: number; pageSize?: number },
) {
  return useQuery({
    queryKey: ["telemetry", "history", token, query],
    queryFn: async () => {
      const response = await getTelemetryHistory(token as string, query);
      return response.data;
    },
    enabled: Boolean(token),
  });
}

export function useDeviceTelemetry(token: string | null, deviceId: string | null) {
  return useQuery({
    queryKey: ["telemetry", "device", token, deviceId],
    queryFn: async () => {
      const response = await getDeviceTelemetry(token as string, deviceId as string, 1, 100);
      return response.data;
    },
    enabled: Boolean(token && deviceId),
  });
}

export function useTelemetryHealth(token: string | null) {
  return useQuery({
    queryKey: ["telemetry", "health", token],
    queryFn: async () => {
      const response = await getTelemetryHealth(token as string);
      return response.data;
    },
    enabled: Boolean(token),
    refetchInterval: 10_000,
  });
}
