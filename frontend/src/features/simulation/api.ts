import { apiRequest } from "@/shared/lib/api";
import {
  BranchSimulationResult,
  PauseSimulationResult,
  SimulationCompare,
  SimulationDetail,
  SimulationValidationHandoff,
  ScenarioConfig,
  SimulationHistory,
} from "@/shared/types/simulation";

export function listSimulations(token: string, workspaceId: string, networkId: string | null, page = 1, signal?: AbortSignal) {
  const params = new URLSearchParams({ workspace_id: workspaceId, page: String(page), page_size: "20" });
  if (networkId) params.set("network_id", networkId);
  return apiRequest<SimulationHistory>(`/api/v1/simulations?${params}`, { token, signal });
}

export function startSimulation(
  token: string,
  body: {
    network_id: string;
    scenario_name: string;
    simulation_id?: string;
    validation_checks: string[];
    scenario_config?: ScenarioConfig;
  },
) {
  return apiRequest<SimulationValidationHandoff>("/api/v1/simulations/start", {
    method: "POST",
    body,
    token,
  });
}

export function pauseSimulation(token: string, simulationId: string) {
  return apiRequest<PauseSimulationResult>("/api/v1/simulations/pause", {
    method: "POST",
    body: { simulation_id: simulationId },
    token,
  });
}

export function branchSimulation(token: string, parentSimulationId: string, scenarioName: string, scenarioConfig?: ScenarioConfig) {
  return apiRequest<BranchSimulationResult>("/api/v1/simulations/branch", {
    method: "POST",
    body: {
      parent_simulation_id: parentSimulationId,
      scenario_name: scenarioName,
      ...(scenarioConfig ? { scenario_config: scenarioConfig } : {}),
    },
    token,
  });
}

export function getSimulationDetail(token: string, simulationId: string, signal?: AbortSignal) {
  return apiRequest<SimulationDetail>(`/api/v1/simulations/${simulationId}`, {
    token,
    signal,
  });
}

export function compareSimulation(token: string, simulationId: string, baselineId: string, signal?: AbortSignal) {
  return apiRequest<SimulationCompare>(`/api/v1/simulations/${simulationId}/compare/${baselineId}`, {
    token,
    signal,
  });
}
