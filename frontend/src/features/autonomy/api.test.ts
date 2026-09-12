import { afterEach, describe, expect, it, vi } from "vitest";
import { getAutonomy, stopAutonomy, updateAutonomy } from "./api";
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
});
