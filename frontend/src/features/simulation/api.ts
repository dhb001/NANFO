import { apiRequest } from "@/shared/lib/api";
import {
  BranchSimulationResult,
  PauseSimulationResult,
  SimulationCompare,
  SimulationDetail,
  SimulationValidationHandoff,
} from "@/shared/types/simulation";

export function startSimulation(
  token: string,
  body: {
    network_id: string;
    scenario_name: string;
    simulation_id?: string;
    validation_checks: string[];
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

export function branchSimulation(token: string, parentSimulationId: string, scenarioName: string) {
  return apiRequest<BranchSimulationResult>("/api/v1/simulations/branch", {
    method: "POST",
    body: {
      parent_simulation_id: parentSimulationId,
      scenario_name: scenarioName,
    },
    token,
  });
}

export function getSimulationDetail(token: string, simulationId: string) {
  return apiRequest<SimulationDetail>(`/api/v1/simulations/${simulationId}`, {
    token,
  });
}

export function compareSimulation(token: string, simulationId: string, baselineId: string) {
  return apiRequest<SimulationCompare>(`/api/v1/simulations/${simulationId}/compare/${baselineId}`, {
    token,
  });
}
