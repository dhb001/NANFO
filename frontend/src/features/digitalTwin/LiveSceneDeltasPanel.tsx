import { useLiveStore } from "@/features/realtime/store";
import { SceneReconciliationStatus } from "@/features/realtime/SceneReconciliationStatus";
import { formatTimestamp } from "@/shared/lib/format";
import { Badge } from "@/shared/ui/Badge";
import { Panel } from "@/shared/ui/Panel";
import type { TwinOverlayObject } from "./sceneAdapter";
import { overlayTone } from "./twinStatusTones";

export const MAX_DELTA_CARDS = 8;

/** Realtime channel state shown in the Twin header (text + tone, never colour alone). */
export function TwinChannelBadges() {
  const topologyStatus = useLiveStore((state) => state.topologyStatus);
  const digitalTwinStatus = useLiveStore((state) => state.digitalTwinStatus);
  return (
    <div className="twin-badges">
      <Badge text={`topology ${topologyStatus}`} tone={topologyStatus === "open" ? "ok" : "warn"} />
      <Badge text={`digital twin ${digitalTwinStatus}`} tone={digitalTwinStatus === "open" ? "ok" : "warn"} />
    </div>
  );
}

/** Newest simulation/intent scene deltas with their observation time and reconciliation state. */
export function LiveSceneDeltasPanel({ overlays }: { overlays: readonly TwinOverlayObject[] }) {
  const lastSeen = useLiveStore((state) => state.sceneObjectLastSeen);
  const availability = useLiveStore((state) => state.sceneObjectAvailability);
  const cards = overlays.slice(0, MAX_DELTA_CARDS);
  return (
    <Panel title="Live Scene Deltas" subtitle="simulation and intent websocket deltas">
      <SceneReconciliationStatus />
      {cards.length === 0 ? <p className="twin-muted">No scene deltas observed yet.</p> : (
        <ul className="twin-card-list" aria-label="Recent scene deltas">
          {cards.map((overlay) => {
            const seen = lastSeen[overlay.id];
            return (
              <li key={overlay.id} className="twin-card twin-card--compact">
                <div className="twin-row">
                  <strong>{overlay.id}</strong>
                  <Badge text={overlay.objectType} tone="info" />
                </div>
                <p className="twin-meta">
                  Last observed: {seen ? formatTimestamp(new Date(seen).toISOString()) : "unavailable"}. Detail reconciliation: {availability[overlay.id] ?? "stale"}. Snapshot only, not continuous proof.
                </p>
                {overlay.status ? <div><Badge text={overlay.status} tone={overlayTone(overlay)} /></div> : null}
                {overlay.spatialRefId ? <div className="mono twin-meta">{overlay.spatialRefId}</div> : null}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
