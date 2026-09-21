import { useEffect, useState } from "react";

// Selection is navigational only; callers explicitly initiate every action.
export function useUrlSelection(parameter: string, scope: string) {
  const binding = `nanfo:${parameter}:scope`;
  const [value, setValue] = useState<string | null>(() => {
    const previous = window.history.state?.[binding];
    return previous && previous !== scope ? null : new URLSearchParams(window.location.search).get(parameter);
  });
  useEffect(() => {
    const url = new URL(window.location.href);
    if (window.history.state?.[binding] && window.history.state[binding] !== scope) url.searchParams.delete(parameter);
    window.history.replaceState({ ...window.history.state, [binding]: scope }, "", `${url.pathname}${url.search}${url.hash}`);
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
    window.history.replaceState({ ...window.history.state, [binding]: scope }, "", `${url.pathname}${url.search}${url.hash}`);
    setValue(next);
  }
  return [value, select] as const;
}
