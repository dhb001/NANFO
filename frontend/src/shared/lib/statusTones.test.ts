import { describe, expect, it } from "vitest";
import {
  ALERT_SEVERITY_TONES, ALERT_STATUS_TONES, DEVICE_STATUS_TONES, INTENT_CONFIDENCE_BAND_TONES, INTENT_QUEUE_STATUS_TONES,
  INTENT_STATUS_TONES, PLUGIN_STATUS_TONES, REPORT_QUEUE_STATUS_TONES, REPORT_STATUS_TONES, SIMULATION_QUEUE_STATUS_TONES,
  SIMULATION_RISK_GATE_TONES, SIMULATION_STATE_TONES, TELEMETRY_HEALTH_TONES, TELEMETRY_SLO_TONES,
  alertSeverityTone, deviceStatusTone, intentStatusTone, reportStatusTone, simulationStateTone, statusLabel, toneFor,
} from "@/shared/lib/statusTones";

const TONES = new Set(["ok", "warn", "danger", "info", "neutral"]);

describe("explicit backend status tone maps (ADR-028)", () => {
  it("lists exactly the backend value sets", () => {
    // backend/app/modules/intent/models.py INTENT_STATUSES / INTENT_QUEUE_STATUSES
    expect(Object.keys(INTENT_STATUS_TONES).sort()).toEqual([
      "cancelled", "compensated", "draft", "execution_cancelled", "execution_compensated", "execution_completed",
      "execution_failed", "execution_started", "rejected", "validated",
    ]);
    expect(Object.keys(INTENT_QUEUE_STATUS_TONES).sort()).toEqual(["deferred", "outbox_pending", "pending", "queued", "validated"]);
    expect(Object.keys(INTENT_CONFIDENCE_BAND_TONES).sort()).toEqual(["60-79", "80-94", "95-100", "below_60"]);
    // backend/app/modules/simulation/models.py SIMULATION_STATES (incl. failed)
    expect(Object.keys(SIMULATION_STATE_TONES).sort()).toEqual(["cancelled", "completed", "draft", "failed", "paused", "queued", "running"]);
    expect(Object.keys(SIMULATION_QUEUE_STATUS_TONES).sort()).toEqual(["deferred", "draft", "outbox_pending", "pending", "queued"]);
    expect(Object.keys(SIMULATION_RISK_GATE_TONES).sort()).toEqual(["blocked", "passed", "required"]);
    // report/models.py ck_reports_status; report queue writers
    expect(Object.keys(REPORT_STATUS_TONES).sort()).toEqual(["failed", "generated", "requested", "running"]);
    expect(Object.keys(REPORT_QUEUE_STATUS_TONES).sort()).toEqual(["outbox_pending", "pending", "queued"]);
    // alert/models.py ck_alerts_status
    expect(Object.keys(ALERT_STATUS_TONES).sort()).toEqual(["acknowledged", "active", "resolved"]);
    expect(Object.keys(ALERT_SEVERITY_TONES).sort()).toEqual(["critical", "degraded", "high", "info", "low", "medium", "ok", "warning"]);
    expect(Object.keys(TELEMETRY_HEALTH_TONES).sort()).toEqual(["degraded", "ok", "unavailable"]);
    expect(Object.keys(TELEMETRY_SLO_TONES).sort()).toEqual(["critical", "degraded", "ok", "unavailable"]);
    expect(Object.keys(DEVICE_STATUS_TONES).sort()).toEqual(["active", "deleted"]);
    expect(Object.keys(PLUGIN_STATUS_TONES).sort()).toEqual(["disabled", "enabled", "failed", "installed", "uninstalled"]);
    for (const map of [INTENT_STATUS_TONES, SIMULATION_STATE_TONES, REPORT_STATUS_TONES, ALERT_SEVERITY_TONES, PLUGIN_STATUS_TONES]) {
      expect(Object.isFrozen(map)).toBe(true);
      for (const tone of Object.values(map)) expect(TONES.has(tone)).toBe(true);
    }
  });

  it("maps known values exactly and never infers meaning from substrings, case or aliases", () => {
    expect(intentStatusTone("execution_failed")).toBe("danger");
    expect(intentStatusTone("execution_completed")).toBe("ok");
    expect(intentStatusTone("execution_started")).toBe("info");
    // Invented aliases and look-alikes are unknown, therefore neutral.
    for (const value of ["failed", "completed", "EXECUTION_FAILED", " execution_failed", "execution_failed_permanently", "not_failed"]) {
      expect(intentStatusTone(value)).toBe("neutral");
    }
    expect(simulationStateTone("failed")).toBe("danger");
    expect(simulationStateTone("draft")).toBe("neutral");
    expect(reportStatusTone("generated")).toBe("ok");
    expect(alertSeverityTone("critical")).toBe("danger");
    expect(alertSeverityTone("warning")).toBe("warn");
    expect(alertSeverityTone("catastrophic")).toBe("neutral");
    expect(deviceStatusTone("active")).toBe("ok");
    expect(deviceStatusTone("offline")).toBe("neutral");
  });

  it("treats absent and non-string values as neutral, including prototype keys", () => {
    for (const value of [undefined, null, 1, {}, [], "", "constructor", "toString", "__proto__"]) {
      expect(toneFor(INTENT_STATUS_TONES, value)).toBe("neutral");
    }
  });

  it("labels the raw backend value or an explicit placeholder", () => {
    expect(statusLabel("execution_failed")).toBe("execution_failed");
    expect(statusLabel(undefined)).toBe("unknown");
    expect(statusLabel("  ", "severity unavailable")).toBe("severity unavailable");
    expect(statusLabel(42)).toBe("unknown");
  });
});
