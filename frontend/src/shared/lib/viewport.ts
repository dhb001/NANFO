import { useEffect, useState } from "react";

const narrowViewportQuery = "(max-width: 980px)";

export function useIsNarrowViewport(): boolean {
  const [isNarrowViewport, setIsNarrowViewport] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia(narrowViewportQuery).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }

    const matcher = window.matchMedia(narrowViewportQuery);
    const update = () => setIsNarrowViewport(matcher.matches);
    update();

    matcher.addEventListener("change", update);
    return () => matcher.removeEventListener("change", update);
  }, []);

  return isNarrowViewport;
}
