import { useExecutionModeStore } from "@/shared/state/execution-mode-store";

export function ExecutionModeBanner() {
  const mode = useExecutionModeStore((state) => state.mode);
  const labels = {
    demo: "Demo mode: synthetic data. No real network execution or measured simulation validation.",
    emulation: "Emulation mode: not production. Real control capability is not implied.",
    production: "Production mode: backend authorization and validation still apply. Synthetic records remain labeled.",
  };
  return <div role="status" className="execution-banner">
    {mode ? labels[mode] : "Execution mode: Unknown. Awaiting authoritative backend response; no live-control assurance."}
  </div>;
}
