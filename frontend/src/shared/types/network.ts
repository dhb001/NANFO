export interface CreateNetworkInput {
  workspace_id: string;
  name: string;
  description?: string | null;
  cidr?: string | null;
}

export type UpdateNetworkInput = Partial<Omit<CreateNetworkInput, "workspace_id">>;

export interface CreateDeviceInput {
  hostname: string;
  device_type: string;
  ip_address?: string | null;
  vendor?: string | null;
  model?: string | null;
  location_hint?: string | null;
  spatial_ref_id?: string | null;
}

export type UpdateDeviceInput = Partial<CreateDeviceInput>;

export interface Network {
  network_id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  cidr: string | null;
  created_at: string;
}

export interface NetworkList {
  items: Network[];
  total: number;
  page: number;
  page_size: number;
}

export interface Device {
  device_id: string;
  network_id: string;
  hostname: string;
  ip_address: string | null;
  device_type: string;
  vendor: string | null;
  model: string | null;
  location_hint: string | null;
  spatial_ref_id: string | null;
  status: string;
  created_at: string;
}

export interface DeviceList {
  items: Device[];
  total: number;
  page: number;
  page_size: number;
}

export interface TopologyNode {
  device_id: string;
  hostname: string;
  device_type: string;
  status: string;
  spatial_ref_id: string | null;
}

export interface TopologyEdge {
  source_id: string;
  target_id: string;
  edge_type: string;
  metadata: Record<string, unknown>;
}

export interface TopologyGraph {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

export interface TopologyNodeWithNeighbours {
  node: TopologyNode;
  neighbours: Array<
    TopologyNode & {
      edge_type: string;
      direction: string;
    }
  >;
}

export interface TopologyNeighbourEdge extends TopologyNode {
  edge_type: string;
  edge_metadata: Record<string, unknown>;
  direction: string;
  hop_depth: number;
}

export interface TopologyDeviceNeighbours {
  device: TopologyNode;
  neighbours: TopologyNeighbourEdge[];
  depth: number;
  total: number;
}

export interface TopologyImpactNode extends TopologyNode {
  hop_depth: number;
}

export interface TopologyImpact {
  device: TopologyNode;
  impacts: TopologyImpactNode[];
  max_hops: number;
  total: number;
}

export interface TopologyReconcileResult {
  reconcile_id: string;
  network_id: string;
  status: string;
  checked_nodes: number;
  checked_edges: number;
  missing_workspace_nodes: number;
  workspace_backfilled_nodes: number;
  warning: string | null;
}

export interface CampusBuildingRecord {
  campus_building_id: string;
  network_id: string;
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
  wall_material: string | null;
  attenuation_db: number | null;
  source: string | null;
  created_at: string;
  updated_at: string;
}

export interface CampusBuildingList {
  items: CampusBuildingRecord[];
  total: number;
}

export interface UpsertCampusBuildingInput {
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
}

export interface AssetRegistration {
  version: 1;
  translation: { x: number; y: number; z: number };
  rotation: { x: number; y: number; z: number };
  scale: { x: number; y: number; z: number };
  target_units: "m";
  target_up_axis: "y";
  source: string;
}

export interface CampusModelAssetRecord {
  registration?: AssetRegistration | null;
  storage_backend?: "inline" | "local_cas";
  download_path?: string | null;
  campus_model_asset_id: string;
  network_id: string;
  model_file_name: string;
  model_mime_type: string;
  model_data_base64?: string | null;
  model_sha256: string;
  model_size_bytes: number;
  mapping_by_device_id: Record<string, string>;
  source: string | null;
  created_at: string;
  updated_at: string;
}

export interface CampusModelAssetList {
  items: CampusModelAssetRecord[];
  total: number;
  page?: number;
  page_size?: number;
}

export interface UpsertCampusModelAssetInput {
  registration?: AssetRegistration | null;
  model_file_name: string;
  model_mime_type: string;
  model_data_base64: string;
  model_sha256: string;
  model_size_bytes: number;
  mapping_by_device_id: Record<string, string>;
  source?: string | null;
  replace_existing?: boolean;
}

export type DeviceGroupType = "site_hierarchy" | "functional" | "operational" | "custom";

export interface DeviceGroupRecord {
  device_group_id: string;
  network_id: string;
  group_key: string;
  name: string;
  group_type: DeviceGroupType;
  description: string | null;
  selector: Record<string, string>;
  device_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface DeviceGroupList {
  items: DeviceGroupRecord[];
  total: number;
}

export interface UpsertDeviceGroupInput {
  group_key: string;
  name: string;
  group_type: DeviceGroupType;
  description?: string | null;
  selector?: Record<string, string>;
  device_ids?: string[];
}
