import { afterEach, describe, expect, it, vi } from "vitest";
import { getAutonomy, STOP_BUSY_ATTEMPTS, stopAutonomy, updateAutonomy, validConfidence } from "./api";
import { autonomyFixture, certificateFixture, decisionFixture } from "./fixtures";

describe("ADR-012 API boundary", () => {
  afterEach(() => vi.unstubAllGlobals());
  const data = autonomyFixture();
  const envelope = (value: unknown) => ({ success: true, data: value, meta: {}, errors: null });
  it("uses exactly the approved scoped GET, PUT and stop fields and passes cancellation signals", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(Response.json(envelope(data))));
    vi.stubGlobal("fetch", fetch);
    const signal = new AbortController().signal;
    await getAutonomy("token", data.network_id, data.workspace_id, signal);
    const request = { network_id: data.network_id, expected_revision: data.revision, mode: "recommend" as const, checkpoint_sha256: null, approval_expires_at: null };
    await updateAutonomy("token", data.workspace_id, request);
    await stopAutonomy("token", data.network_id, data.workspace_id);
    expect(fetch.mock.calls[0][0]).toMatch(new RegExp(`/api/v1/autonomy\\?network_id=${data.network_id}$`));
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: "GET", signal });
    expect(fetch.mock.calls[1][0]).toMatch(/\/api\/v1\/autonomy$/);
    expect(fetch.mock.calls[1][1]).toMatchObject({ method: "PUT", body: JSON.stringify(request), headers: { Authorization: "Bearer token" } });
    expect(fetch.mock.calls[2][0]).toMatch(/\/api\/v1\/autonomy\/stop$/);
    expect(fetch.mock.calls[2][1]).toMatchObject({ method: "POST", body: JSON.stringify({ network_id: data.network_id }) });
  });
  it.each([null, {}, { ...data, network_id: "other" }, { ...data, workspace_id: "other" },
    { ...data, ready: undefined }, { ...data, online_learning: true }, { ...data, providers: {} },
    { ...data, decisions: [null] }, { ...data, cancellation_status: "success" },
    { ...data, revision: undefined }, { ...data, revision: -1 }, { ...data, revision: 0.5 }, { ...data, revision: Number.MAX_SAFE_INTEGER + 1 },
    { ...data, last_decision: decisionFixture({ network_id: "other" }) },
    { ...data, decisions: [decisionFixture({ verification: { execution_id: "wrong-execution", status: "cancelled", safe_to_release: true, evidence: [], reasons: [] } })] },
    { ...data, decisions: [{ ...decisionFixture(), safety: { admissible: "false", model_version: "test" } }] },
    { ...data, last_observation: { network_id: data.network_id, workspace_id: data.workspace_id, reasons: "invalid" } },
  ])("rejects empty, incompatible and cross-scope status %#", async (value) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(envelope(value))));
    await expect(getAutonomy("token", data.network_id, data.workspace_id)).rejects.toThrow();
  });
  it("rejects a cross-scope stop acknowledgement and accepts bounded durable history", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(Response.json(envelope(autonomyFixture({ emergency_stopped: true, network_id: "other" }))))
      .mockResolvedValueOnce(Response.json(envelope(autonomyFixture({ decisions: [decisionFixture()] })))));
    await expect(stopAutonomy("token", data.network_id, data.workspace_id)).rejects.toMatchObject({ code: "AUTONOMY_SCOPE_MISMATCH" });
    expect((await getAutonomy("token", data.network_id, data.workspace_id)).decisions).toEqual([decisionFixture()]);
  });
  it("preserves a rejected autonomous request rather than fabricating a new mode", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ success: false, data: null, meta: {}, errors: {
      code: "AUTONOMY_NOT_READY", message: "calibrated_safety_unavailable, autonomous_executor_unavailable",
    } }, { status: 409 })));
    await expect(updateAutonomy("token", data.workspace_id, { network_id: data.network_id, expected_revision: data.revision, mode: "autonomous", checkpoint_sha256: "a".repeat(64), approval_expires_at: "2026-09-09T13:00:00Z" }))
      .rejects.toMatchObject({ status: 409, code: "AUTONOMY_NOT_READY" });
  });
  it.each([-1, 0.5, NaN])("does not send a PUT with invalid expected_revision %s", async (revision) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(updateAutonomy("token", data.workspace_id, { network_id: data.network_id, expected_revision: revision, mode: "monitor", checkpoint_sha256: null, approval_expires_at: null })).rejects.toThrow(/revision/);
    expect(fetch).not.toHaveBeenCalled();
  });
  it.each(["valid", "wrong-network", "bad-hash", "bad-expiry", "bad-drift", "unconditional"])("validates structured certificate %s", async (kind) => {
    const certificate = { ...certificateFixture(), ...(kind === "wrong-network" ? { network_id: "other" } : {}),
      ...(kind === "bad-hash" ? { input_sha256: "not-a-hash" } : {}),
      ...(kind === "bad-expiry" ? { expires_at_unix_seconds: 1e20 } : {}),
      ...(kind === "bad-drift" ? { drift: null } : {}), ...(kind === "unconditional" ? { conditional: false } : {}) };
    const status = autonomyFixture({ decisions: [decisionFixture()] });
    const decision = { ...decisionFixture(), safety: { admissible: true, action_id: "route-1", model_version: "test-only", reasons: [], evidence: [], certificate } };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(envelope({ ...status, decisions: [decision] }))));
    const result = getAutonomy("token", data.network_id, data.workspace_id);
    if (kind === "valid") expect((await result).decisions[0].safety?.certificate).toEqual(certificate);
    else await expect(result).rejects.toMatchObject({ code: "AUTONOMY_INVALID_STATUS" });
  });

  describe("ADR-028 C17/C25", () => {
    const request = { network_id: data.network_id, expected_revision: data.revision, mode: "autonomous" as const, checkpoint_sha256: "a".repeat(64), approval_expires_at: "2026-09-09T13:00:00Z" };

    it("reports a 202 PUT as a pending two-person approval, not an applied mode", async () => {
      const pending = { requested_by_user_id: "user-a", mode: "autonomous", expected_revision: data.revision, checkpoint_sha256: "a".repeat(64),
        approval_expires_at: "2026-09-09T13:00:00Z", requested_at: "2026-09-09T12:00:00Z", expires_at: "2026-09-09T13:00:00Z" };
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ success: true, data: { ...data, pending_approval: pending },
        meta: { pending_approval: true, pending_approval_expires_at: "2026-09-09T13:00:00Z", pending_requested_by_user_id: "user-a" }, errors: null }, { status: 202 })));
      const result = await updateAutonomy("token", data.workspace_id, request);
      expect(result).toMatchObject({ pendingApproval: true, pendingApprovalExpiresAt: "2026-09-09T13:00:00Z" });
      expect(result.status.mode).toBe("monitor");
      expect(result.status.pending_approval).toEqual(pending);
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(envelope(data))));
      expect(await updateAutonomy("token", data.workspace_id, { ...request, mode: "monitor", checkpoint_sha256: null, approval_expires_at: null }))
        .toMatchObject({ pendingApproval: false, pendingApprovalExpiresAt: null });
    });

    it("rejects a malformed pending approval", async () => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(envelope({ ...data, pending_approval: { mode: "autonomous" } }))));
      await expect(getAutonomy("token", data.network_id, data.workspace_id)).rejects.toMatchObject({ code: "AUTONOMY_INVALID_STATUS" });
    });

    it("accepts only honest confidence: calibrated exactly when a calibration is named", async () => {
      expect(validConfidence(null)).toBe(true);
      expect(validConfidence({ value: 0.97, method: "isotonic", calibrated: true, calibration_id: "cal-1" })).toBe(true);
      expect(validConfidence({ value: 0.62, method: "policy_action_probability", calibrated: false, calibration_id: null })).toBe(true);
      expect(validConfidence({ value: 0.62, method: "policy_action_probability", calibrated: false })).toBe(true);
      expect(validConfidence({ value: 0.97, method: "isotonic", calibrated: true, calibration_id: null })).toBe(false);
      expect(validConfidence({ value: 0.62, method: "raw", calibrated: false, calibration_id: "cal-1" })).toBe(false);
      expect(validConfidence({ value: 1.2, method: "raw", calibrated: false })).toBe(false);
      const dishonest = decisionFixture({ confidence: { value: 0.99, method: "raw", calibrated: true } });
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(envelope({ ...data, decisions: [dishonest] }))));
      await expect(getAutonomy("token", data.network_id, data.workspace_id)).rejects.toMatchObject({ code: "AUTONOMY_INVALID_STATUS" });
    });

    it("retries a busy emergency-stop latch honouring Retry-After, then surfaces AUTONOMY_STOP_BUSY", async () => {
      const busy = () => Response.json({ success: false, data: null, meta: {}, errors: { code: "AUTONOMY_STOP_BUSY", message: "retry now" } },
        { status: 503, headers: { "Retry-After": "1" } });
      const waits: number[] = [];
      const wait = async (ms: number) => { waits.push(ms); };
      const fetch = vi.fn().mockResolvedValueOnce(busy()).mockResolvedValueOnce(Response.json(envelope(autonomyFixture({ emergency_stopped: true }))));
      vi.stubGlobal("fetch", fetch);
      expect((await stopAutonomy("token", data.network_id, data.workspace_id, wait)).emergency_stopped).toBe(true);
      expect(waits).toEqual([1000]);
      const always = vi.fn().mockImplementation(() => Promise.resolve(busy()));
      vi.stubGlobal("fetch", always);
      await expect(stopAutonomy("token", data.network_id, data.workspace_id, wait)).rejects.toMatchObject({ status: 503, code: "AUTONOMY_STOP_BUSY" });
      expect(always).toHaveBeenCalledTimes(STOP_BUSY_ATTEMPTS);
    });

    it("never retries other stop failures", async () => {
      const fetch = vi.fn().mockResolvedValue(Response.json({ success: false, data: null, meta: {}, errors: { code: "DEPENDENCY_UNAVAILABLE", message: "down" } }, { status: 503 }));
      vi.stubGlobal("fetch", fetch);
      await expect(stopAutonomy("token", data.network_id, data.workspace_id, async () => undefined)).rejects.toMatchObject({ code: "DEPENDENCY_UNAVAILABLE" });
      expect(fetch).toHaveBeenCalledTimes(1);
    });
  });
});
