export function FlowCounterIdentity({ metric, observedAt, tags }: { metric: string; observedAt: string; tags: Record<string, unknown> }) {
  if (!metric.startsWith("flow_")) return null;
  return <span style={{ overflowWrap: "anywhere" }}>snapshot-local flow counter, durable identity unavailable | observed {observedAt} | table {String(tags.table_id ?? "unavailable")} | cookie {String(tags.cookie ?? "unavailable")} | priority {String(tags.priority ?? "unavailable")} | ordinal {String(tags.flow_index ?? "unavailable")}</span>;
}
