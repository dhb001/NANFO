import { useLayoutEffect, type RefObject } from "react";

/**
 * Keyboard focus survives a scope switch (ADR-028). AppShell remounts the workspace
 * content when the organization, workspace or network changes, which would drop focus
 * to <body>. A control that changes scope calls `rememberFocus(key)` first and carries
 * `data-focus-key={key}`; the shell restores focus to the same control once it renders
 * again (lists may still be loading), unless the operator has moved focus meanwhile.
 */
export const FOCUS_RESTORE_WINDOW_MS = 3_000;

let pending: { key: string; expires: number } | null = null;

export function rememberFocus(key: string, now = Date.now()): void {
  pending = { key, expires: now + FOCUS_RESTORE_WINDOW_MS };
}

export function clearRememberedFocus(): void {
  pending = null;
}

function focusWasLost(root: HTMLElement): boolean {
  const active = document.activeElement;
  return !active || active === document.body || active === root;
}

/** "restored", "waiting" (target not rendered yet) or "none" (nothing pending, expired, or focus moved on). */
export function restoreRememberedFocus(root: HTMLElement, now = Date.now()): "restored" | "waiting" | "none" {
  if (!pending) return "none";
  if (now > pending.expires || !focusWasLost(root)) {
    pending = null;
    return "none";
  }
  const key = pending.key;
  const target = Array.from(root.querySelectorAll<HTMLElement>("[data-focus-key]")).find((element) => element.dataset.focusKey === key);
  if (!target) return "waiting";
  pending = null;
  target.focus({ preventScroll: true });
  return "restored";
}

/** Restore remembered focus into `root` after each `contextKey` remount. */
export function useFocusRestoration(root: RefObject<HTMLElement | null>, contextKey: string): void {
  useLayoutEffect(() => {
    const element = root.current;
    if (!element || restoreRememberedFocus(element) !== "waiting") return;
    const observer = new MutationObserver(() => {
      if (restoreRememberedFocus(element) !== "waiting") observer.disconnect();
    });
    observer.observe(element, { childList: true, subtree: true });
    const timer = window.setTimeout(() => { observer.disconnect(); clearRememberedFocus(); }, FOCUS_RESTORE_WINDOW_MS);
    return () => { observer.disconnect(); window.clearTimeout(timer); };
  }, [root, contextKey]);
}
