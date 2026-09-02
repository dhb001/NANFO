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
