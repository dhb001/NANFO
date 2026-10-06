import type { TelemetryHealth } from "@/shared/types/telemetry";
import { formatTimestamp } from "@/shared/lib/format";
import { telemetrySloTone } from "@/shared/lib/statusTones";
import { StatTile } from "@/shared/ui/StatTile";

/** Collector-evaluated SLO state (read-only, ADR-028 C12); a stale evaluation is never shown as current. */
export function SloStatusTile({ slo }: { slo: TelemetryHealth["slo"] }) {
  if (!slo) return <StatTile label="SLO" value="Not reported" caption="The collector has not published an SLO evaluation." />;
  const caption = [
    slo.stale ? "Stale evaluation: the collector has not re-evaluated recently" : null,
    slo.evaluated_at ? `Evaluated ${formatTimestamp(slo.evaluated_at)}` : "Never evaluated",
    slo.severity_reason ? `Reason: ${slo.severity_reason}` : null,
    slo.alert_active ? "SLO alert active" : null,
  ].filter(Boolean).join(" · ");
  return <StatTile label="SLO" value={`${slo.status.toUpperCase()}${slo.stale ? " (STALE)" : ""}`}
    tone={slo.stale ? "warn" : telemetrySloTone(slo.status)} caption={caption} />;
}
