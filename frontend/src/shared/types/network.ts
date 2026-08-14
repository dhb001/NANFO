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
