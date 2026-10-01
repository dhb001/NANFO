import { useEffect, useId, useMemo, useRef, useState, type MouseEvent, type RefObject } from "react";
import { Button } from "@/shared/ui/Button";
import type { TwinLink, TwinNode } from "./sceneAdapter";
import { drawPlan, layoutPlan, pickPlanPoint } from "./twinPlan2d";

const DEFAULT_SIZE = { width: 800, height: 560 };
const MAX_ALERT_BUTTONS = 20;

function useCanvasSize(canvas: RefObject<HTMLCanvasElement>) {
  const [size, setSize] = useState(DEFAULT_SIZE);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const measure = () => {
      const width = Math.round(element.clientWidth) || DEFAULT_SIZE.width;
      const height = Math.round(element.clientHeight) || DEFAULT_SIZE.height;
      setSize((current) => (current.width === width && current.height === height ? current : { width, height }));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [canvas]);
  return size;
}

/**
 * 2D top-down plan shown when WebGL is unavailable or the 3D renderer failed. Devices are
 * drawn with Canvas 2D (no WebGL); active backend alerts use a distinct shape and are also
 * listed as buttons, and every device stays selectable from the Inspect node control.
 */
export function TwinPlanFallback({ reason, nodes, links, alertingDeviceIds, selectedNodeId, onSelectNode, onRetry }: {
  reason: string;
  nodes: readonly TwinNode[];
  links: readonly TwinLink[];
  alertingDeviceIds: ReadonlySet<string>;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  onRetry: () => void;
}) {
  const legendId = useId();
  const canvas = useRef<HTMLCanvasElement>(null);
  const size = useCanvasSize(canvas);
  const layout = useMemo(() => layoutPlan(nodes, links, { ...size, alertingIds: alertingDeviceIds, selectedId: selectedNodeId }), [nodes, links, size, alertingDeviceIds, selectedNodeId]);
  const alerting = useMemo(() => nodes.filter((node) => alertingDeviceIds.has(node.id)), [nodes, alertingDeviceIds]);

  useEffect(() => {
    const element = canvas.current;
    // No 2D context in non-browser environments (tests); the DOM alternatives still work.
    if (!element || typeof CanvasRenderingContext2D === "undefined") return;
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    element.width = Math.round(layout.width * ratio);
    element.height = Math.round(layout.height * ratio);
    const context = element.getContext("2d");
    if (context) drawPlan(context, layout, ratio);
  }, [layout]);

  function pick(event: MouseEvent<HTMLCanvasElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const scaleX = rect.width > 0 ? layout.width / rect.width : 1;
    const scaleY = rect.height > 0 ? layout.height / rect.height : 1;
    const id = pickPlanPoint(layout, (event.clientX - rect.left) * scaleX, (event.clientY - rect.top) * scaleY);
    if (id) onSelectNode(id);
  }

  return (
    <section className="twin-plan" aria-label="2D plan view">
      <div role="alert" className="twin-viewport-status twin-viewport-status--error">
        <p className="twin-viewport-title">3D view unavailable</p>
        <p className="twin-muted">{reason} Showing a 2D top-down plan instead (x east, z south, metres). Canonical geometry, campus buildings and imported models need the 3D view.</p>
        <Button type="button" tone="ghost" onClick={onRetry}>Retry 3D view</Button>
      </div>
      <canvas
        ref={canvas}
        className="twin-plan-canvas"
        role="img"
        aria-label={`2D plan of ${layout.shownNodes} devices and ${layout.shownLinks} links; ${alerting.length} with active backend alerts. Select devices with the Inspect node control or the alert list.`}
        aria-describedby={legendId}
        onClick={pick}
      />
      <ul id={legendId} className="twin-plan-legend" aria-label="2D plan legend">
        <li><span aria-hidden="true">●</span> device</li>
        <li><span aria-hidden="true">■</span> active backend alert (larger square)</li>
        <li><span aria-hidden="true">◯</span> selected device (ring)</li>
      </ul>
      {layout.shownNodes < layout.totalNodes || layout.shownLinks < layout.totalLinks ? (
        <p className="twin-muted">Showing {layout.shownNodes} of {layout.totalNodes} devices and {layout.shownLinks} of {layout.totalLinks} links (selected and alerting devices first).</p>
      ) : null}
      {alerting.length ? (
        <ul className="twin-plan-alerts" aria-label="Devices with active backend alerts">
          {alerting.slice(0, MAX_ALERT_BUTTONS).map((node) => (
            <li key={node.id}>
              <Button type="button" tone="danger" aria-pressed={node.id === selectedNodeId} onClick={() => onSelectNode(node.id)}>ALERT {node.hostname}</Button>
            </li>
          ))}
          {alerting.length > MAX_ALERT_BUTTONS ? <li className="twin-muted">… {alerting.length - MAX_ALERT_BUTTONS} more (use Inspect node)</li> : null}
        </ul>
      ) : <p className="twin-muted">No devices with active backend alerts.</p>}
    </section>
  );
}
