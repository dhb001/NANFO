import { useMemo } from "react";
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
    <div
      style={{
        border: "1px solid var(--line-soft)",
        borderRadius: "10px",
        padding: "0.48rem 0.56rem",
        display: "grid",
        gap: "0.3rem",
      }}
    >
      <strong style={{ fontSize: "0.9rem" }}>Device type legend</strong>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {deviceLegend.map((entry) => (
          <span
            key={entry.typeKey}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.28rem",
              fontSize: "0.76rem",
              color: "var(--ink-2)",
            }}
          >
            <span
              aria-hidden="true"
              style={{
                width: "0.62rem",
                height: "0.62rem",
                borderRadius: entry.geometry === "box" ? "2px" : "999px",
                background: entry.color,
                border: "1px solid rgba(20, 48, 36, 0.24)",
              }}
            />
            {entry.label}
            {deviceTypeCounts[entry.label] ? (
              <span className="mono" style={{ color: "var(--ink-3)" }}>
                ({deviceTypeCounts[entry.label]})
              </span>
            ) : null}
            <span className="mono" style={{ color: "var(--ink-3)", fontSize: "0.68rem" }}>
              {TIER_LABELS[entry.tier]}
            </span>
          </span>
        ))}
      </div>
      <div style={{ color: "var(--ink-3)", fontSize: "0.78rem" }}>
        Shape and colour encode device type. Ring colour changes with congestion severity
        while the Congestion layer is active.
      </div>
    </div>
  );
}
