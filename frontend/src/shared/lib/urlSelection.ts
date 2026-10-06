import { useEffect, useState } from "react";

function historyState(): Record<string, unknown> | null {
  const state: unknown = window.history.state;
  return state && typeof state === "object" ? state as Record<string, unknown> : null;
}

// Selection is navigational only; callers explicitly initiate every action.
export function useUrlSelection(parameter: string, scope: string) {
  const binding = `nanfo:${parameter}:scope`;
  const [value, setValue] = useState<string | null>(() => {
    const previous = historyState()?.[binding];
    return previous && previous !== scope ? null : new URLSearchParams(window.location.search).get(parameter);
  });
  useEffect(() => {
    const url = new URL(window.location.href);
    const bound = historyState()?.[binding];
    if (bound && bound !== scope) url.searchParams.delete(parameter);
    window.history.replaceState({ ...historyState(), [binding]: scope }, "", `${url.pathname}${url.search}${url.hash}`);
  }, [binding, parameter, scope]);
  useEffect(() => {
    const changed = () => setValue(new URLSearchParams(window.location.search).get(parameter));
    window.addEventListener("popstate", changed);
    return () => window.removeEventListener("popstate", changed);
  }, [parameter]);
  function select(next: string | null) {
    const url = new URL(window.location.href);
    if (next) url.searchParams.set(parameter, next);
    else url.searchParams.delete(parameter);
    window.history.replaceState({ ...historyState(), [binding]: scope }, "", `${url.pathname}${url.search}${url.hash}`);
    setValue(next);
  }
  return [value, select] as const;
}
