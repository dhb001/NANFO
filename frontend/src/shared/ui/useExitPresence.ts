import { useEffect, useState } from "react";

// Retain exiting content for its CSS animation; reopening cancels the removal.
export function useExitPresence(open: boolean, duration = 200) {
  const [retained, setRetained] = useState(open);
  useEffect(() => {
    if (open) {
      setRetained(true);
      return;
    }
    const timer = window.setTimeout(() => setRetained(false), duration);
    return () => window.clearTimeout(timer);
  }, [open, duration]);
  return open || retained;
}
