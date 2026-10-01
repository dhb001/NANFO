import { displayValue } from "@/shared/lib/format";

export function FlowCounterIdentity({ metric, observedAt, tags }: { metric: string; observedAt: string; tags: Record<string, unknown> }) {
  if (!metric.startsWith("flow_")) return null;
  return <span style={{ overflowWrap: "anywhere" }}>snapshot-local flow counter, durable identity unavailable | observed {observedAt} | table {displayValue(tags.table_id)} | cookie {displayValue(tags.cookie)} | priority {displayValue(tags.priority)} | ordinal {displayValue(tags.flow_index)}</span>;
}
