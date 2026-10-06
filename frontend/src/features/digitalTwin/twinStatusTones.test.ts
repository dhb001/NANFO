import { describe, expect, it } from "vitest";
import {
  INTENT_STATUS_TONES,
  SIMULATION_STATE_TONES,
  TONE_COLORS,
  OVERLAY_BASE_COLORS,
  deviceStatusTone,
  overlayColor,
  overlayLifecycleValue,
  overlayTone,
} from "./twinStatusTones";

const sim = (state: string | null, status: string | null = null) => ({ objectType: "simulation_state", state, status });
const intent = (status: string | null) => ({ objectType: "intent_state", state: null, status });

describe("explicit backend-state tone maps", () => {
  it("maps every documented simulation state and intent status exactly", () => {
    expect(Object.keys(SIMULATION_STATE_TONES).sort()).toEqual(["cancelled", "completed", "draft", "failed", "paused", "pending", "queued", "running"]);
    expect(overlayTone(sim("failed"))).toBe("danger");
    expect(overlayTone(sim("cancelled"))).toBe("danger");
    expect(overlayTone(sim("completed"))).toBe("ok");
    expect(overlayTone(sim("queued"))).toBe("warn");
    expect(overlayTone(sim("paused"))).toBe("warn");
    expect(overlayTone(sim("running"))).toBe("info");
    expect(overlayTone(intent("validated"))).toBe("ok");
    expect(overlayTone(intent("execution_completed"))).toBe("ok");
    expect(overlayTone(intent("execution_failed"))).toBe("danger");
    expect(overlayTone(intent("rejected"))).toBe("danger");
    expect(overlayTone(intent("execution_started"))).toBe("info");
    expect(INTENT_STATUS_TONES.execution_cancelled).toBe("danger");
  });

  it("never infers meaning from substrings or case variants of unknown values", () => {
    for (const value of ["partially_failed", "Failed", "not_completed", "revalidated", "queued_later", "", "__proto__", "toString"]) {
      expect(overlayTone(sim(value))).toBe("neutral");
      expect(overlayTone(intent(value))).toBe("neutral");
    }
    expect(overlayTone({ objectType: "future_state", state: "failed", status: "failed" })).toBe("neutral");
    expect(overlayTone(intent(null))).toBe("neutral");
  });

  it("uses simulation state before status and intent status before state", () => {
    expect(overlayLifecycleValue(sim("running", "pending"))).toBe("running");
    expect(overlayLifecycleValue(sim(null, "queued"))).toBe("queued");
    expect(overlayLifecycleValue({ objectType: "intent_state", state: "ignored", status: "validated" })).toBe("validated");
  });

  it("colours scene overlays from the tone and keeps neutral objects distinguishable by type", () => {
    expect(overlayColor(sim("failed"))).toBe(TONE_COLORS.danger);
    expect(overlayColor(intent("validated"))).toBe(TONE_COLORS.ok);
    expect(overlayColor(sim("queued"))).toBe(TONE_COLORS.warn);
    expect(overlayColor(intent("execution_started"))).toBe(OVERLAY_BASE_COLORS.intent_state);
    expect(overlayColor(sim("running"))).toBe(OVERLAY_BASE_COLORS.simulation_state);
    expect(overlayColor(intent("unknown-state"))).toBe(OVERLAY_BASE_COLORS.intent_state);
  });

  it("maps device inventory statuses explicitly", () => {
    expect(deviceStatusTone("active")).toBe("ok");
    expect(deviceStatusTone("offline")).toBe("warn");
    expect(deviceStatusTone("deleted")).toBe("danger");
    expect(deviceStatusTone("inactive")).toBe("neutral");
    expect(deviceStatusTone(undefined)).toBe("neutral");
  });
});
