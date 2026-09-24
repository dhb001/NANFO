import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { samePageSeries } from "@/shared/lib/queryKeys";
import { useEffect } from "react";
import { useSessionScope } from "@/features/auth/sessionScope";
import type { ScenarioConfig } from "@/shared/types/simulation";
import {
  branchSimulation,
  compareSimulation,
  getSimulationDetail,
  pauseSimulation,
  startSimulation,
  listSimulations,
} from "@/features/simulation/api";

export function useSimulationHistory(token: string | null, workspaceId: string | null, networkId: string | null, page: number) {
  const session = useSessionScope();
  const queryKey = ["simulation", session.key, session.authority, "history", page];
  return useQuery({
    queryKey,
    queryFn: ({ signal }) => session.read((credential) => listSimulations(credential, workspaceId!, networkId, page, signal), signal).then((response) => response.data),
    enabled: Boolean(token && workspaceId),
    placeholderData: (previous, previousQuery) => samePageSeries(previousQuery?.queryKey, queryKey, 4) ? keepPreviousData(previous) : undefined,
  });
}

export function useStartSimulation(token: string | null) {
  const session = useSessionScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { network_id: string; scenario_name: string; simulation_id?: string; validation_checks: string[]; scenario_config?: ScenarioConfig }) =>
      session.request((credential) => startSimulation(credential || token!, body)).then((response) => response.data),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: ["simulation", session.key] }),
  });
}

export function usePauseSimulation(token: string | null) {
  const session = useSessionScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (simulationId: string) => session.request((credential) => pauseSimulation(credential || token!, simulationId)).then((response) => response.data),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: ["simulation", session.key] }),
  });
}

export function useBranchSimulation(token: string | null) {
  const session = useSessionScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { parentSimulationId: string; scenarioName: string; scenarioConfig?: ScenarioConfig }) =>
      session.request((credential) => branchSimulation(credential || token!, body.parentSimulationId, body.scenarioName, body.scenarioConfig)).then((response) => response.data),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: ["simulation", session.key] }),
  });
}

export function useSimulationDetail(token: string | null, simulationId: string | null) {
  const session = useSessionScope();
  const client = useQueryClient();
  const result = useQuery({
    queryKey: ["simulation", session.key, session.authority, simulationId],
    queryFn: ({ signal }) => session.read((credential) => getSimulationDetail(credential, simulationId as string, signal), signal).then((response) => response.data),
    enabled: Boolean(token && simulationId),
    refetchInterval: (query) => query.state.dataUpdateCount < 40 && ["queued", "running"].includes(query.state.data?.status ?? "") ? 3000 : false,
  });
  useEffect(() => {
    if (simulationId && result.data?.status === "completed") void client.invalidateQueries({ queryKey: ["simulation-compare", session.key] });
  }, [client, session.key, simulationId, result.data?.status, result.dataUpdatedAt]);
  return result;
}

export function useSimulationCompare(token: string | null, simulationId: string | null, baselineId: string | null) {
  const session = useSessionScope();
  return useQuery({
    queryKey: ["simulation-compare", session.key, session.authority, simulationId, baselineId],
    queryFn: ({ signal }) => session.read((credential) => compareSimulation(credential, simulationId as string, baselineId as string, signal), signal).then((response) => response.data),
    enabled: Boolean(token && simulationId && baselineId),
  });
}
