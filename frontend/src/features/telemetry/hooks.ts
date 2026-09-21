import { useQuery } from "@tanstack/react-query";
import { getDeviceTelemetry, getTelemetryHealth, getTelemetryHistory } from "@/features/telemetry/api";
import { useAuthStore } from "@/shared/state/auth-store";
import { canReadTelemetryHealth } from "@/features/auth/permissions";
import { TelemetryHistoryQuery, TelemetryTimeRange } from "@/shared/types/telemetry";
import { useSessionScope } from "@/features/auth/sessionScope";

export function useTelemetryHistory(
  token: string | null,
  query: TelemetryHistoryQuery,
  enabled = true,
) {
  const session = useSessionScope();
  return useQuery({
    queryKey: ["telemetry", "history", session.key, session.authority, query],
    queryFn: async ({ signal }) => {
      const response = await session.read((credential) => getTelemetryHistory(credential, query, signal), signal);
      return response.data;
    },
    enabled: Boolean(token && (query.networkId || query.workspaceId)) && enabled,
  });
}

export function useDeviceTelemetry(token: string | null, deviceId: string | null, range: TelemetryTimeRange = {}, metric?: string, enabled = true) {
  const session = useSessionScope();
  return useQuery({
    queryKey: ["telemetry", "device", session.key, session.authority, deviceId, range, metric],
    queryFn: async ({ signal }) => {
      const response = await session.read((credential) => getDeviceTelemetry(credential, deviceId as string, 1, 100, metric, range, signal), signal);
      return response.data;
    },
    enabled: Boolean(token && deviceId) && enabled,
  });
}

export function useTelemetryHealth(token: string | null) {
  const session = useSessionScope();
  const allowed = useAuthStore((state) => canReadTelemetryHealth(state.profile));
  return useQuery({
    queryKey: ["telemetry", "health", session.key, session.authority],
    queryFn: async ({ signal }) => {
      const response = await session.read((credential) => getTelemetryHealth(credential, signal), signal);
      return response.data;
    },
    enabled: Boolean(token && allowed),
    refetchInterval: 10_000,
  });
}
