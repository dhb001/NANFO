import type { TwinLink, TwinNode } from "./sceneAdapter";

export interface MeasuredPathSegment {
  id: string;
  source: [number, number, number];
  target: [number, number, number];
}

// Canonical IDs only. Names, proximity and a plausible route are not packet evidence.
export function mapMeasuredPath(nodeIds: readonly (string | null)[], linkIds: readonly (string | null)[],
  nodes: readonly TwinNode[], links: readonly TwinLink[]): MeasuredPathSegment[] | null {
  if (nodeIds.length < 2 || linkIds.length !== nodeIds.length - 1) return null;
  const byNode = new Map(nodes.map((node) => [node.id, node]));
  const byLink = new Map(links.map((link) => [link.id, link]));
  if (byNode.size !== nodes.length || byLink.size !== links.length) return null;
  const segments: MeasuredPathSegment[] = [];
  for (let index = 0; index < linkIds.length; index += 1) {
    const source = byNode.get(nodeIds[index] ?? "");
    const target = byNode.get(nodeIds[index + 1] ?? "");
    const link = byLink.get(linkIds[index] ?? "");
    if (!source || !target || !link || source.id === target.id ||
        ![source.x, source.y, source.z, target.x, target.y, target.z].every(Number.isFinite) ||
        !((link.sourceId === source.id && link.targetId === target.id) || (link.targetId === source.id && link.sourceId === target.id))) return null;
    segments.push({ id: `${index}:${link.id}`, source: [source.x, source.y, source.z], target: [target.x, target.y, target.z] });
  }
  return segments;
}
