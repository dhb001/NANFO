import { ModelPanel } from "./ModelPanel";
import { ConfigurationPanel } from "./ConfigurationPanel";
import { OverridePanel } from "./OverridePanel";
import type { AutonomyStatus } from "./types";

export function OperatorPanels({ panel, now, control, controlFresh, stopPending, refreshControl }: {
  panel: string; now: number; control: AutonomyStatus | undefined; controlFresh: boolean; stopPending: boolean; refreshControl: () => void;
}) {
  if (panel === "model") return <ModelPanel now={now} />;
  if (panel === "configuration") return <ConfigurationPanel now={now} />;
  return <OverridePanel now={now} control={control} controlFresh={controlFresh} stopPending={stopPending} refreshControl={refreshControl} />;
}
