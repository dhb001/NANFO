import { useMemo } from "react";
import { useTopologyGraph } from "@/features/topology/hooks";
import { useAlertsQuery } from "@/features/reliability/hooks";
import { hasPermission } from "@/features/auth/permissions";
import { useLiveStore } from "@/features/realtime/store";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useTwinLiveCongestion, useTwinOverlays, useTwinTopology } from "./hooks";
import { useSpatialScene } from "./spatialHooks";
import { applySpatialScene } from "./spatialScene";
import { activeAlertDeviceIds, deriveDeviceAlertStates } from "./twinSeverity";
import { resolveViewportStatus } from "./twinViewportStatus";

export const TWIN_ALERT_LIMIT = 200;

/**
 * All server/realtime data the Twin renders, split by change rate:
 * - `scene` (topology + canonical placement) is memoized by topology revision and spatial
 *   scene only, so telemetry never rebuilds geometry;
 * - `congestionByDevice` (visual heuristic) updates in animation-frame batches;
 * - `alertStates` (authoritative severity) merges the REST snapshot with realtime deltas.
 */
export function useTwinSceneData(sessionMapping?: Record<string, string>) {
  const token = useAuthStore((state) => state.accessToken);
  const profile = useAuthStore((state) => state.profile);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const graphQuery = useTopologyGraph(token, networkId);
  const spatialQuery = useSpatialScene(token, networkId, hasPermission(profile, "read:topology"));
  const alertsEnabled = Boolean(networkId && hasPermission(profile, "read:telemetry"));
  const alertsQuery = useAlertsQuery(token, {
    status: "active", limit: TWIN_ALERT_LIMIT, ...(networkId ? { networkId } : {}), ...(workspaceId ? { workspaceId } : {}),
  }, alertsEnabled);
  const baseGraph = graphQuery.data?.data;
  const topology = useTwinTopology(baseGraph?.nodes, baseGraph?.edges, sessionMapping);
  const scene = useMemo(() => applySpatialScene(topology, spatialQuery.data), [topology, spatialQuery.data]);
  const overlays = useTwinOverlays();
  const congestionByDevice = useTwinLiveCongestion();
  const liveAlerts = useLiveStore((state) => state.alerts);
  const knownDeviceIds = useMemo(() => new Set(scene.nodes.map((node) => node.id)), [scene.nodes]);
  const alertStates = useMemo(() => deriveDeviceAlertStates(alertsQuery.data?.items, liveAlerts, knownDeviceIds), [alertsQuery.data?.items, liveAlerts, knownDeviceIds]);
  const alertingDeviceIds = useMemo(() => activeAlertDeviceIds(alertStates), [alertStates]);
  const hasContent = Boolean(baseGraph?.nodes.length || scene.nodes.length || spatialQuery.data?.objects.some((object) => object.geometry));
  const viewportStatus = resolveViewportStatus({
    networkSelected: Boolean(networkId),
    isLoading: graphQuery.isLoading,
    isError: graphQuery.isError,
    error: graphQuery.error,
    hasData: Boolean(graphQuery.data),
    hasContent,
  });
  return {
    token,
    networkId,
    workspaceId,
    graphQuery,
    spatialQuery,
    alertsQuery,
    alertsEnabled,
    baseGraph,
    scene,
    overlays,
    congestionByDevice,
    alertStates,
    alertingDeviceIds,
    graphComplete: Boolean(baseGraph) && !graphQuery.data?.nextCursor,
    hasContent,
    viewportStatus,
  };
}

export type TwinSceneData = ReturnType<typeof useTwinSceneData>;
