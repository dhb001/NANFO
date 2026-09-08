import { Badge } from "@/shared/ui/Badge";

export function TelemetryProvenance({ tags }: { tags: Record<string, unknown> }) {
  const synthetic = tags.synthetic === true || tags.synthetic === "true";
  return <Badge text={synthetic ? "Synthetic telemetry" : "Telemetry provenance: unverified"}
    tone={synthetic ? "warn" : "neutral"} />;
}
