import { Badge } from "@/shared/ui/Badge";

export function TelemetryProvenance({ tags }: { tags: Record<string, unknown> }) {
  const synthetic = tags.synthetic === true || tags.synthetic === "true";
  const measuredEmulation = tags.synthetic === false && tags.execution_mode === "emulation";
  return <Badge text={synthetic ? "Synthetic telemetry" : measuredEmulation ? "Measured emulation" : "Telemetry provenance: unverified"}
    tone={synthetic ? "warn" : measuredEmulation ? "info" : "neutral"} />;
}
