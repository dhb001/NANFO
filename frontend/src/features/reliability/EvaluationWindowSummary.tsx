import { formatTimestamp } from "@/shared/lib/format";
import { evaluationWindow } from "./origin";

/** Evaluation window recorded on a platform SLO alert (read-only evidence). */
export function EvaluationWindowSummary({ payload }: { payload: Record<string, unknown> }) {
  const window = evaluationWindow(payload);
  if (!window) return <p>Evaluation window: not recorded.</p>;
  return <p>Evaluation window: {window.start ? formatTimestamp(window.start) : "start not recorded"} to {window.end ? formatTimestamp(window.end) : "end not recorded"}
    {window.seconds !== null ? ` (${window.seconds} s)` : ""}; counter reset: {window.counterReset === null ? "not recorded" : window.counterReset ? "yes" : "no"}.</p>;
}
