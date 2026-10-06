import { useLiveStore, type RealtimeChannel } from "./store";
import { Button } from "@/shared/ui/Button";

const CHANNEL_LABELS: Record<RealtimeChannel, string> = {
  topology: "topology",
  telemetry: "telemetry",
  alerts: "alerts",
  digitalTwin: "digital twin",
};

// ADR-028 C1: a per-user socket cap stops the client; resuming is an explicit operator action.
export function RealtimeRetryControl() {
  const halts = useLiveStore((state) => state.realtimeHalts);
  const retryRealtime = useLiveStore((state) => state.retryRealtime);
  const limited = (Object.keys(halts) as RealtimeChannel[]).filter((channel) => halts[channel]?.reason === "connection_limit");
  if (!limited.length) return null;
  return (
    <div className="realtime-halt" role="status">
      <span>
        Realtime paused for {limited.map((channel) => CHANNEL_LABELS[channel]).join(", ")}: your account has too many
        concurrent realtime connections. Close other NANFO tabs or devices, then retry. Pages still refresh on demand.
      </span>
      <Button tone="ghost" onClick={retryRealtime}>Retry realtime</Button>
    </div>
  );
}
