import { useMemo } from "react";
import { useLiveStore } from "@/features/realtime/store";
import { TopologyEdge, TopologyNode } from "@/shared/types/network";
import { topologyEdgeIdentity } from "@/features/topology/edgeIdentity";
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
  const telemetryKeysNewestFirst = useLiveStore((state) => state.telemetryKeysNewestFirst);
  const sceneObjects = useLiveStore((state) => state.sceneObjects);
  const sceneObjectIdsNewestFirst = useLiveStore((state) => state.sceneObjectIdsNewestFirst);

  return useMemo(() => {
    return buildTwinSceneModel({
      baseNodes,
        baseEdges,
        liveNodesByDeviceId: topologyByDeviceId,
        telemetryByDeviceMetric,
        telemetryKeysNewestFirst,
        sceneObjects,
        sceneObjectIdsNewestFirst,
      }).nodes;
  }, [
    baseNodes,
    baseEdges,
    topologyByDeviceId,
    telemetryByDeviceMetric,
    telemetryKeysNewestFirst,
    sceneObjects,
    sceneObjectIdsNewestFirst,
  ]);
}

export function useTwinSceneModel(
  baseNodes: TopologyNode[] = [],
  baseEdges: TopologyEdge[] = [],
  importedSpatialRefByDeviceId?: Record<string, string>,
) {
  const topologyByDeviceId = useLiveStore((state) => state.topologyByDeviceId);
  const telemetryByDeviceMetric = useLiveStore((state) => state.telemetryByDeviceMetric);
  const telemetryKeysNewestFirst = useLiveStore((state) => state.telemetryKeysNewestFirst);
  const sceneObjects = useLiveStore((state) => state.sceneObjects);
  const sceneObjectIdsNewestFirst = useLiveStore((state) => state.sceneObjectIdsNewestFirst);

  return useMemo(() => {
    return buildTwinSceneModel({
      baseNodes,
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
    baseNodes,
    importedSpatialRefByDeviceId,
    telemetryKeysNewestFirst,
    sceneObjectIdsNewestFirst,
    sceneObjects,
    telemetryByDeviceMetric,
    topologyByDeviceId,
  ]);
}

export function useTwinLinks(nodes: TwinNode[], edges: TopologyEdge[] = []): TwinLink[] {
  return useMemo(() => {
    const seenLinkIds = new Set<string>();
    const nodeById = nodes.reduce<Record<string, TwinNode>>((acc, node) => {
      acc[node.id] = node;
      return acc;
    }, {});

    return edges
      .map((edge) => {
        const sourceNode = nodeById[edge.source_id];
        const targetNode = nodeById[edge.target_id];
        const id = topologyEdgeIdentity(edge);
        if (!sourceNode || !targetNode || seenLinkIds.has(id)) {
          return null;
        }
        seenLinkIds.add(id);

        return {
          id,
          source: [sourceNode.x, sourceNode.y, sourceNode.z],
          target: [targetNode.x, targetNode.y, targetNode.z],
          sourceId: sourceNode.id,
          targetId: targetNode.id,
          edgeType: edge.edge_type,
          metadata: edge.metadata,
        } satisfies TwinLink;
      })
      .filter((link): link is TwinLink => link !== null);
  }, [edges, nodes]);
}
