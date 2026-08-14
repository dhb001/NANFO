import { describe, expect, it } from "vitest";
import {
  alertSeverityWeight,
  isAcknowledgedAlert,
  isResolvedAlert,
  normalizeAlertStatus,
  summarizeAlertSource,
} from "@/shared/lib/alerts";
import { LiveAlertItem } from "@/features/realtime/store";

function createAlert(overrides: Partial<LiveAlertItem> = {}): LiveAlertItem {
  return {
    event_id: "event-1",
    event_type: "alert.generated",
    source: "telemetry",
    payload: { severity: "medium" },
    ...overrides,
  };
}

describe("alerts helpers", () => {
  it("computes severity weights", () => {
    expect(alertSeverityWeight(createAlert({ payload: { severity: "critical" } }))).toBe(5);
    expect(alertSeverityWeight(createAlert({ payload: { severity: "medium" } }))).toBe(2);
    expect(alertSeverityWeight(createAlert({ payload: { severity: "unknown" } }))).toBe(0);
  });

  it("builds source summary counts", () => {
    const summary = summarizeAlertSource([
      createAlert({ source: "telemetry" }),
      createAlert({ source: "telemetry", event_id: "event-2" }),
      createAlert({ source: "intent", event_id: "event-3" }),
    ]);

    expect(summary).toEqual({ telemetry: 2, intent: 1 });
  });

  it("normalizes and resolves status semantics", () => {
    expect(normalizeAlertStatus("ack")).toBe("acknowledged");
    expect(normalizeAlertStatus("resolved")).toBe("resolved");
    expect(isAcknowledgedAlert(createAlert({ event_type: "alert.acknowledged" }))).toBe(true);
    expect(isAcknowledgedAlert(createAlert({ event_type: "alert.generated" }))).toBe(false);
    expect(isResolvedAlert(createAlert({ event_type: "alert.resolved" }))).toBe(true);
    expect(isResolvedAlert(createAlert({ event_type: "alert.generated" }))).toBe(false);
  });
});
