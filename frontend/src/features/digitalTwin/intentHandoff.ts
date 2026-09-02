import type { TwinMetricSnapshot } from "@/features/digitalTwin/sceneAdapter";

interface IntentHandoffPrefill {
  source: "digital-twin";
  action: string;
  scopeJson: string;
  constraintsJson: string;
  contextSummary: string;
}

interface IntentHandoffNode {
  id: string;
  hostname: string;
  type: string;
  spatialRefId: string | null;
  congestion: {
    severity: "low" | "medium" | "high" | "neutral";
    score: number | null;
    policyVersion: string;
    primaryPolicyId: string | null;
    metrics: TwinMetricSnapshot[];
  };
}

function recommendIntentAction(severity: "low" | "medium" | "high" | "neutral") {
  if (severity === "high") {
    return "throttle_qos";
  }
  if (severity === "medium") {
    return "optimize_wireless_capacity";
  }
  return "reroute_path";
}

export function buildIntentHandoffFromNode(node: IntentHandoffNode): IntentHandoffPrefill {
  const action = recommendIntentAction(node.congestion.severity);
  const topMetric = node.congestion.metrics[0] ?? null;
  const scope = {
    source: "digital_twin",
    device_id: node.id,
    spatial_ref_id: node.spatialRefId,
    congestion: {
      severity: node.congestion.severity,
      score: node.congestion.score,
      policy_id: node.congestion.primaryPolicyId,
      metric: topMetric
        ? {
            name: topMetric.metric,
            value: topMetric.value,
            unit: topMetric.unit,
            severity: topMetric.severity,
          }
        : null,
    },
  };

  const constraints = {
    max_downtime: 0,
    preserve_connectivity: true,
    simulation_required: true,
    context_source: "digital_twin",
  };

  const summary = [
    `device=${node.hostname}`,
    `severity=${node.congestion.severity}`,
    `policy=${node.congestion.primaryPolicyId ?? "none"}`,
  ].join(" | ");

  return {
    source: "digital-twin",
    action,
    scopeJson: JSON.stringify(scope),
    constraintsJson: JSON.stringify(constraints),
    contextSummary: summary,
  };
}
