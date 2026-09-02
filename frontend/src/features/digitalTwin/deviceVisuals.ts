/**
 * Central device visual metadata for the Digital Twin scene.
 *
 * Why this module exists
 * ----------------------
 * Colour and size decisions used to live inline inside `TwinScene.tsx`, which meant
 * every renderer that wanted to show a device had to re-derive them. This module is the
 * single source of truth: renderers read it, they never invent their own palette.
 *
 * Design constraints honoured here:
 * - Pure and synchronous. No React, no three.js imports, so it is fully unit-testable.
 * - The existing per-node mesh architecture is preserved. This module only describes
 *   *what* to draw (geometry kind, colour, radius); `TwinScene` still decides *how*.
 * - Tier names deliberately mirror the backend taxonomy in
 *   `app/modules/network/synthetic_topology.py` so the spatial view and the topology
 *   hierarchy agree on what "distribution" means.
 * - Nothing is invented. Alert state is an explicit input, never derived from unrelated
 *   signals such as congestion (see `deriveAlertingDeviceIds`).
 */

import type { CongestionSeverity } from "@/features/digitalTwin/sceneAdapter";

/** Network hierarchy tier. Mirrors the backend synthetic topology planner. */
export type DeviceTier = "perimeter" | "core" | "distribution" | "access" | "leaf";

/** Primitive shape family. Kept small on purpose -- these map to existing R3F geometry. */
export type DeviceGeometryKind =
  | "icosahedron"
  | "octahedron"
  | "box"
  | "cylinder"
  | "cone"
  | "sphere";

/** Which signal drives the node's base colour. */
export type DeviceColorMode = "type" | "status" | "congestion";

export interface DeviceVisualDefinition {
  /** Canonical `device_type` key as stored on the device record. */
  typeKey: string;
  /** Human-readable label for legends and the inspector. */
  label: string;
  tier: DeviceTier;
  /** Colour used when `colorMode === "type"`. */
  typeColor: string;
  geometry: DeviceGeometryKind;
  /** Unselected radius in scene units. */
  baseRadius: number;
  /** Higher wins when the label budget is exhausted. */
  labelPriority: number;
}

// --------------------------------------------------------------------------------------
// Colour tokens
// --------------------------------------------------------------------------------------

/**
 * Status colours. These values are carried over verbatim from the previous inline
 * implementation in `TwinScene.tsx` so existing visuals do not shift.
 */
export const STATUS_COLORS = {
  active: "#2ca774",
  offline: "#d1780f",
  deleted: "#c93f2e",
  unknown: "#2b70c8",
} as const;

/** Congestion colours, also carried over verbatim. */
export const CONGESTION_COLORS = {
  low: "#2ca774",
  medium: "#d1780f",
  high: "#c93f2e",
  neutral: "#6f8291",
} as const;

export const SELECTION_EMISSIVE = "#a6ffd4";
export const SELECTION_EMISSIVE_INTENSITY = 0.38;
export const BASE_EMISSIVE = "#103824";
export const BASE_EMISSIVE_INTENSITY = 0.12;

/** Alert outline colour. Only applied when a real alert is supplied. */
export const ALERT_OUTLINE_COLOR = "#c93f2e";
export const ALERT_EMISSIVE = "#ffb4a6";
export const ALERT_EMISSIVE_INTENSITY = 0.34;

/**
 * Selected nodes grow by this factor. Chosen to reproduce the previous hardcoded
 * 0.52 -> 0.72 jump for a default-sized node.
 */
export const SELECTED_RADIUS_SCALE = 1.385;

// --------------------------------------------------------------------------------------
// Device catalogue
// --------------------------------------------------------------------------------------

const LABEL_PRIORITY_BY_TIER: Record<DeviceTier, number> = {
  core: 100,
  perimeter: 90,
  distribution: 70,
  access: 50,
  leaf: 10,
};

function definition(
  typeKey: string,
  label: string,
  tier: DeviceTier,
  typeColor: string,
  geometry: DeviceGeometryKind,
  baseRadius: number,
  labelPriorityOverride?: number,
): DeviceVisualDefinition {
  return {
    typeKey,
    label,
    tier,
    typeColor,
    geometry,
    baseRadius,
    labelPriority: labelPriorityOverride ?? LABEL_PRIORITY_BY_TIER[tier],
  };
}

/**
 * Canonical catalogue. Covers every `device_type` produced by the Strathmore demo
 * generator plus the generic `switch`/`core_router` aliases used elsewhere.
 *
 * Geometry is varied per class so device types are distinguishable at a glance --
 * this is the Phase 2 goal -- while still using plain R3F primitives.
 */
export const DEVICE_VISUAL_DEFINITIONS: readonly DeviceVisualDefinition[] = [
  definition("firewall", "Firewall", "perimeter", "#b3341f", "box", 0.7),
  definition("router", "Core router", "core", "#2b4fc8", "octahedron", 0.78),
  definition("core_router", "Core router", "core", "#2b4fc8", "octahedron", 0.78),
  definition("distribution_switch", "Distribution switch", "distribution", "#7a4fc8", "cylinder", 0.64),
  definition("access_switch", "Access switch", "access", "#2f8f99", "box", 0.56),
  definition("switch", "Switch", "access", "#2f8f99", "box", 0.56),
  definition("wireless_ap", "Wireless AP", "leaf", "#1f9d6b", "cone", 0.46, 40),
  definition("server", "Server", "leaf", "#3d6b8f", "box", 0.52, 30),
  definition("security_gateway", "Security gateway", "leaf", "#c26a1a", "octahedron", 0.44, 25),
  definition("ups", "UPS", "leaf", "#8a7b2f", "cylinder", 0.42, 20),
  definition("lab_endpoint", "Lab endpoint", "leaf", "#6f8291", "icosahedron", 0.38),
] as const;

/** Fallback for device types not present in the catalogue. Never promoted to core. */
export const FALLBACK_DEVICE_VISUAL: DeviceVisualDefinition = definition(
  "device",
  "Device",
  "leaf",
  "#6f8291",
  "icosahedron",
  0.5,
);

const DEFINITIONS_BY_TYPE: ReadonlyMap<string, DeviceVisualDefinition> = new Map(
  DEVICE_VISUAL_DEFINITIONS.map((item) => [item.typeKey, item]),
);

/** Normalise a raw `device_type` into a catalogue key. */
export function normalizeDeviceType(deviceType: string | null | undefined): string {
  return (deviceType ?? "").trim().toLowerCase().replace(/[\s-]+/g, "_");
}

/** Resolve the visual definition for a device type, falling back safely. */
export function getDeviceVisualDefinition(
  deviceType: string | null | undefined,
): DeviceVisualDefinition {
  return DEFINITIONS_BY_TYPE.get(normalizeDeviceType(deviceType)) ?? FALLBACK_DEVICE_VISUAL;
}

/** Tier for a device type. Convenience wrapper used by grouping/filtering code. */
export function getDeviceTier(deviceType: string | null | undefined): DeviceTier {
  return getDeviceVisualDefinition(deviceType).tier;
}

// --------------------------------------------------------------------------------------
// Colour resolution
// --------------------------------------------------------------------------------------

export function statusColor(status: string | null | undefined): string {
  const normalized = (status ?? "").trim().toLowerCase();
  if (normalized === "active") {
    return STATUS_COLORS.active;
  }
  if (normalized === "offline") {
    return STATUS_COLORS.offline;
  }
  if (normalized === "deleted") {
    return STATUS_COLORS.deleted;
  }
  return STATUS_COLORS.unknown;
}

export function congestionColor(severity: CongestionSeverity): string {
  if (severity === "low") {
    return CONGESTION_COLORS.low;
  }
  if (severity === "medium") {
    return CONGESTION_COLORS.medium;
  }
  if (severity === "high") {
    return CONGESTION_COLORS.high;
  }
  return CONGESTION_COLORS.neutral;
}

// --------------------------------------------------------------------------------------
// Full visual state resolution
// --------------------------------------------------------------------------------------

export interface DeviceVisualInput {
  deviceType: string | null | undefined;
  status: string | null | undefined;
  congestionSeverity: CongestionSeverity;
  selected?: boolean;
  /**
   * Whether this device has an active alert. MUST come from real alert data.
   * Never derive it from congestion -- those are different signals.
   */
  alerting?: boolean;
  colorMode?: DeviceColorMode;
  /** Whether the congestion ring should be displayed. */
  showCongestionRing?: boolean;
}

export interface ResolvedDeviceVisual {
  definition: DeviceVisualDefinition;
  color: string;
  emissive: string;
  emissiveIntensity: number;
  radius: number;
  /** Congestion ring colour, or null when congestion is not being shown. */
  ringColor: string | null;
  /** Alert outline colour, or null when the device has no active alert. */
  outlineColor: string | null;
  tier: DeviceTier;
}

/**
 * Resolve every visual property for one device in one place.
 *
 * Precedence for the base colour is explicit: the caller chooses `colorMode`, and the
 * chosen signal always wins. Selection and alert state are expressed through emissive
 * glow, radius and outline instead of overwriting the base colour, so an operator can
 * read type/status/congestion and selection/alert simultaneously.
 */
export function resolveDeviceVisual(input: DeviceVisualInput): ResolvedDeviceVisual {
  const definition = getDeviceVisualDefinition(input.deviceType);
  const colorMode: DeviceColorMode = input.colorMode ?? "type";
  const selected = input.selected === true;
  const alerting = input.alerting === true;

  let color: string;
  if (colorMode === "congestion") {
    color = congestionColor(input.congestionSeverity);
  } else if (colorMode === "type") {
    color = definition.typeColor;
  } else {
    color = statusColor(input.status);
  }

  // Status drives the default glow so type colour can stay visible on the mesh body.
  let emissive = statusColor(input.status);
  let emissiveIntensity = BASE_EMISSIVE_INTENSITY;
  if (selected) {
    emissive = SELECTION_EMISSIVE;
    emissiveIntensity = SELECTION_EMISSIVE_INTENSITY;
  } else if (alerting) {
    emissive = ALERT_EMISSIVE;
    emissiveIntensity = ALERT_EMISSIVE_INTENSITY;
  }

  const radius = selected
    ? definition.baseRadius * SELECTED_RADIUS_SCALE
    : definition.baseRadius;

  return {
    definition,
    color,
    emissive,
    emissiveIntensity,
    radius,
    ringColor: input.showCongestionRing ? congestionColor(input.congestionSeverity) : null,
    outlineColor: alerting ? ALERT_OUTLINE_COLOR : null,
    tier: definition.tier,
  };
}

// --------------------------------------------------------------------------------------
// Label budgeting
// --------------------------------------------------------------------------------------

/**
 * Default cap on simultaneously rendered DOM labels.
 *
 * Each label is a `<Html>` overlay, i.e. a real DOM node. The previous implementation
 * rendered one per device, which meant ~339 DOM nodes for the Strathmore dataset and a
 * measurable interaction cost. Labels are now budgeted by importance.
 */
export const DEFAULT_MAX_DEVICE_LABELS = 24;

export interface LabelCandidate {
  id: string;
  hostname: string;
  deviceType: string | null | undefined;
}

export interface SelectLabelsOptions {
  maxLabels?: number;
  selectedNodeId?: string | null;
  alertingDeviceIds?: ReadonlySet<string>;
}

/**
 * Choose which devices get a DOM label.
 *
 * Ordering is deterministic:
 * 1. the selected device, always, regardless of budget;
 * 2. devices with an active alert;
 * 3. highest tier priority (core before leaf);
 * 4. hostname, then id, for stable tie-breaking.
 */
export function selectDeviceLabels(
  candidates: readonly LabelCandidate[],
  options: SelectLabelsOptions = {},
): Set<string> {
  const maxLabels = Math.max(0, options.maxLabels ?? DEFAULT_MAX_DEVICE_LABELS);
  const alerting = options.alertingDeviceIds ?? new Set<string>();
  const selectedNodeId = options.selectedNodeId ?? null;

  const selected = new Set<string>();

  const hasSelected = Boolean(
    selectedNodeId && candidates.some((candidate) => candidate.id === selectedNodeId),
  );

  // The selected device is always labelled, even when the budget is zero.
  if (hasSelected && selectedNodeId) {
    selected.add(selectedNodeId);
  }

  const remainingSlots = hasSelected ? Math.max(0, maxLabels - 1) : maxLabels;
  let added = 0;

  const ranked = [...candidates]
    .filter((candidate) => candidate.id !== selectedNodeId)
    .sort((left, right) => {
      const leftAlert = alerting.has(left.id) ? 1 : 0;
      const rightAlert = alerting.has(right.id) ? 1 : 0;
      if (leftAlert !== rightAlert) {
        return rightAlert - leftAlert;
      }

      const leftPriority = getDeviceVisualDefinition(left.deviceType).labelPriority;
      const rightPriority = getDeviceVisualDefinition(right.deviceType).labelPriority;
      if (leftPriority !== rightPriority) {
        return rightPriority - leftPriority;
      }

      const hostnameDelta = (left.hostname || "").localeCompare(right.hostname || "");
      if (hostnameDelta !== 0) {
        return hostnameDelta;
      }
      return left.id.localeCompare(right.id);
    });

  for (const candidate of ranked) {
    if (added >= remainingSlots) {
      break;
    }
    selected.add(candidate.id);
    added += 1;
  }

  return selected;
}

// --------------------------------------------------------------------------------------
// Alert association
// --------------------------------------------------------------------------------------

interface AlertLike {
  event_type: string;
  payload: Record<string, unknown>;
}

/**
 * Extract the set of device ids that currently have an active alert.
 *
 * IMPORTANT / known limitation: NANFO alerts are presently infrastructure and SLO
 * alerts (for example telemetry collector sustained failure) and their payloads do NOT
 * carry a `device_id`. This function therefore returns an empty set against today's
 * backend, and per-device alert rings will not appear.
 *
 * That is deliberate. Fabricating device alerts from unrelated signals (congestion,
 * status) would misrepresent operational state. The extraction is defensive so that if
 * and when alert payloads gain a device reference, the visual lights up with no
 * renderer change required.
 */
export function deriveAlertingDeviceIds(
  alerts: readonly AlertLike[],
  knownDeviceIds?: ReadonlySet<string>,
): Set<string> {
  const latestStateByDeviceId = new Map<string, boolean>();

  for (const alert of alerts) {
    const eventType = (alert.event_type ?? "").trim().toLowerCase();

    const payload = alert.payload ?? {};
    const candidate =
      payload.device_id ?? payload.deviceId ?? payload.target_device_id ?? null;
    if (typeof candidate !== "string") {
      continue;
    }

    const deviceId = candidate.trim();
    if (!deviceId) {
      continue;
    }
    if (knownDeviceIds && !knownDeviceIds.has(deviceId)) {
      continue;
    }

    // `alerts` is newest-first in the live store; first match wins.
    if (latestStateByDeviceId.has(deviceId)) {
      continue;
    }

    const isActive = !(eventType === "alert.resolved" || eventType === "alert.acknowledged");
    latestStateByDeviceId.set(deviceId, isActive);
  }

  const alerting = new Set<string>();
  for (const [deviceId, isActive] of latestStateByDeviceId.entries()) {
    if (isActive) {
      alerting.add(deviceId);
    }
  }

  return alerting;
}

// --------------------------------------------------------------------------------------
// Legend
// --------------------------------------------------------------------------------------

export interface DeviceLegendEntry {
  typeKey: string;
  label: string;
  tier: DeviceTier;
  color: string;
  geometry: DeviceGeometryKind;
}

export const TIER_DISPLAY_ORDER: readonly DeviceTier[] = [
  "perimeter",
  "core",
  "distribution",
  "access",
  "leaf",
] as const;

export const TIER_LABELS: Record<DeviceTier, string> = {
  perimeter: "Perimeter",
  core: "Core",
  distribution: "Distribution",
  access: "Access",
  leaf: "Edge / Endpoint",
};

/**
 * Legend rows for the UI, de-duplicated by label so aliases such as
 * `router`/`core_router` appear once, ordered by tier.
 */
export function buildDeviceLegend(): DeviceLegendEntry[] {
  const seenLabels = new Set<string>();
  const entries: DeviceLegendEntry[] = [];

  for (const tier of TIER_DISPLAY_ORDER) {
    for (const item of DEVICE_VISUAL_DEFINITIONS) {
      if (item.tier !== tier || seenLabels.has(item.label)) {
        continue;
      }
      seenLabels.add(item.label);
      entries.push({
        typeKey: item.typeKey,
        label: item.label,
        tier: item.tier,
        color: item.typeColor,
        geometry: item.geometry,
      });
    }
  }

  return entries;
}
