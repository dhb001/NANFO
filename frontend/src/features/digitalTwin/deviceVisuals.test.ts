import { describe, expect, it } from "vitest";
import {
  ALERT_EMISSIVE,
  ALERT_OUTLINE_COLOR,
  BASE_EMISSIVE_INTENSITY,
  DEVICE_VISUAL_DEFINITIONS,
  SELECTION_EMISSIVE,
  SELECTION_EMISSIVE_INTENSITY,
  SELECTED_RADIUS_SCALE,
  TIER_DISPLAY_ORDER,
  buildDeviceLegend,
  congestionColor,
  deriveAlertingDeviceIds,
  getDeviceTier,
  getDeviceVisualDefinition,
  normalizeDeviceType,
  resolveDeviceVisual,
  selectDeviceLabels,
  statusColor,
} from "@/features/digitalTwin/deviceVisuals";

describe("device visuals", () => {
  it("resolves all required canonical device types", () => {
    const requiredTypes = [
      "router",
      "firewall",
      "distribution_switch",
      "access_switch",
      "wireless_ap",
      "server",
      "security_gateway",
      "ups",
      "lab_endpoint",
    ];

    for (const typeKey of requiredTypes) {
      const definition = getDeviceVisualDefinition(typeKey);
      expect(definition.typeKey).toBe(typeKey);
      expect(definition.label.length).toBeGreaterThan(0);
      expect(definition.baseRadius).toBeGreaterThan(0);
    }
  });

  it("normalizes type aliases and falls back deterministically", () => {
    expect(normalizeDeviceType("Core-Router")).toBe("core_router");
    expect(getDeviceVisualDefinition(" core router ").label).toBe("Core router");
    expect(getDeviceTier("unknown-thing")).toBe("leaf");
  });

  it("keeps type colour as base while using status for glow", () => {
    const definition = getDeviceVisualDefinition("firewall");
    const resolved = resolveDeviceVisual({
      deviceType: "firewall",
      status: "offline",
      congestionSeverity: "medium",
    });

    expect(resolved.color).toBe(definition.typeColor);
    expect(resolved.emissive).toBe(statusColor("offline"));
    expect(resolved.emissiveIntensity).toBe(BASE_EMISSIVE_INTENSITY);
    expect(resolved.outlineColor).toBeNull();
    expect(resolved.ringColor).toBeNull();
  });

  it("applies selection and alert state overlays without hiding type identity", () => {
    const definition = getDeviceVisualDefinition("server");

    const alerting = resolveDeviceVisual({
      deviceType: "server",
      status: "active",
      congestionSeverity: "low",
      alerting: true,
      showCongestionRing: true,
    });

    expect(alerting.color).toBe(definition.typeColor);
    expect(alerting.emissive).toBe(ALERT_EMISSIVE);
    expect(alerting.outlineColor).toBe(ALERT_OUTLINE_COLOR);
    expect(alerting.ringColor).toBe(congestionColor("low"));

    const selected = resolveDeviceVisual({
      deviceType: "server",
      status: "active",
      congestionSeverity: "low",
      selected: true,
      alerting: true,
      showCongestionRing: true,
    });

    expect(selected.emissive).toBe(SELECTION_EMISSIVE);
    expect(selected.emissiveIntensity).toBe(SELECTION_EMISSIVE_INTENSITY);
    expect(selected.radius).toBeCloseTo(definition.baseRadius * SELECTED_RADIUS_SCALE, 6);
    expect(selected.outlineColor).toBe(ALERT_OUTLINE_COLOR);
  });

  it("supports congestion-as-colour mode and deterministic ring rendering", () => {
    const resolved = resolveDeviceVisual({
      deviceType: "access_switch",
      status: "active",
      congestionSeverity: "high",
      colorMode: "congestion",
      showCongestionRing: true,
    });

    expect(resolved.color).toBe(congestionColor("high"));
    expect(resolved.ringColor).toBe(congestionColor("high"));
  });

  it("budgets labels deterministically and always keeps selected node", () => {
    const labels = selectDeviceLabels(
      [
        { id: "core-a", hostname: "core-a", deviceType: "router" },
        { id: "access-a", hostname: "access-a", deviceType: "access_switch" },
        { id: "leaf-a", hostname: "leaf-a", deviceType: "lab_endpoint" },
        { id: "leaf-alert", hostname: "leaf-z", deviceType: "lab_endpoint" },
      ],
      {
        maxLabels: 3,
        selectedNodeId: "leaf-a",
        alertingDeviceIds: new Set(["leaf-alert"]),
      },
    );

    expect(labels.size).toBe(3);
    expect(labels.has("leaf-a")).toBe(true);
    expect(labels.has("leaf-alert")).toBe(true);
    expect(labels.has("core-a")).toBe(true);

    const zeroBudget = selectDeviceLabels(
      [{ id: "leaf-a", hostname: "leaf-a", deviceType: "lab_endpoint" }],
      { maxLabels: 0, selectedNodeId: "leaf-a" },
    );
    expect(zeroBudget.size).toBe(1);
    expect(zeroBudget.has("leaf-a")).toBe(true);
  });

  it("derives active alerting devices from newest event state only", () => {
    const alerting = deriveAlertingDeviceIds([
      { event_type: "alert.resolved", payload: { device_id: "device-1" } },
      { event_type: "alert.generated", payload: { device_id: "device-1" } },
      { event_type: "alert.generated", payload: { deviceId: "device-2" } },
      { event_type: "alert.generated", payload: { target_device_id: "device-3" } },
      { event_type: "alert.generated", payload: {} },
    ]);

    expect(alerting.has("device-1")).toBe(false);
    expect(alerting.has("device-2")).toBe(true);
    expect(alerting.has("device-3")).toBe(true);

    const filtered = deriveAlertingDeviceIds(
      [{ event_type: "alert.generated", payload: { device_id: "device-4" } }],
      new Set(["device-2"]),
    );
    expect(filtered.size).toBe(0);
  });

  it("builds a de-duplicated legend ordered by tier", () => {
    const legend = buildDeviceLegend();
    const labels = legend.map((entry) => entry.label);
    const uniqueLabels = new Set(labels);

    expect(uniqueLabels.size).toBe(legend.length);
    expect(labels.filter((label) => label === "Core router")).toHaveLength(1);

    const tierIndex = (tier: string) => TIER_DISPLAY_ORDER.indexOf(tier as (typeof TIER_DISPLAY_ORDER)[number]);
    for (let index = 1; index < legend.length; index += 1) {
      expect(tierIndex(legend[index - 1].tier)).toBeLessThanOrEqual(tierIndex(legend[index].tier));
    }
  });

  it("keeps the catalogue aligned with exported definitions", () => {
    const uniqueTypeKeys = new Set(DEVICE_VISUAL_DEFINITIONS.map((entry) => entry.typeKey));
    expect(uniqueTypeKeys.size).toBe(DEVICE_VISUAL_DEFINITIONS.length);
  });
});
