import { useEffect, useState } from "react";

/** `value`, updated only after it has been stable for `delayMs` (typing does not issue a request per keystroke). */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    if (Object.is(value, debounced)) return;
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, debounced, delayMs]);
  return debounced;
}
