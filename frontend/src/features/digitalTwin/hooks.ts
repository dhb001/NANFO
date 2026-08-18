import { useMemo } from "react";
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

export function useTwinNodes(baseNodes: TopologyNode[] = []) {
  const baseEdges = useMemo(() => [], []);
  const topologyByDeviceId = useLiveStore((state) => state.topologyByDeviceId);
  const telemetryByDeviceMetric = useLiveStore((state) => state.telemetryByDeviceMetric);
  const sceneObjects = useLiveStore((state) => state.sceneObjects);
  const sceneObjectIdsNewestFirst = useLiveStore((state) => state.sceneObjectIdsNewestFirst);

  return useMemo(() => {
    return buildTwinSceneModel({
      baseNodes,
      baseEdges,
      liveNodesByDeviceId: topologyByDeviceId,
      telemetryByDeviceMetric,
      sceneObjects,
      sceneObjectIdsNewestFirst,
    }).nodes;
  }, [baseNodes, baseEdges, topologyByDeviceId, telemetryByDeviceMetric, sceneObjects, sceneObjectIdsNewestFirst]);
}

export function useTwinSceneModel(
  baseNodes: TopologyNode[] = [],
  baseEdges: TopologyEdge[] = [],
  importedSpatialRefByDeviceId?: Record<string, string>,
) {
  const topologyByDeviceId = useLiveStore((state) => state.topologyByDeviceId);
  const telemetryByDeviceMetric = useLiveStore((state) => state.telemetryByDeviceMetric);
  const sceneObjects = useLiveStore((state) => state.sceneObjects);
  const sceneObjectIdsNewestFirst = useLiveStore((state) => state.sceneObjectIdsNewestFirst);

  return useMemo(() => {
    return buildTwinSceneModel({
      baseNodes,
      baseEdges,
      liveNodesByDeviceId: topologyByDeviceId,
      telemetryByDeviceMetric,
      sceneObjects,
      sceneObjectIdsNewestFirst,
      importedSpatialRefByDeviceId,
    });
  }, [
    baseEdges,
    baseNodes,
    importedSpatialRefByDeviceId,
    sceneObjectIdsNewestFirst,
    sceneObjects,
    telemetryByDeviceMetric,
    topologyByDeviceId,
  ]);
}

export function useTwinLinks(nodes: TwinNode[], edges: TopologyEdge[] = []): TwinLink[] {
  return useMemo(() => {
    const nodeById = nodes.reduce<Record<string, TwinNode>>((acc, node) => {
      acc[node.id] = node;
      return acc;
    }, {});

    return edges
      .map((edge) => {
        const sourceNode = nodeById[edge.source_id];
        const targetNode = nodeById[edge.target_id];
        if (!sourceNode || !targetNode) {
          return null;
        }

        return {
          id: `${edge.source_id}:${edge.target_id}:${edge.edge_type}`,
          source: [sourceNode.x, sourceNode.y, sourceNode.z],
          target: [targetNode.x, targetNode.y, targetNode.z],
          sourceId: sourceNode.id,
          targetId: targetNode.id,
          edgeType: edge.edge_type,
        } satisfies TwinLink;
      })
      .filter((link): link is TwinLink => link !== null);
  }, [edges, nodes]);
}
