import { FormEvent, useMemo, useState } from "react";
import {
  useBranchSimulation,
  usePauseSimulation,
  useSimulationCompare,
  useSimulationDetail,
  useStartSimulation,
  useSimulationHistory,
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
import { ScenarioEditor } from "./ScenarioEditor";
import { exampleScenario, parseScenarioConfig } from "./scenarioConfig";
import { ModeledEvidence } from "./ModeledEvidence";
import { modeledMetrics, modeledOutput, modelHistorySeries, type ModeledMetric } from "./modeledOutput";
import { TimeSeriesChart } from "@/features/telemetry/TimeSeriesChart";
import { SceneReconciliationStatus } from "@/features/realtime/SceneReconciliationStatus";
import type { ScenarioValidationState } from "@/shared/types/simulation";
import { useSessionScope } from "@/features/auth/sessionScope";
import { useUrlSelection } from "@/shared/lib/urlSelection";

const defaultChecks = ["simulation_before_deployment", "blast_radius_assessment"];

export function SimulationPage() {
  const { key } = useSessionScope();
  return <SimulationPageContent key={key} />;
}

function SimulationPageContent() {
  const session = useSessionScope();
  const token = useAuthStore((state) => state.accessToken);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);

  const [scenarioName, setScenarioName] = useState("Campus baseline validation");
  const [trackedSimulationId, setTrackedSimulationId] = useUrlSelection("simulation_id", session.urlScope);
  const [baselineSimulationId, setBaselineSimulationId] = useUrlSelection("baseline_id", session.urlScope);
  const [historyPage, setHistoryPage] = useState(1);
  const history = useSimulationHistory(token, workspaceId, networkId, historyPage);
  const [branchScenario, setBranchScenario] = useState("Branch candidate");
  const [scenarioJson, setScenarioJson] = useState(JSON.stringify(exampleScenario, null, 2));
  const [editBranchInputs, setEditBranchInputs] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<ScenarioValidationState | undefined>();
  const [metric, setMetric] = useState<ModeledMetric>("latency_ms");
  const isNarrowViewport = useIsNarrowViewport();

  const startMutation = useStartSimulation(token);
  const pauseMutation = usePauseSimulation(token);
  const branchMutation = useBranchSimulation(token);

  const detailQuery = useSimulationDetail(token, trackedSimulationId);
  const compareQuery = useSimulationCompare(token, trackedSimulationId, baselineSimulationId);
  const baselineQuery = useSimulationDetail(token, baselineSimulationId && baselineSimulationId !== trackedSimulationId ? baselineSimulationId : null);
  const selectedDetail = detailQuery.data?.simulation_id === trackedSimulationId && detailQuery.data.network_id === networkId && !detailQuery.isError ? detailQuery.data : undefined;
  const baselineDetail = baselineSimulationId === trackedSimulationId ? selectedDetail : baselineQuery.data;
  const currentOutput = modeledOutput(selectedDetail);
  const baselineOutput = modeledOutput(baselineDetail);
  const compatible = compareQuery.data?.compatible === true && compareQuery.data.simulation_id === trackedSimulationId && compareQuery.data.baseline_simulation_id === baselineSimulationId &&
    selectedDetail?.status === "completed" && baselineDetail?.status === "completed" && Boolean(currentOutput && baselineOutput && currentOutput.workload_sha256 === baselineOutput.workload_sha256 && currentOutput.elapsed_ms === baselineOutput.elapsed_ms);
  const busy = startMutation.isPending || pauseMutation.isPending || branchMutation.isPending;

  const sceneObjects = useLiveStore((state) => state.sceneObjects);
  const sceneObjectIdsNewestFirst = useLiveStore((state) => state.sceneObjectIdsNewestFirst);
  const simulationSceneObjects = useMemo(
    () =>
      sceneObjectIdsNewestFirst
        .map((id) => sceneObjects[id])
        .filter((item): item is (typeof sceneObjects)[string] => Boolean(item))
        .filter((item) => item.object_type === "simulation_state")
        .slice(0, 20),
    [sceneObjects, sceneObjectIdsNewestFirst],
  );

  async function start(event: FormEvent) {
    event.preventDefault();
    if (!networkId || busy) {
      return;
    }
    setInputError(null);
    try {
      const scenarioConfig = parseScenarioConfig(scenarioJson);
      const response = await startMutation.mutateAsync({
        network_id: networkId,
        scenario_name: scenarioName,
        validation_checks: defaultChecks,
        scenario_config: scenarioConfig,
      });
      session.assertCurrent();
      setTrackedSimulationId(response.simulation_id);
      setHandoff(response.validation);
      if (!baselineSimulationId) setBaselineSimulationId(response.simulation_id);
    } catch (error) {
      setInputError(error instanceof Error ? error.message : "Simulation start failed.");
    }
  }

  async function resume() {
    if (!selectedDetail || !["draft", "paused"].includes(selectedDetail.status) || busy) return;
    try {
      const response = await startMutation.mutateAsync({ network_id: selectedDetail.network_id, scenario_name: selectedDetail.scenario_name,
        simulation_id: selectedDetail.simulation_id, validation_checks: defaultChecks });
      session.assertCurrent();
      setHandoff(response.validation);
    } catch { /* Mutation failure is rendered below. Resume never resubmits edited inputs. */ }
  }

  async function branch() {
    if (!selectedDetail || busy) {
      return;
    }
    setInputError(null);
    try {
      const response = await branchMutation.mutateAsync({
        parentSimulationId: selectedDetail.simulation_id,
        scenarioName: branchScenario,
        ...(editBranchInputs ? { scenarioConfig: parseScenarioConfig(scenarioJson) } : {}),
      });
      session.assertCurrent();
      setBaselineSimulationId(selectedDetail.simulation_id);
      setTrackedSimulationId(response.simulation_id);
      setHandoff(response.validation);
    } catch (error) { setInputError(error instanceof Error ? error.message : "Branch failed."); }
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Simulation history" subtitle="Persisted runs in the selected workspace and network; selecting a run only loads detail">
        <Button tone="ghost" disabled={!workspaceId || history.isFetching} onClick={() => void history.refetch()}>Refresh simulation history</Button>
        <p>A lost start or branch response may still have created a run. Inspect history before starting another.</p>
        <QueryState query={history} hasData={(data) => data.items.length > 0} emptyTitle="No simulation history" emptyDescription="No persisted runs on this page.">
          {(data) => <ul>{data.items.map((item) => <li key={item.simulation_id}>
            <Button tone="ghost" disabled={busy} onClick={() => { setTrackedSimulationId(item.simulation_id); setHandoff(undefined); }}>{item.scenario_name} — {item.status}</Button>
            <span className="mono"> {item.simulation_id} | {item.created_at}</span>
            <Button tone="ghost" disabled={busy} onClick={() => setBaselineSimulationId(item.simulation_id)}>Use as baseline</Button>
          </li>)}</ul>}
        </QueryState>
        <nav aria-label="Simulation history pagination">
          <Button disabled={historyPage <= 1 || history.isFetching} onClick={() => setHistoryPage(historyPage - 1)}>Previous simulations</Button>
          <span> Page {historyPage} | {history.data?.total ?? "Unknown"} runs </span>
          <Button disabled={!history.data || historyPage * history.data.page_size >= history.data.total || history.isFetching} onClick={() => setHistoryPage(historyPage + 1)}>Next simulations</Button>
        </nav>
      </Panel>
      <Panel title="Simulation Lifecycle" subtitle="Configured deterministic what-if model, never live traffic or production authorization">
        <form
          onSubmit={start}
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr)",
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
              maxLength={120}
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.52rem 0.56rem" }}
            />
          </label>
          <ScenarioEditor value={scenarioJson} onChange={setScenarioJson} />
          <Button permission="write:config" type="submit" disabled={!networkId || busy}>
            {startMutation.isPending ? "Starting..." : "Start Simulation"}
          </Button>
        </form>
        {inputError && <p role="alert">{inputError}</p>}
        {handoff && <p role="status">Lifecycle handoff source: {handoff.source ?? "Unavailable"}. Physical safety authorization: {handoff.physical_safety_authorized === false ? "false (not authorized)" : "Unavailable / unsupported"}. Queue acceptance is not completed computation or deployment approval.</p>}

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
            permission="write:config"
            tone="ghost"
            onClick={() => trackedSimulationId && pauseMutation.mutate(trackedSimulationId)}
            disabled={!selectedDetail || !["queued", "running"].includes(selectedDetail.status) || busy}
          >
            Pause
          </Button>
          <Button permission="write:config" tone="ghost" onClick={() => void resume()} disabled={!selectedDetail || !["draft", "paused"].includes(selectedDetail.status) || busy}>Resume / start draft</Button>
          <Button permission="write:config" tone="ghost" onClick={branch} disabled={!selectedDetail || busy || !branchScenario.trim()}>
            Branch
          </Button>
          <input
            aria-label="Branch scenario name"
            maxLength={120}
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
            aria-label="Simulation ID"
            value={trackedSimulationId ?? ""}
            onChange={(event) => setTrackedSimulationId(event.target.value || null)}
            placeholder="Simulation ID"
            style={{
              border: "1px solid var(--line-soft)",
              borderRadius: "10px",
              padding: "0.45rem 0.5rem",
              minWidth: 0, width: isNarrowViewport ? "100%" : 300,
              fontFamily: "var(--font-mono)",
            }}
          />
          <input
            aria-label="Baseline simulation ID"
            value={baselineSimulationId ?? ""}
            onChange={(event) => setBaselineSimulationId(event.target.value || null)}
            placeholder="Baseline simulation ID"
            style={{
              border: "1px solid var(--line-soft)",
              borderRadius: "10px",
              padding: "0.45rem 0.5rem",
              minWidth: 0, width: isNarrowViewport ? "100%" : 300,
              fontFamily: "var(--font-mono)",
            }}
          />
        </div>
        <label><input type="checkbox" checked={editBranchInputs} onChange={(event) => setEditBranchInputs(event.target.checked)} /> Branch with editor inputs (changed inputs restart at tick 0)</label>
        <p>Default branch copies the checkpoint and compatible inputs. Resume uses the same simulation ID and persisted inputs/checkpoint, ignoring editor changes. Pause is committed safely between worker batches.</p>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "minmax(0, 1fr)" : "repeat(2, minmax(0, 1fr))", gap: "1rem", alignItems: "start" }}>
        <Panel title="Simulation Detail" subtitle="Configuration, progress and evidence for the selected run">
          <Button tone="ghost" disabled={!trackedSimulationId || detailQuery.isFetching} onClick={() => void detailQuery.refetch()}>Refresh simulation status</Button>
          <p>Active detail polling is bounded to 40 reads, then use Refresh. A stalled worker or lost connection is not completion.</p>
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
                <ModeledEvidence detail={detail} />
                <TimeSeriesChart title="Modeled flow history" modeled series={modelHistorySeries(detail, metric, "Candidate")} />
              </div>
            )}
          </QueryState>
        </Panel>

        <Panel title="Compare" subtitle="Review the selected run against a compatible baseline">
          {baselineQuery.isError && <AsyncState title="Baseline detail unavailable" description="Comparison remains unavailable until the baseline can be read." action={<Button tone="ghost" onClick={() => void baselineQuery.refetch()}>Retry baseline</Button>} />}
          <label style={{ display: "grid" }}>Comparison metric<select aria-label="Comparison metric" value={metric} onChange={(event) => setMetric(event.target.value as ModeledMetric)}>{Object.entries(modeledMetrics).map(([key, value]) => <option key={key} value={key}>{value.label} ({value.unit}; {value.higherIsBetter ? "higher" : "lower"} is better)</option>)}</select></label>
          <p>Candidate minus baseline; latency/loss decreases and goodput increases are favorable. Model-only comparisons require matching workload and modeled time. Missing or incompatible metrics are unavailable, never zero.</p>
          <QueryState
            query={compareQuery}
            emptyTitle="No compare inputs"
            emptyDescription="Provide simulation and baseline ids to compare deterministic deltas."
          >
            {(compare) => (
              <div style={{ display: "grid", gap: "0.5rem" }}>
                <MetricRow label="Latency delta" value={compatible ? compare.deltas.latency_ms : null} unit="ms" />
                <MetricRow label="Loss delta" value={compatible ? compare.deltas.loss_pct : null} unit="%" />
                <MetricRow label="Goodput delta" value={compatible ? compare.deltas.throughput_mbps : null} unit="Mbps" higherIsBetter />
                {compatible ? <TimeSeriesChart title="Modeled comparison history" modeled series={[...modelHistorySeries(selectedDetail, metric, "Candidate"), ...modelHistorySeries(baselineDetail, metric, "Baseline")]} /> : <p>Comparison histories unavailable or incompatible. Both completed versioned model outputs and a common workload/time basis are required. {compare.comparison_reason}</p>}
                <Button tone="ghost" disabled={compareQuery.isFetching} onClick={() => { void compareQuery.refetch(); if (baselineSimulationId !== trackedSimulationId) void baselineQuery.refetch(); }}>Refresh comparison</Button>
              </div>
            )}
          </QueryState>
        </Panel>
      </div>

      <Panel title="Realtime Simulation Timeline" subtitle="Incoming progress and lifecycle changes for simulation runs">
        <SceneReconciliationStatus />
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

function MetricRow({ label, value, unit, higherIsBetter = false }: {
  label: string; value: number | null; unit: string; higherIsBetter?: boolean;
}) {
  const available = value !== null && Number.isFinite(value);
  const tone = !available || value === 0 ? "neutral" : (value > 0) === higherIsBetter ? "ok" : "warn";
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
      <Badge text={available ? `${formatNumber(value)} ${unit}` : "Unavailable (no compatible modeled evidence)"} tone={tone} />
    </div>
  );
}
