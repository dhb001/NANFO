import { keepPreviousData, useQuery, type QueryKey } from "@tanstack/react-query";
import { getDeviceTelemetry, getTelemetryHealth, getTelemetryHistory } from "@/features/telemetry/api";
import { useAuthStore } from "@/shared/state/auth-store";
import { canReadTelemetryHealth } from "@/features/auth/permissions";
import { TelemetryHistoryQuery, TelemetryTimeRange } from "@/shared/types/telemetry";
import { useSessionScope } from "@/features/auth/sessionScope";

/** Same session and filters, any page: previous rows stay visible while the next page loads. */
function sameHistorySeries(previous: QueryKey | undefined, next: QueryKey) {
  if (!previous || previous.length !== next.length) return false;
  const withoutPage = (key: QueryKey) => JSON.stringify(key.map((part, index) => index === 4 ? { ...(part as object), page: undefined } : part));
  return withoutPage(previous) === withoutPage(next);
}

export function useTelemetryHistory(
  token: string | null,
  query: TelemetryHistoryQuery,
  enabled = true,
) {
  const session = useSessionScope();
  const queryKey = ["telemetry", "history", session.key, session.authority, query];
  return useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const response = await session.read((credential) => getTelemetryHistory(credential, query, signal), signal);
      return response.data;
    },
    enabled: Boolean(token && (query.networkId || query.workspaceId)) && enabled,
    placeholderData: (previous, previousQuery) => sameHistorySeries(previousQuery?.queryKey, queryKey) ? keepPreviousData(previous) : undefined,
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
