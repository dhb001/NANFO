import { TopologyEdge } from "@/shared/types/network";

export function topologyEdgeIdentity(edge: TopologyEdge): string {
  const metadata = edge.metadata ?? {};
  const identity = [metadata.observation_owner, metadata.edge_key, metadata.source_port, metadata.target_port];
  // Legacy edges have no durable key: only identical metadata is safe to deduplicate.
  const discriminator = identity.some((value) => value !== undefined && value !== null)
    ? identity
    : JSON.stringify(metadata, (_key, value: unknown) =>
      value !== null && typeof value === "object" && !Array.isArray(value)
        ? Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)))
        : value);
  return JSON.stringify([edge.source_id, edge.target_id, edge.edge_type, discriminator]);
}
