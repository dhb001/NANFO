import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type { ScenarioConfig } from "@/shared/types/simulation";
import {
  branchSimulation,
  compareSimulation,
  getSimulationDetail,
  pauseSimulation,
  startSimulation,
} from "@/features/simulation/api";

export function useStartSimulation(token: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { network_id: string; scenario_name: string; simulation_id?: string; validation_checks: string[]; scenario_config?: ScenarioConfig }) =>
      startSimulation(token as string, body).then((response) => response.data),
    onSuccess: (data) => client.invalidateQueries({ queryKey: ["simulation", token, data.simulation_id] }),
  });
}

export function usePauseSimulation(token: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (simulationId: string) => pauseSimulation(token as string, simulationId).then((response) => response.data),
    onSuccess: (data) => client.invalidateQueries({ queryKey: ["simulation", token, data.simulation_id] }),
  });
}

export function useBranchSimulation(token: string | null) {
  return useMutation({
    mutationFn: (body: { parentSimulationId: string; scenarioName: string; scenarioConfig?: ScenarioConfig }) =>
      branchSimulation(token as string, body.parentSimulationId, body.scenarioName, body.scenarioConfig).then((response) => response.data),
  });
}

export function useSimulationDetail(token: string | null, simulationId: string | null) {
  const client = useQueryClient();
  const result = useQuery({
    queryKey: ["simulation", token, simulationId],
    queryFn: () => getSimulationDetail(token as string, simulationId as string).then((response) => response.data),
    enabled: Boolean(token && simulationId),
    refetchInterval: (query) => query.state.dataUpdateCount < 40 && ["queued", "running"].includes(query.state.data?.status ?? "") ? 3000 : false,
  });
  useEffect(() => {
    if (simulationId && result.data?.status === "completed") void client.invalidateQueries({ queryKey: ["simulation-compare", token] });
  }, [client, token, simulationId, result.data?.status, result.dataUpdatedAt]);
  return result;
}

export function useSimulationCompare(token: string | null, simulationId: string | null, baselineId: string | null) {
  return useQuery({
    queryKey: ["simulation-compare", token, simulationId, baselineId],
    queryFn: () => compareSimulation(token as string, simulationId as string, baselineId as string).then((response) => response.data),
    enabled: Boolean(token && simulationId && baselineId),
  });
}
