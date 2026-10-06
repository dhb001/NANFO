import { describe, expect, it, vi } from "vitest";
import { ApiClientError } from "@/shared/lib/errors";
import { resolveViewportStatus } from "./twinViewportStatus";
import { WEBGL_UNAVAILABLE_REASON, describeCanvasFailure, detectWebGLSupport } from "./webglSupport";

const base = { networkSelected: true, isLoading: false, isError: false, error: null, hasData: true, hasContent: true };

describe("resolveViewportStatus", () => {
  it("orders no-network, loading, error and empty before ready", () => {
    expect(resolveViewportStatus({ ...base, networkSelected: false, isLoading: true })).toMatchObject({ kind: "no-network", title: "No network selected" });
    expect(resolveViewportStatus({ ...base, isLoading: true, isError: true })).toMatchObject({ kind: "loading", title: "Loading topology" });
    expect(resolveViewportStatus({ ...base, isError: true, hasContent: false })).toMatchObject({ kind: "error", title: "Topology request failed" });
    expect(resolveViewportStatus({ ...base, hasContent: false })).toMatchObject({ kind: "empty", title: "Topology graph is empty" });
    expect(resolveViewportStatus(base)).toEqual({ kind: "ready" });
  });

  it("explains the error with the API context and says when the last topology stays visible", () => {
    const error = new ApiClientError("Upstream unavailable", "SERVICE_UNAVAILABLE", 503, { retryAfterMs: 4000, requestId: "req-1" });
    const stale = resolveViewportStatus({ ...base, isError: true, error });
    expect(stale).toMatchObject({ kind: "error" });
    expect(stale.kind === "error" && stale.description).toBe("Upstream unavailable Retry in about 4 s. Reference: req-1. The last loaded topology stays visible.");
    const first = resolveViewportStatus({ ...base, isError: true, error: new Error("offline"), hasData: false });
    expect(first.kind === "error" && first.description).toBe("offline");
  });
});

describe("webglSupport", () => {
  it("reports no WebGL when the browser lacks the WebGL constructors, without probing a canvas", () => {
    const createElement = vi.fn();
    expect(detectWebGLSupport({ defaultView: {}, createElement } as unknown as Document)).toBe(false);
    expect(createElement).not.toHaveBeenCalled();
    expect(detectWebGLSupport(undefined)).toBe(false);
  });

  it("probes a context, releases it, and treats a null or throwing probe as unsupported", () => {
    const loseContext = vi.fn();
    const context = { getExtension: vi.fn().mockReturnValue({ loseContext }) };
    const supported = { defaultView: { WebGL2RenderingContext: class {} }, createElement: () => ({ getContext: (kind: string) => (kind === "webgl2" ? context : null) }) };
    expect(detectWebGLSupport(supported as unknown as Document)).toBe(true);
    expect(context.getExtension).toHaveBeenCalledWith("WEBGL_lose_context");
    expect(loseContext).toHaveBeenCalledTimes(1);
    const none = { defaultView: { WebGLRenderingContext: class {} }, createElement: () => ({ getContext: () => null }) };
    expect(detectWebGLSupport(none as unknown as Document)).toBe(false);
    const throwing = { defaultView: { WebGLRenderingContext: class {} }, createElement: () => ({ getContext: () => { throw new Error("blocked"); } }) };
    expect(detectWebGLSupport(throwing as unknown as Document)).toBe(false);
  });

  it("describes context, download and scene failures for operators", () => {
    expect(describeCanvasFailure(new Error("Error creating WebGL context."))).toBe(WEBGL_UNAVAILABLE_REASON);
    expect(describeCanvasFailure(new TypeError("Failed to fetch dynamically imported module: /assets/three.js"))).toMatch(/could not be downloaded/);
    expect(describeCanvasFailure(new Error("bad geometry"))).toBe("The 3D renderer stopped with an error (bad geometry).");
    expect(describeCanvasFailure(null)).toBe("The 3D renderer stopped with an error.");
  });
});
