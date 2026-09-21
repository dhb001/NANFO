import { useCallback, useSyncExternalStore, type SetStateAction } from "react";
import { useAuthStore } from "@/shared/state/auth-store";

// AppShell remounts its Outlet on selection changes. Keep bounded navigation
// state across those remounts, isolated by session generation and owning scope.
const navigation = new Map<string, unknown>();
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export function useScopeState<T>(name: string, scope: string | null, initial: T) {
  const generation = useAuthStore((s) => s.generation);
  const key = JSON.stringify([generation, name, scope]);
  const value = useSyncExternalStore(subscribe, () => navigation.has(key) ? navigation.get(key) as T : initial);
  const update = useCallback((next: SetStateAction<T>) => {
    const previous = navigation.has(key) ? navigation.get(key) as T : initial;
    const resolved = typeof next === "function" ? (next as (previous: T) => T)(previous) : next;
    navigation.set(key, resolved);
    if (navigation.size > 50) navigation.delete(navigation.keys().next().value!);
    listeners.forEach((listener) => listener());
  }, [key, initial]);
  return [value, update] as const;
}
