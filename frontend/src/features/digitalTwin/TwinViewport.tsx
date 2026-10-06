import { Suspense, useCallback, useEffect, useId, useState } from "react";
import { Button } from "@/shared/ui/Button";
import { CanvasErrorBoundary } from "./CanvasErrorBoundary";
import { TwinPlanFallback } from "./TwinPlanFallback";
import { TwinScene, type TwinSceneProps } from "./TwinScene";
import type { ViewportStatus } from "./twinViewportStatus";
import { WEBGL_UNAVAILABLE_REASON, describeCanvasFailure, detectWebGLSupport } from "./webglSupport";

const EMPTY_ALERTING: ReadonlySet<string> = new Set<string>();

function StatusOverlay({ status, onRetry }: { status: Exclude<ViewportStatus, { kind: "ready" }>; onRetry: () => void }) {
  const error = status.kind === "error";
  return (
    <div className="twin-viewport-overlay">
      <div className={`twin-viewport-status${error ? " twin-viewport-status--error" : ""}`} role={error ? "alert" : "status"}>
        <p className="twin-viewport-title">{status.title}</p>
        <p className="twin-muted">{status.description}</p>
        {error ? <Button type="button" onClick={onRetry}>Retry loading topology</Button> : null}
      </div>
    </div>
  );
}

/**
 * The Twin view. The Canvas is rendered outside any query state, so refetches, errors and
 * empty results are overlays and never remount the WebGL context. Renderer failures (no
 * WebGL, context creation, scene errors) are contained by a Canvas error boundary and
 * replaced by the 2D plan.
 */
export function TwinViewport({ status, onRetry, scene }: { status: ViewportStatus; onRetry: () => void; scene: TwinSceneProps }) {
  const hintId = useId();
  const [failure, setFailure] = useState<string | null>(() => (detectWebGLSupport() ? null : WEBGL_UNAVAILABLE_REASON));
  const [attempt, setAttempt] = useState(0);
  const { importedModelUrl, onImportedModelStatusChange } = scene;

  useEffect(() => {
    if (failure && importedModelUrl) onImportedModelStatusChange?.("error", `The campus model cannot be shown without the 3D view. ${failure}`);
  }, [failure, importedModelUrl, onImportedModelStatusChange]);

  const retry3d = useCallback(() => {
    setFailure(detectWebGLSupport() ? null : WEBGL_UNAVAILABLE_REASON);
    setAttempt((value) => value + 1);
  }, []);
  const onCanvasError = useCallback((error: unknown) => setFailure(describeCanvasFailure(error)), []);

  return (
    <div className="twin-viewport" role="group" aria-label="Digital twin view" aria-describedby={hintId} aria-busy={status.kind === "loading"}>
      <p id={hintId} className="twin-visually-hidden">Pointer selection in the view is optional: every device can be selected with the Inspect node control.</p>
      {failure ? (
        <TwinPlanFallback reason={failure} nodes={scene.nodes} links={scene.links} alertingDeviceIds={scene.alertingDeviceIds ?? EMPTY_ALERTING}
          selectedNodeId={scene.selectedNodeId} onSelectNode={scene.onSelectNode} onRetry={retry3d} />
      ) : (
        <CanvasErrorBoundary key={attempt} onError={onCanvasError}>
          <Suspense fallback={<p role="status" className="twin-muted">Loading 3D scene…</p>}>
            <TwinScene {...scene} />
          </Suspense>
        </CanvasErrorBoundary>
      )}
      {status.kind === "ready" ? null : <StatusOverlay status={status} onRetry={onRetry} />}
    </div>
  );
}
