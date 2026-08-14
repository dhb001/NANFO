import { useMutation, useQuery } from "@tanstack/react-query";
import {
  branchSimulation,
  compareSimulation,
  getSimulationDetail,
  pauseSimulation,
  startSimulation,
} from "@/features/simulation/api";

export function useStartSimulation(token: string | null) {
  return useMutation({
    mutationFn: (body: { network_id: string; scenario_name: string; simulation_id?: string; validation_checks: string[] }) =>
      startSimulation(token as string, body).then((response) => response.data),
  });
}

export function usePauseSimulation(token: string | null) {
  return useMutation({
    mutationFn: (simulationId: string) => pauseSimulation(token as string, simulationId).then((response) => response.data),
  });
}

export function useBranchSimulation(token: string | null) {
  return useMutation({
    mutationFn: (body: { parentSimulationId: string; scenarioName: string }) =>
      branchSimulation(token as string, body.parentSimulationId, body.scenarioName).then((response) => response.data),
  });
}

export function useSimulationDetail(token: string | null, simulationId: string | null) {
  return useQuery({
    queryKey: ["simulation", token, simulationId],
    queryFn: () => getSimulationDetail(token as string, simulationId as string).then((response) => response.data),
    enabled: Boolean(token && simulationId),
  });
}

export function useSimulationCompare(token: string | null, simulationId: string | null, baselineId: string | null) {
  return useQuery({
    queryKey: ["simulation-compare", token, simulationId, baselineId],
    queryFn: () => compareSimulation(token as string, simulationId as string, baselineId as string).then((response) => response.data),
    enabled: Boolean(token && simulationId && baselineId),
  });
}
