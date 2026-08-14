import { useEffect, useState } from "react";

const mediaQuery = "(prefers-reduced-motion: reduce)";

export function usePrefersReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia(mediaQuery).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }

    const matcher = window.matchMedia(mediaQuery);
    const update = () => setPrefersReducedMotion(matcher.matches);
    update();

    matcher.addEventListener("change", update);
    return () => matcher.removeEventListener("change", update);
  }, []);

  return prefersReducedMotion;
}
