export interface WebSocketErrorData {
  code: "WS_UNAUTHORIZED" | "WS_UNKNOWN_CHANNEL" | "WS_BACKPRESSURE" | "WS_INVALID_FILTER" | string;
  message: string;
}

export interface WebSocketEnvelope<T> {
  event: string;
  correlation_id?: string;
  timestamp?: string;
  channel?: string;
  filters?: Record<string, unknown>;
  data?: T;
}

export interface TopologyDeltaData {
  delta_type: "add" | "update" | "remove";
  node: {
    device_id: string;
    hostname?: string;
    device_type?: string;
    status?: string;
    spatial_ref_id?: string | null;
  };
}

export interface TelemetryDeltaData {
  delta_type: "metric";
  metric: {
    event_id: string;
    device_id: string;
    network_id: string;
    workspace_id: string;
    metric: string;
    value: number;
    unit: string | null;
    observed_at: string;
    source: string;
    tags: Record<string, unknown>;
  };
}

export interface AlertDeltaData {
  delta_type: "add" | "ack" | "resolve";
  alert: {
    event_id: string;
    event_type: string;
    source: string;
    payload: Record<string, unknown>;
  };
}

export interface DigitalTwinDeltaData {
  delta_type: "update";
  scene_object: {
    id: string;
    object_type: "simulation_state" | "intent_state" | string;
    simulation_id?: string;
    scenario_id?: string;
    state?: string;
    status?: string;
    risk_gate?: string;
    intent_id?: string;
    spatial_ref_id?: string | null;
    spatial_metadata?: Record<string, unknown>;
    changed_fields?: Record<string, unknown>;
  };
}
