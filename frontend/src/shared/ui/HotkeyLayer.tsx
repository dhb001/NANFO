import { useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useUiStore } from "@/shared/state/ui-store";
import {
  resolveChordNavigation,
  shouldIgnoreHotkeyTarget,
} from "@/shared/lib/hotkeys";

export function HotkeyLayer() {
  const navigate = useNavigate();
  const setCommandPaletteOpen = useUiStore((state) => state.setCommandPaletteOpen);
  const commandPaletteOpen = useUiStore((state) => state.commandPaletteOpen);
  const prefixRef = useRef<string | null>(null);
  const resetTimerRef = useRef<number | null>(null);

  const clearPrefixTimer = useCallback(() => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  }, []);

  const resetPrefix = useCallback(() => {
    prefixRef.current = null;
    clearPrefixTimer();
  }, [clearPrefixTimer]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();

      if ((event.metaKey || event.ctrlKey) && key === "k") {
        event.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
        return;
      }

      if (key === "escape") {
        resetPrefix();
        if (commandPaletteOpen) {
          setCommandPaletteOpen(false);
        }
        return;
      }

      if (event.shiftKey || event.metaKey || event.ctrlKey || event.altKey) {
        resetPrefix();
        return;
      }

      if (shouldIgnoreHotkeyTarget(event.target)) {
        resetPrefix();
        return;
      }

      const result = resolveChordNavigation(prefixRef.current, key);
      prefixRef.current = result.nextPrefix;

      clearPrefixTimer();
      if (result.nextPrefix) {
        resetTimerRef.current = window.setTimeout(resetPrefix, 1200);
      }

      if (result.path) {
        event.preventDefault();
        resetPrefix();
        navigate(result.path);
      }
    };

    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      resetPrefix();
    };
  }, [clearPrefixTimer, commandPaletteOpen, navigate, resetPrefix, setCommandPaletteOpen]);

  return null;
}
