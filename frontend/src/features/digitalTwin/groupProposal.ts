import type { DeviceGroupRecord, UpsertDeviceGroupInput } from "@/shared/types/network";
import { deriveSpatialBuildingScope } from "./campusBuildings";
import { parseSpatialRefPath } from "./spatialProjection";

/**
 * Derived campus device groups, computed from PERSISTED device spatial references only.
 *
 * Session-only sidecar mappings never influence scope or membership. Membership is not
 * classified in the browser: selectors (`site_prefix`, `functional_group`) are resolved
 * by the Network service with its own device-type classifier and persisted
 * `spatial_ref_id` values. Explicit `device_ids` are sent only for the network-wide
 * operations group, which no selector can express.
 */

export interface GroupProposalNode {
  id: string;
  persistedSpatialRefId?: string | null;
}

export interface GroupFocus {
  buildingId: string | null;
  floorKey: string | null;
}

/** C8: `expected_updated_at` makes a concurrent change fail with 409 DEVICE_GROUP_CONFLICT. */
export type ConcurrentGroupInput = UpsertDeviceGroupInput & { expected_updated_at?: string };

export interface ProposedGroup {
  input: ConcurrentGroupInput;
  action: "create" | "update";
  existing: DeviceGroupRecord | null;
  changes: string[];
}

export interface GroupProposal {
  scope: {
    source: "focus" | "persisted_majority" | "network";
    sitePrefix: string | null;
    buildingId: string | null;
    floorKey: string | null;
    label: string;
  };
  groups: ProposedGroup[];
  /** Devices whose persisted spatial_ref_id lies under the scope (preview only; the server decides). */
  persistedDevicesInScope: number;
  /** Devices without a persisted spatial_ref_id (they cannot match a site selector). */
  devicesWithoutPersistedRef: number;
  blockedReason: string | null;
}

const MAX_GROUP_KEY = 160;
const MAX_EXPLICIT_MEMBERS = 5000;

function pickMostCommon(values: ReadonlyArray<string | null>): string | null {
  const counts = new Map<string, number>();
  for (const value of values) if (value) counts.set(value, (counts.get(value) ?? 0) + 1);
  let selected: string | null = null;
  let selectedCount = -1;
  for (const [value, count] of counts) {
    if (count > selectedCount || (count === selectedCount && selected !== null && value.localeCompare(selected) < 0)) {
      selected = value;
      selectedCount = count;
    }
  }
  return selected;
}

export function toSafeGroupToken(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9:_-]+/g, "-").replace(/^-+|-+$/g, "") || "scope";
}

/** Raw lower-cased path prefix exactly as the server compares it (`startswith` on the stored value). */
function rawPrefix(spatialRefId: string, depth: 2 | 3): string | null {
  const path = parseSpatialRefPath(spatialRefId);
  if (!path || path.segments.length < depth) return null;
  const raw = spatialRefId.trim().split("/").map((segment) => segment.trim()).filter(Boolean);
  return raw.length >= depth ? raw.slice(0, depth).join("/").toLowerCase() : null;
}

function describeChanges(existing: DeviceGroupRecord, input: ConcurrentGroupInput): string[] {
  const changes: string[] = [];
  if (existing.name !== input.name) changes.push(`name "${existing.name}" -> "${input.name}"`);
  if (existing.group_type !== input.group_type) changes.push(`type ${existing.group_type} -> ${input.group_type}`);
  const before = JSON.stringify(Object.entries(existing.selector ?? {}).sort());
  const after = JSON.stringify(Object.entries(input.selector ?? {}).sort());
  if (before !== after) changes.push("selector changed");
  const explicit = input.device_ids ?? [];
  if (explicit.length) {
    const current = new Set(existing.device_ids);
    const added = explicit.filter((id) => !current.has(id)).length;
    const removed = existing.device_ids.filter((id) => !explicit.includes(id)).length;
    if (added || removed) changes.push(`members +${added} / -${removed}`);
  } else {
    changes.push(`members re-resolved by the server (currently ${existing.device_ids.length})`);
  }
  return changes;
}

export function deriveGroupProposal({ nodes, focus, existingGroups }: {
  nodes: readonly GroupProposalNode[];
  focus: GroupFocus;
  existingGroups: readonly DeviceGroupRecord[];
}): GroupProposal {
  const persisted = nodes.map((node) => {
    const ref = typeof node.persistedSpatialRefId === "string" && node.persistedSpatialRefId.trim() ? node.persistedSpatialRefId.trim() : null;
    return { node, ref, scope: deriveSpatialBuildingScope(ref) };
  });
  const devicesWithoutPersistedRef = persisted.filter((item) => !item.ref).length;
  const source: GroupProposal["scope"]["source"] = focus.buildingId ? "focus" : "persisted_majority";
  const buildingId = focus.buildingId ?? pickMostCommon(persisted.map((item) => item.scope.buildingId));
  const floorKey = focus.buildingId
    ? focus.floorKey
    : pickMostCommon(persisted.filter((item) => buildingId && item.scope.buildingId === buildingId).map((item) => item.scope.floorKey));
  const inScope = persisted.filter((item) => item.ref && buildingId && item.scope.buildingId === buildingId && (!floorKey || item.scope.floorKey === floorKey));
  // The prefix comes from a real persisted reference so it matches the server's comparison.
  const sitePrefix = inScope.length ? rawPrefix(inScope[0].ref!, floorKey ? 3 : 2) : null;
  const scopeSource = sitePrefix ? source : "network";
  const [, buildingKey] = sitePrefix ? (buildingId ?? "").split(":") : [];
  const label = sitePrefix ? [buildingKey?.toUpperCase() ?? null, floorKey?.toUpperCase() ?? null].filter(Boolean).join(" ") : "";
  const token = toSafeGroupToken(sitePrefix ?? "network");
  const existingByKey = new Map(existingGroups.map((group) => [group.group_key, group]));

  const drafts: ConcurrentGroupInput[] = [
    {
      group_key: `wireless-${token}`.slice(0, MAX_GROUP_KEY),
      name: label ? `${label} Wireless` : "Wireless Devices",
      group_type: "functional",
      selector: sitePrefix ? { functional_group: "wireless", site_prefix: sitePrefix } : { functional_group: "wireless" },
      device_ids: [],
    },
    {
      group_key: `ops-${token}`.slice(0, MAX_GROUP_KEY),
      name: label ? `${label} Operations` : "Operations Devices",
      group_type: "operational",
      selector: sitePrefix ? { site_prefix: sitePrefix } : {},
      device_ids: sitePrefix ? [] : [...new Set(nodes.map((node) => node.id))].sort(),
    },
  ];

  const groups: ProposedGroup[] = drafts.map((draft) => {
    const existing = existingByKey.get(draft.group_key) ?? null;
    const input: ConcurrentGroupInput = existing ? { ...draft, expected_updated_at: existing.updated_at } : draft;
    return { input, action: existing ? "update" : "create", existing, changes: existing ? describeChanges(existing, input) : [] };
  });

  let blockedReason: string | null = null;
  if (nodes.length === 0) blockedReason = "No devices in the current topology.";
  else if (focus.buildingId && !sitePrefix) blockedReason = "No device has a persisted spatial_ref_id in the focused building. Persist device mappings first; session-only mappings are never used for groups.";
  else if (!sitePrefix && nodes.length > MAX_EXPLICIT_MEMBERS) blockedReason = `A network-wide group can list at most ${MAX_EXPLICIT_MEMBERS} devices. Focus a building instead.`;

  return {
    scope: { source: scopeSource, sitePrefix, buildingId: sitePrefix ? buildingId : null, floorKey: sitePrefix ? floorKey : null, label: label || "Network" },
    groups,
    persistedDevicesInScope: sitePrefix ? inScope.length : nodes.length,
    devicesWithoutPersistedRef,
    blockedReason,
  };
}

export interface GroupConflict {
  groupKey: string;
  change: "created" | "deleted" | "modified";
  fields: string[];
  previousUpdatedAt: string | null;
  currentUpdatedAt: string | null;
  previousMembers: number | null;
  currentMembers: number | null;
}

/** What changed on the server between the read the proposal used and a reload after a 409. */
export function describeGroupConflicts(previous: readonly DeviceGroupRecord[], current: readonly DeviceGroupRecord[], keys: readonly string[]): GroupConflict[] {
  const before = new Map(previous.map((group) => [group.group_key, group]));
  const after = new Map(current.map((group) => [group.group_key, group]));
  const conflicts: GroupConflict[] = [];
  for (const key of keys) {
    const old = before.get(key) ?? null;
    const now = after.get(key) ?? null;
    if (!old && !now) continue;
    if (old && now && old.updated_at === now.updated_at) continue;
    const fields: string[] = [];
    if (old && now) {
      if (old.name !== now.name) fields.push("name");
      if (old.group_type !== now.group_type) fields.push("group_type");
      if (old.description !== now.description) fields.push("description");
      if (JSON.stringify(Object.entries(old.selector).sort()) !== JSON.stringify(Object.entries(now.selector).sort())) fields.push("selector");
      if (JSON.stringify([...old.device_ids].sort()) !== JSON.stringify([...now.device_ids].sort())) fields.push("device_ids");
    }
    conflicts.push({
      groupKey: key,
      change: !old ? "created" : !now ? "deleted" : "modified",
      fields,
      previousUpdatedAt: old?.updated_at ?? null,
      currentUpdatedAt: now?.updated_at ?? null,
      previousMembers: old?.device_ids.length ?? null,
      currentMembers: now?.device_ids.length ?? null,
    });
  }
  return conflicts;
}
