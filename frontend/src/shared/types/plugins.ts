import type { Schema } from "@/shared/types/contracts";

export interface PluginManifest {
  plugin_key: string;
  name: string;
  version: string;
  signer: string;
  signature: string;
  dependencies: Record<string, unknown>;
  sandbox: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

/** Backend `PluginRecordResponse.status` value set (generated from the OpenAPI Literal). */
export type PluginStatus = Schema<"PluginRecordResponse">["status"];

export interface PluginRecord {
  registry_only?: true;
  execution_supported?: false;
  lifecycle_semantics?: "registry_flags_only";
  permissions_status?: "declared_unverified";
  uninstalled_at?: string | null;
  plugin_id: string;
  plugin_key: string;
  name: string;
  version: string;
  manifest: PluginManifest;
  signature_status: string;
  dependency_status: string;
  sandbox_status: string;
  status: PluginStatus;
  enabled: boolean;
  failure_reason: string | null;
  queue_status: string;
  stream_entry_id: string | null;
  warning: string | null;
  installed_at: string;
  updated_at: string;
}

export interface PluginListResult {
  registry_only?: true;
  execution_supported?: false;
  lifecycle_semantics?: "registry_flags_only";
  items: PluginRecord[];
  total: number;
  status_counts: Record<string, number>;
}

export interface PluginActionResult extends PluginRecord {
  idempotent_replay: boolean;
}

export interface InstallPluginRequest {
  plugin_key: string;
  name: string;
  version: string;
  signer: string;
  signature: string;
  dependencies: Record<string, unknown>;
  sandbox: Record<string, unknown>;
  metadata: Record<string, unknown>;
}
