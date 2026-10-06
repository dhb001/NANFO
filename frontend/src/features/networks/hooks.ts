import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSessionScope } from "@/features/auth/sessionScope";
import { samePageSeries, scopedKey } from "@/shared/lib/queryKeys";
import { useAuthStore } from "@/shared/state/auth-store";
import {
  createDevice,
  createNetwork,
  listCampusBuildings,
  listCampusModelAssets,
  listDeviceGroups,
  listDevices,
  listNetworks,
  upsertCampusModelAssets,
  upsertCampusBuildings,
  upsertDeviceGroups,
  updateDeviceSpatialRef,
  updateNetwork,
  deleteNetwork,
  updateDevice,
  deleteDevice,
} from "@/features/networks/api";
import type {
  UpsertCampusModelAssetInput,
  UpsertDeviceGroupInput,
  CreateNetworkInput,
  CreateDeviceInput,
  UpdateNetworkInput,
  UpdateDeviceInput,
} from "@/shared/types/network";

// Query identity is the session scope, never the access token (ADR-028): a
// rotation keeps caches and mounted views (including the Twin canvas). The
// `token` parameters only gate `enabled`; reads use the current credential.

/** Current credential for a write; the render-time token may already be rotated. */
function currentToken(fallback: string | null) {
  return useAuthStore.getState().accessToken ?? fallback;
}

export function useNetworks(token: string | null, workspaceId: string | null, page = 1, pageSize = 20) {
  const scope = useSessionScope();
  const queryKey = scopedKey(scope, "networks", workspaceId, page, pageSize);
  return useQuery({
    queryKey,
    queryFn: async ({ signal }) => (await scope.read((credential) => listNetworks(credential, workspaceId as string, page, pageSize, signal), signal)).data,
    enabled: Boolean(token && workspaceId),
    placeholderData: (previous, previousQuery) => samePageSeries(previousQuery?.queryKey, queryKey, 4) ? keepPreviousData(previous) : undefined,
  });
}

export function useCreateNetwork(token: string | null, workspaceId: string | null) {
  const queryClient = useQueryClient();
  const scope = useSessionScope();
  return useMutation({
    mutationFn: async (input: string | Omit<CreateNetworkInput, "workspace_id">) => {
      const credential = currentToken(token);
      if (!credential || !workspaceId) throw new Error("Workspace context is required.");
      const response = await createNetwork(credential, { ...(typeof input === "string" ? { name: input } : input), workspace_id: workspaceId });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: scopedKey(scope, "networks") });
    },
  });
}

export function useDevices(token: string | null, networkId: string | null, page = 1, pageSize = 20) {
  const scope = useSessionScope();
  const queryKey = scopedKey(scope, "devices", networkId, page, pageSize);
  return useQuery({
    queryKey,
    queryFn: async ({ signal }) => (await scope.read((credential) => listDevices(credential, networkId as string, page, pageSize, signal), signal)).data,
    enabled: Boolean(token && networkId),
    placeholderData: (previous, previousQuery) => samePageSeries(previousQuery?.queryKey, queryKey, 4) ? keepPreviousData(previous) : undefined,
  });
}

function useInvalidateInventory() {
  const client = useQueryClient();
  const scope = useSessionScope();
  return (domains: string[]) => {
    for (const domain of domains) void client.invalidateQueries({ queryKey: scopedKey(scope, domain) });
  };
}

export function useCreateDevice(token: string | null, networkId: string | null) {
  const invalidate = useInvalidateInventory();
  return useMutation({
    mutationFn: async (input: CreateDeviceInput | { hostname: string; deviceType: string; spatialRefId?: string }) => {
      const credential = currentToken(token);
      if (!credential || !networkId) throw new Error("Network context is required.");
      const response = await createDevice(credential, networkId, "device_type" in input ? input : {
        hostname: input.hostname,
        device_type: input.deviceType,
        spatial_ref_id: input.spatialRefId ?? null,
      });
      return response.data;
    },
    onSuccess: () => invalidate(["devices", "topology"]),
  });
}

export function useUpdateNetwork(token: string | null, workspaceId: string | null) {
  const invalidate = useInvalidateInventory();
  return useMutation({
    mutationFn: async ({ networkId, changes }: { networkId: string; changes: UpdateNetworkInput }) => {
      const credential = currentToken(token);
      if (!credential || !workspaceId) throw new Error("Workspace context is required.");
      return (await updateNetwork(credential, networkId, changes)).data;
    },
    onSuccess: () => invalidate(["networks"]),
  });
}

export function useDeleteNetwork(token: string | null, workspaceId: string | null) {
  const invalidate = useInvalidateInventory();
  return useMutation({
    mutationFn: async (networkId: string) => {
      const credential = currentToken(token);
      if (!credential || !workspaceId) throw new Error("Workspace context is required.");
      await deleteNetwork(credential, networkId);
    },
    onSuccess: () => invalidate(["networks"]),
  });
}

export function useUpdateDevice(token: string | null, networkId: string | null) {
  const invalidate = useInvalidateInventory();
  return useMutation({
    mutationFn: async ({ deviceId, changes }: { deviceId: string; changes: UpdateDeviceInput }) => {
      const credential = currentToken(token);
      if (!credential || !networkId) throw new Error("Network context is required.");
      return (await updateDevice(credential, networkId, deviceId, changes)).data;
    },
    onSuccess: () => invalidate(["devices", "topology", "topology-node"]),
  });
}

export function useDeleteDevice(token: string | null, networkId: string | null) {
  const invalidate = useInvalidateInventory();
  return useMutation({
    mutationFn: async (deviceId: string) => {
      const credential = currentToken(token);
      if (!credential || !networkId) throw new Error("Network context is required.");
      await deleteDevice(credential, networkId, deviceId);
    },
    onSuccess: () => invalidate(["devices", "topology", "topology-node"]),
  });
}

export function useUpdateDeviceSpatialRef(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  const scope = useSessionScope();
  return useMutation({
    mutationFn: async (input: { deviceId: string; spatialRefId: string | null }) => {
      const credential = currentToken(token);
      if (!credential || !networkId) {
        throw new Error("Network context is required to update spatial references.");
      }
      const response = await updateDeviceSpatialRef(
        credential,
        networkId,
        input.deviceId,
        input.spatialRefId,
      );
      return response.data;
    },
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: scopedKey(scope, "devices", networkId) });
      void queryClient.invalidateQueries({ queryKey: scopedKey(scope, "topology", networkId) });
      void queryClient.invalidateQueries({ queryKey: scopedKey(scope, "topology-node", variables.deviceId) });
    },
  });
}

export function useCampusBuildings(token: string | null, networkId: string | null) {
  const scope = useSessionScope();
  return useQuery({
    queryKey: scopedKey(scope, "campus-buildings", networkId),
    queryFn: async ({ signal }) => (await scope.read((credential) => listCampusBuildings(credential, networkId as string, signal), signal)).data,
    enabled: Boolean(token && networkId),
  });
}

export function useUpsertCampusBuildings(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  const scope = useSessionScope();
  return useMutation({
    mutationFn: async (input: {
      buildings: Array<{
        building_id: string;
        campus_key: string;
        building_key: string;
        label: string;
        geometry: "box" | "extrude";
        x: number;
        z: number;
        base_y: number;
        width: number;
        depth: number;
        height: number;
        floors: number;
        footprint: Array<[number, number]>;
        wall_material?: string | null;
        attenuation_db?: number | null;
        source?: string | null;
      }>;
      replaceExisting?: boolean;
    }) => {
      const credential = currentToken(token);
      if (!credential || !networkId) {
        throw new Error("Network context is required to update campus buildings.");
      }
      const response = await upsertCampusBuildings(credential, networkId, input);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: scopedKey(scope, "campus-buildings", networkId) });
    },
  });
}

export function useCampusModelAssets(token: string | null, networkId: string | null, page = 1, pageSize = 20) {
  const scope = useSessionScope();
  const readPage = async (targetPage: number, signal?: AbortSignal) => {
    const response = await scope.read((credential) => listCampusModelAssets(credential, networkId as string, targetPage, pageSize, signal), signal);
    return response.data;
  };
  const queryKey = scopedKey(scope, "campus-model-assets", networkId, page, pageSize);
  const query = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      return readPage(page, signal);
    },
    enabled: Boolean(token && networkId),
    placeholderData: (previous, previousQuery) => samePageSeries(previousQuery?.queryKey, queryKey, 4) ? keepPreviousData(previous) : undefined,
  });
  return { ...query, readPage };
}

export function useUpsertCampusModelAssets(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  const scope = useSessionScope();
  return useMutation({
    mutationFn: async (input: UpsertCampusModelAssetInput) => {
      const credential = currentToken(token);
      if (!credential || !networkId) {
        throw new Error("Network context is required to update campus model assets.");
      }
      const response = await upsertCampusModelAssets(credential, networkId, input);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: scopedKey(scope, "campus-model-assets") });
    },
  });
}

export function useDeviceGroups(token: string | null, networkId: string | null) {
  const scope = useSessionScope();
  return useQuery({
    queryKey: scopedKey(scope, "device-groups", networkId),
    queryFn: async ({ signal }) => (await scope.read((credential) => listDeviceGroups(credential, networkId as string, signal), signal)).data,
    enabled: Boolean(token && networkId),
  });
}

export function useUpsertDeviceGroups(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  const scope = useSessionScope();
  return useMutation({
    mutationFn: async (input: {
      groups: UpsertDeviceGroupInput[];
      replaceExisting?: boolean;
    }) => {
      const credential = currentToken(token);
      if (!credential || !networkId) {
        throw new Error("Network context is required to update device groups.");
      }
      const response = await upsertDeviceGroups(credential, networkId, input);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: scopedKey(scope, "device-groups", networkId) });
    },
  });
}
