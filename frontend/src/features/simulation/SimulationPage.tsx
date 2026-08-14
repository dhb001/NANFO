import { FormEvent, useMemo, useState } from "react";
import {
  useBranchSimulation,
  usePauseSimulation,
  useSimulationCompare,
  useSimulationDetail,
  useStartSimulation,
} from "@/features/simulation/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { Panel } from "@/shared/ui/Panel";
import { Button } from "@/shared/ui/Button";
import { QueryState } from "@/shared/ui/QueryState";
import { Badge } from "@/shared/ui/Badge";
import { formatNumber } from "@/shared/lib/format";
import { useLiveStore } from "@/features/realtime/store";
import { useIsNarrowViewport } from "@/shared/lib/viewport";
import { AsyncState } from "@/shared/ui/AsyncState";

const defaultChecks = ["simulation_before_deployment", "blast_radius_assessment"];

export function SimulationPage() {
  const token = useAuthStore((state) => state.accessToken);
  const networkId = useWorkspaceStore((state) => state.networkId);

  const [scenarioName, setScenarioName] = useState("Campus baseline validation");
  const [trackedSimulationId, setTrackedSimulationId] = useState<string | null>(null);
  const [baselineSimulationId, setBaselineSimulationId] = useState<string | null>(null);
  const [branchScenario, setBranchScenario] = useState("Branch candidate");
  const isNarrowViewport = useIsNarrowViewport();

  const startMutation = useStartSimulation(token);
  const pauseMutation = usePauseSimulation(token);
  const branchMutation = useBranchSimulation(token);

  const detailQuery = useSimulationDetail(token, trackedSimulationId);
  const compareQuery = useSimulationCompare(token, trackedSimulationId, baselineSimulationId);

  const sceneObjects = useLiveStore((state) => state.sceneObjects);
  const simulationSceneObjects = useMemo(
    () =>
      Object.values(sceneObjects)
        .filter((item) => item.object_type === "simulation_state")
        .slice(0, 20),
    [sceneObjects],
  );

  async function start(event: FormEvent) {
    event.preventDefault();
    if (!networkId) {
      return;
    }
    const response = await startMutation.mutateAsync({
      network_id: networkId,
      scenario_name: scenarioName,
      validation_checks: defaultChecks,
    });
    setTrackedSimulationId(response.simulation_id);
    if (!baselineSimulationId) {
      setBaselineSimulationId(response.simulation_id);
    }
  }

  async function branch() {
    if (!trackedSimulationId) {
      return;
    }
    const response = await branchMutation.mutateAsync({
      parentSimulationId: trackedSimulationId,
      scenarioName: branchScenario,
    });
    setBaselineSimulationId(trackedSimulationId);
    setTrackedSimulationId(response.simulation_id);
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Simulation Lifecycle" subtitle="VS4-VS7 what-if orchestration with branch and compare views">
        <form
          onSubmit={start}
          style={{
            display: "grid",
            gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr auto",
            gap: "0.6rem",
            alignItems: "end",
          }}
        >
          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
              Scenario Name
            </span>
            <input
              value={scenarioName}
              onChange={(event) => setScenarioName(event.target.value)}
              required
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.52rem 0.56rem" }}
            />
          </label>
          <Button type="submit" disabled={!networkId || startMutation.isPending}>
            {startMutation.isPending ? "Starting..." : "Start Simulation"}
          </Button>
        </form>

        {startMutation.isError ? (
          <div style={{ marginTop: "0.6rem" }}>
            <AsyncState
              title="Simulation start failed"
              description={startMutation.error instanceof Error ? startMutation.error.message : "Unexpected error"}
              action={
                <Button tone="ghost" type="button" onClick={() => startMutation.reset()}>
                  Dismiss
                </Button>
              }
            />
          </div>
        ) : null}

        {pauseMutation.isError ? (
          <div style={{ marginTop: "0.6rem" }}>
            <AsyncState
              title="Pause failed"
              description={pauseMutation.error instanceof Error ? pauseMutation.error.message : "Unexpected error"}
            />
          </div>
        ) : null}

        {branchMutation.isError ? (
          <div style={{ marginTop: "0.6rem" }}>
            <AsyncState
              title="Branch failed"
              description={branchMutation.error instanceof Error ? branchMutation.error.message : "Unexpected error"}
            />
          </div>
        ) : null}

        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.7rem", flexWrap: "wrap" }}>
          <Button
            tone="ghost"
            onClick={() => trackedSimulationId && pauseMutation.mutate(trackedSimulationId)}
            disabled={!trackedSimulationId || pauseMutation.isPending}
          >
            Pause
          </Button>
          <Button tone="ghost" onClick={branch} disabled={!trackedSimulationId || branchMutation.isPending}>
            Branch
          </Button>
          <input
            value={branchScenario}
            onChange={(event) => setBranchScenario(event.target.value)}
            placeholder="Branch scenario name"
            style={{
              border: "1px solid var(--line-soft)",
              borderRadius: "10px",
              padding: "0.45rem 0.5rem",
              minWidth: 220,
            }}
          />
          <input
            value={trackedSimulationId ?? ""}
            onChange={(event) => setTrackedSimulationId(event.target.value || null)}
            placeholder="Simulation ID"
            style={{
              border: "1px solid var(--line-soft)",
              borderRadius: "10px",
              padding: "0.45rem 0.5rem",
              minWidth: 300,
              fontFamily: "var(--font-mono)",
            }}
          />
          <input
            value={baselineSimulationId ?? ""}
            onChange={(event) => setBaselineSimulationId(event.target.value || null)}
            placeholder="Baseline simulation ID"
            style={{
              border: "1px solid var(--line-soft)",
              borderRadius: "10px",
              padding: "0.45rem 0.5rem",
              minWidth: 300,
              fontFamily: "var(--font-mono)",
            }}
          />
        </div>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr", gap: "1rem", alignItems: "start" }}>
        <Panel title="Simulation Detail" subtitle="GET /simulations/{id}">
          <QueryState
            query={detailQuery}
            emptyTitle="No simulation selected"
            emptyDescription="Start or paste a simulation id to inspect lifecycle detail."
          >
            {(detail) => (
              <div style={{ display: "grid", gap: "0.5rem" }}>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <Badge text={detail.status} tone={detail.status === "completed" ? "ok" : detail.status === "cancelled" ? "danger" : "warn"} />
                  <Badge text={detail.queue_status} tone={detail.queue_status === "queued" ? "ok" : "warn"} />
                  <Badge text={detail.risk_gate} tone={detail.risk_gate === "passed" ? "ok" : "warn"} />
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                  simulation_id: {detail.simulation_id}
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                  scenario_id: {detail.scenario_id}
                </div>
                <div>
                  <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>Validation</div>
                  <pre style={{ margin: 0, fontSize: "0.76rem", color: "var(--ink-2)", overflow: "auto" }}>
                    {JSON.stringify(detail.validation, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </QueryState>
        </Panel>

        <Panel title="Compare" subtitle="GET /simulations/{id}/compare/{baselineId}">
          <QueryState
            query={compareQuery}
            emptyTitle="No compare inputs"
            emptyDescription="Provide simulation and baseline ids to compare deterministic deltas."
          >
            {(compare) => (
              <div style={{ display: "grid", gap: "0.5rem" }}>
                <MetricRow label="Latency delta" value={compare.deltas.latency_ms} unit="ms" />
                <MetricRow label="Loss delta" value={compare.deltas.loss_pct} unit="%" />
                <MetricRow label="Throughput delta" value={compare.deltas.throughput_mbps} unit="mbps" />
              </div>
            )}
          </QueryState>
        </Panel>
      </div>

      <Panel title="Realtime Simulation Timeline" subtitle="/ws/digital-twin scene-object updates for simulation lifecycle">
        {simulationSceneObjects.length === 0 ? (
          <div style={{ color: "var(--ink-3)" }}>Awaiting simulation scene deltas...</div>
        ) : (
          <div style={{ display: "grid", gap: "0.4rem", maxHeight: 300, overflow: "auto" }}>
            {simulationSceneObjects.map((item) => (
              <div
                key={item.id}
                style={{
                  border: "1px solid var(--line-soft)",
                  borderRadius: "10px",
                  padding: "0.46rem 0.52rem",
                  display: "grid",
                  gap: "0.2rem",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <strong>{item.id}</strong>
                  <Badge text={String(item.status ?? item.state ?? "unknown")} tone="info" />
                </div>
                <div className="mono" style={{ fontSize: "0.74rem", color: "var(--ink-3)" }}>
                  simulation: {String(item.simulation_id ?? "-")}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function MetricRow({ label, value, unit }: { label: string; value: number; unit: string }) {
  const tone = value > 0 ? "warn" : value < 0 ? "ok" : "neutral";
  return (
    <div
      style={{
        border: "1px solid var(--line-soft)",
        borderRadius: "10px",
        padding: "0.5rem 0.56rem",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <span>{label}</span>
      <Badge text={`${formatNumber(value)} ${unit}`} tone={tone as "neutral" | "ok" | "warn"} />
    </div>
  );
}
