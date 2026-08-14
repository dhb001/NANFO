import { TopologyDeviceNeighbours, TopologyImpact } from "@/shared/types/network";

export interface TopologySummaryStats {
  total: number;
  byHopDepth: Record<number, number>;
}

function summarizeByHopDepth(values: Array<{ hop_depth: number }>): Record<number, number> {
  return values.reduce<Record<number, number>>((acc, item) => {
    const depth = Number(item.hop_depth) || 0;
    acc[depth] = (acc[depth] ?? 0) + 1;
    return acc;
  }, {});
}

export function summarizeNeighbourStats(neighbours: TopologyDeviceNeighbours): TopologySummaryStats {
  return {
    total: neighbours.total,
    byHopDepth: summarizeByHopDepth(neighbours.neighbours),
  };
}

export function summarizeImpactStats(impact: TopologyImpact): TopologySummaryStats {
  return {
    total: impact.total,
    byHopDepth: summarizeByHopDepth(impact.impacts),
  };
}

export function sanitizeRangeInput(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.max(min, Math.min(max, Math.trunc(value)));
}
