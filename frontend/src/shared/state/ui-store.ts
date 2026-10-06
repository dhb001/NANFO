import { create } from "zustand";
import { randomId } from "@/shared/lib/uid";

export interface ToastItem {
  id: string;
  title: string;
  description?: string;
  tone: "info" | "ok" | "warn" | "danger";
}

/** At most this many toasts are kept; the oldest non-danger toast is dropped first. */
export const MAX_TOASTS = 5;

interface UIState {
  commandPaletteOpen: boolean;
  toasts: ToastItem[];
  setCommandPaletteOpen: (open: boolean) => void;
  pushToast: (item: Omit<ToastItem, "id">) => void;
  dismissToast: (id: string) => void;
}

function capToasts(toasts: ToastItem[]): ToastItem[] {
  const next = [...toasts];
  while (next.length > MAX_TOASTS) {
    const disposable = next.findIndex((toast) => toast.tone !== "danger");
    next.splice(disposable === -1 ? 0 : disposable, 1);
  }
  return next;
}

export const useUiStore = create<UIState>((set) => ({
  commandPaletteOpen: false,
  toasts: [],
  setCommandPaletteOpen: (commandPaletteOpen) => set({ commandPaletteOpen }),
  pushToast: (item) =>
    set((state) => ({
      toasts: capToasts([...state.toasts, { ...item, id: randomId("toast") }]),
    })),
  dismissToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((toast) => toast.id !== id),
    })),
}));
