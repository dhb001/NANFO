import { useEffect, useMemo, useState } from "react";
import { useLiveStore } from "@/features/realtime/store";
import { TopologyEdge, TopologyNode } from "@/shared/types/network";
import {
  buildTwinSceneModel,
  type TwinCongestion,
  type TwinLink,
  type TwinNode,
  type TwinOverlayObject,
} from "@/features/digitalTwin/sceneAdapter";

export type { TwinCongestion, TwinLink, TwinNode, TwinOverlayObject };

function useFreshnessClock() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 5_000);
    return () => window.clearInterval(interval);
  }, []);
  return now;
}

export function useTwinSceneModel(
  baseNodes: TopologyNode[] = [],
  baseEdges: TopologyEdge[] = [],
  importedSpatialRefByDeviceId?: Record<string, string>,
) {
  const now = useFreshnessClock();
  const topologyTombstones = useLiveStore((state) => state.topologyTombstones);
  const topologyByDeviceId = useLiveStore((state) => state.topologyByDeviceId);
  const telemetryByDeviceMetric = useLiveStore((state) => state.telemetryByDeviceMetric);
  const telemetryKeysNewestFirst = useLiveStore((state) => state.telemetryKeysNewestFirst);
  const sceneObjects = useLiveStore((state) => state.sceneObjects);
  const sceneObjectIdsNewestFirst = useLiveStore((state) => state.sceneObjectIdsNewestFirst);

  return useMemo(() => {
    return buildTwinSceneModel({
      baseNodes,
      now,
      topologyTombstones,
      baseEdges,
      liveNodesByDeviceId: topologyByDeviceId,
      telemetryByDeviceMetric,
      telemetryKeysNewestFirst,
      sceneObjects,
      sceneObjectIdsNewestFirst,
      importedSpatialRefByDeviceId,
    });
  }, [
    baseEdges,
    now,
    topologyTombstones,
    baseNodes,
    importedSpatialRefByDeviceId,
    telemetryKeysNewestFirst,
    sceneObjectIdsNewestFirst,
    sceneObjects,
    telemetryByDeviceMetric,
    topologyByDeviceId,
  ]);
}
