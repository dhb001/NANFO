import { useEffect, useMemo, useState } from "react";
import { useLiveStore } from "@/features/realtime/store";
import { TopologyEdge, TopologyNode } from "@/shared/types/network";
import {
  buildTwinOverlays,
  buildTwinTopology,
  deriveCongestionByDevice,
  type TwinCongestion,
  type TwinLink,
  type TwinNode,
  type TwinOverlayObject,
  type TwinTopology,
} from "@/features/digitalTwin/sceneAdapter";

export type { TwinCongestion, TwinLink, TwinNode, TwinOverlayObject };

const EMPTY_NODES: TopologyNode[] = [];
const EMPTY_EDGES: TopologyEdge[] = [];

/**
 * Topology and schematic placement only. Recomputed when the REST graph, a live topology
 * delta (revision/tombstone) or the session mapping changes, never on telemetry.
 */
export function useTwinTopology(
  baseNodes: TopologyNode[] = EMPTY_NODES,
  baseEdges: TopologyEdge[] = EMPTY_EDGES,
  importedSpatialRefByDeviceId?: Record<string, string>,
): TwinTopology {
  const topologyTombstones = useLiveStore((state) => state.topologyTombstones);
  const topologyByDeviceId = useLiveStore((state) => state.topologyByDeviceId);
  return useMemo(() => buildTwinTopology({
    baseNodes, baseEdges, topologyTombstones, liveNodesByDeviceId: topologyByDeviceId, importedSpatialRefByDeviceId,
  }), [baseNodes, baseEdges, topologyTombstones, topologyByDeviceId, importedSpatialRefByDeviceId]);
}

export function useTwinOverlays(): TwinOverlayObject[] {
  const sceneObjects = useLiveStore((state) => state.sceneObjects);
  const sceneObjectIdsNewestFirst = useLiveStore((state) => state.sceneObjectIdsNewestFirst);
  return useMemo(() => buildTwinOverlays(sceneObjects, sceneObjectIdsNewestFirst), [sceneObjects, sceneObjectIdsNewestFirst]);
}

export interface FrameScheduler {
  request: (callback: () => void) => number;
  cancel: (handle: number) => void;
}

export const animationFrameScheduler: FrameScheduler = {
  request: (callback) => (typeof requestAnimationFrame === "function" ? requestAnimationFrame(() => callback()) : window.setTimeout(callback, 16)),
  cancel: (handle) => (typeof cancelAnimationFrame === "function" ? cancelAnimationFrame(handle) : window.clearTimeout(handle)),
};

/** Freshness tick: stale samples expire from the heuristic without another push. */
export const CONGESTION_FRESHNESS_TICK_MS = 5_000;

function computeCongestion(): Record<string, TwinCongestion> {
  const { telemetryByDeviceMetric, telemetryKeysNewestFirst } = useLiveStore.getState();
  return deriveCongestionByDevice(telemetryByDeviceMetric, telemetryKeysNewestFirst, Date.now());
}

function sameMetrics(left: TwinCongestion, right: TwinCongestion): boolean {
  if (left.severity !== right.severity || left.primaryMetric !== right.primaryMetric || left.metrics.length !== right.metrics.length) return false;
  return left.metrics.every((metric, index) => {
    const other = right.metrics[index];
    return other !== undefined && metric.metric === other.metric && metric.value === other.value && metric.observedAt === other.observedAt && metric.stale === other.stale && metric.source === other.source;
  });
}

export function sameCongestionMap(left: Readonly<Record<string, TwinCongestion>>, right: Readonly<Record<string, TwinCongestion>>): boolean {
  const leftKeys = Object.keys(left);
  if (leftKeys.length !== Object.keys(right).length) return false;
  return leftKeys.every((key) => {
    const leftValue = left[key], rightValue = Object.hasOwn(right, key) ? right[key] : undefined;
    return leftValue !== undefined && rightValue !== undefined && sameMetrics(leftValue, rightValue);
  });
}

/**
 * Live visual-heuristic congestion per device, applied in animation-frame batches: any
 * burst of telemetry deltas within one frame produces at most one recomputation and one
 * render, and an unchanged result produces none.
 */
export function useTwinLiveCongestion(scheduler: FrameScheduler = animationFrameScheduler): Readonly<Record<string, TwinCongestion>> {
  const [value, setValue] = useState(computeCongestion);
  useEffect(() => {
    let handle: number | null = null;
    const flush = () => {
      handle = null;
      const next = computeCongestion();
      setValue((current) => (sameCongestionMap(current, next) ? current : next));
    };
    const schedule = () => { if (handle === null) handle = scheduler.request(flush); };
    const unsubscribe = useLiveStore.subscribe((state, previous) => {
      if (state.telemetryByDeviceMetric !== previous.telemetryByDeviceMetric || state.telemetryKeysNewestFirst !== previous.telemetryKeysNewestFirst) schedule();
    });
    const tick = window.setInterval(schedule, CONGESTION_FRESHNESS_TICK_MS);
    schedule();
    return () => {
      unsubscribe();
      window.clearInterval(tick);
      if (handle !== null) scheduler.cancel(handle);
    };
  }, [scheduler]);
  return value;
}
