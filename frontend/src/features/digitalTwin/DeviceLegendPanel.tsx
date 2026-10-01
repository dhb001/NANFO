import { useMemo, type CSSProperties } from "react";
import type { TwinNode } from "@/features/digitalTwin/hooks";
import {
  buildDeviceLegend,
  getDeviceVisualDefinition,
  TIER_LABELS,
} from "@/features/digitalTwin/deviceVisuals";

interface DeviceLegendPanelProps {
  nodes: TwinNode[];
}

export function DeviceLegendPanel({ nodes }: DeviceLegendPanelProps) {
  const deviceLegend = useMemo(() => buildDeviceLegend(), []);

  const deviceTypeCounts = useMemo(() => {
    return nodes.reduce<Record<string, number>>((acc, node) => {
      const definition = getDeviceVisualDefinition(node.type);
      acc[definition.label] = (acc[definition.label] ?? 0) + 1;
      return acc;
    }, {});
  }, [nodes]);

  return (
    <section className="twin-card" aria-label="Device type legend">
      <h4 className="twin-card-title">Device type legend</h4>
      <ul className="twin-legend-items">
        {deviceLegend.map((entry) => (
          <li key={entry.typeKey} className="twin-legend-item">
            <span
              aria-hidden="true"
              className={`twin-swatch${entry.geometry === "box" ? " twin-swatch--box" : ""}`}
              style={{ "--twin-swatch": entry.color } as CSSProperties}
            />
            {entry.label}
            {deviceTypeCounts[entry.label] ? (
              <span className="mono twin-meta">
                ({deviceTypeCounts[entry.label]})
              </span>
            ) : null}
            <span className="mono twin-meta">
              {TIER_LABELS[entry.tier]}
            </span>
          </li>
        ))}
      </ul>
      <p className="twin-muted">
        Shape and colour encode device type. While the Congestion layer is active the ring colour shows the visual
        heuristic; devices with an active backend alert also carry an ALERT label.
      </p>
    </section>
  );
}
