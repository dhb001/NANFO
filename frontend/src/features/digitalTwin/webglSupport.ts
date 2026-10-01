/** WebGL capability probe and operator-facing text for 3D renderer failures (pure). */

export const WEBGL_UNAVAILABLE_REASON = "This browser or device cannot create a WebGL context (hardware acceleration may be disabled or blocked).";

type WebGLWindow = Window & { WebGLRenderingContext?: unknown; WebGL2RenderingContext?: unknown };

/**
 * Whether a WebGL context can be created. The probe context is released immediately so it
 * never counts against the browser's live-context limit used by the real renderer.
 */
export function detectWebGLSupport(doc: Document | undefined = typeof document === "undefined" ? undefined : document): boolean {
  const view = doc?.defaultView as WebGLWindow | null | undefined;
  if (!doc || !view || (typeof view.WebGL2RenderingContext === "undefined" && typeof view.WebGLRenderingContext === "undefined")) return false;
  try {
    const canvas = doc.createElement("canvas");
    const context = (canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
    if (!context) return false;
    context.getExtension("WEBGL_lose_context")?.loseContext();
    return true;
  } catch {
    return false;
  }
}

const CHUNK_FAILURE = /ChunkLoadError|Loading (?:CSS )?chunk .*failed|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i;
const CONTEXT_FAILURE = /webgl|context/i;

/** Maps an error caught by the Canvas boundary to a short operator explanation. */
export function describeCanvasFailure(error: unknown): string {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : typeof error === "string" ? error : "";
  if (CHUNK_FAILURE.test(message)) return "The 3D renderer could not be downloaded (connection problem or updated application).";
  if (CONTEXT_FAILURE.test(message)) return WEBGL_UNAVAILABLE_REASON;
  const detail = error instanceof Error && error.message.trim() ? ` (${error.message.trim().slice(0, 160)})` : "";
  return `The 3D renderer stopped with an error${detail}.`;
}
