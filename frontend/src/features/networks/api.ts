import { apiRequest } from "@/shared/lib/api";
import {
  CampusBuildingList,
  CampusModelAssetList,
  Device,
  DeviceGroupList,
  DeviceList,
  Network,
  NetworkList,
  UpsertCampusModelAssetInput,
  UpsertCampusBuildingInput,
  UpsertDeviceGroupInput,
} from "@/shared/types/network";

interface CreateNetworkInput {
  workspace_id: string;
  name: string;
  description?: string;
  cidr?: string;
}

interface CreateDeviceInput {
  hostname: string;
  ip_address?: string;
  device_type: string;
  vendor?: string;
  model?: string;
  location_hint?: string;
  spatial_ref_id?: string;
}

export function listNetworks(token: string, workspaceId: string, page = 1, pageSize = 20) {
  return apiRequest<NetworkList>(
    `/api/v1/networks?workspace_id=${workspaceId}&page=${page}&page_size=${pageSize}`,
    { token },
  );
}

export function createNetwork(token: string, body: CreateNetworkInput) {
  return apiRequest<Network>("/api/v1/networks", {
    method: "POST",
    body,
    token,
  });
}

export function listDevices(token: string, networkId: string, page = 1, pageSize = 20) {
  return apiRequest<DeviceList>(
    `/api/v1/networks/${networkId}/devices?page=${page}&page_size=${pageSize}`,
    { token },
  );
}

export function createDevice(token: string, networkId: string, body: CreateDeviceInput) {
  return apiRequest<Device>(`/api/v1/networks/${networkId}/devices`, {
    method: "POST",
    body,
    token,
  });
}

export function updateDeviceSpatialRef(token: string, networkId: string, deviceId: string, spatialRefId: string | null) {
  return apiRequest<Device>(`/api/v1/networks/${networkId}/devices/${deviceId}`, {
    method: "PATCH",
    body: { spatial_ref_id: spatialRefId },
    token,
  });
}

export function listCampusBuildings(token: string, networkId: string) {
  return apiRequest<CampusBuildingList>(`/api/v1/networks/${networkId}/campus/buildings`, {
    token,
  });
}

export function upsertCampusBuildings(
  token: string,
  networkId: string,
  input: {
    buildings: UpsertCampusBuildingInput[];
    replaceExisting?: boolean;
  },
) {
  return apiRequest<CampusBuildingList>(`/api/v1/networks/${networkId}/campus/buildings`, {
    method: "POST",
    body: {
      buildings: input.buildings,
      replace_existing: input.replaceExisting ?? true,
    },
    token,
  });
}

export function listCampusModelAssets(token: string, networkId: string) {
  return apiRequest<CampusModelAssetList>(`/api/v1/networks/${networkId}/campus/model-assets`, {
    token,
  });
}

export function upsertCampusModelAssets(token: string, networkId: string, input: UpsertCampusModelAssetInput) {
  return apiRequest<CampusModelAssetList>(`/api/v1/networks/${networkId}/campus/model-assets`, {
    method: "POST",
    body: {
      model_file_name: input.model_file_name,
      model_mime_type: input.model_mime_type,
      model_data_base64: input.model_data_base64,
      model_sha256: input.model_sha256,
      model_size_bytes: input.model_size_bytes,
      mapping_by_device_id: input.mapping_by_device_id,
      source: input.source ?? null,
      replace_existing: input.replace_existing ?? true,
    },
    token,
  });
}

export function listDeviceGroups(token: string, networkId: string) {
  return apiRequest<DeviceGroupList>(`/api/v1/networks/${networkId}/device-groups`, {
    token,
  });
}

export function upsertDeviceGroups(
  token: string,
  networkId: string,
  input: {
    groups: UpsertDeviceGroupInput[];
    replaceExisting?: boolean;
  },
) {
  return apiRequest<DeviceGroupList>(`/api/v1/networks/${networkId}/device-groups`, {
    method: "POST",
    body: {
      replace_existing: input.replaceExisting ?? false,
      groups: input.groups.map((group) => ({
        group_key: group.group_key,
        name: group.name,
        group_type: group.group_type,
        description: group.description ?? null,
        selector: group.selector ?? {},
        device_ids: group.device_ids ?? [],
      })),
    },
    token,
  });
}
