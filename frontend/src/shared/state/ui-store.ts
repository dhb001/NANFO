import { create } from "zustand";
import { randomId } from "@/shared/lib/uid";

export interface ToastItem {
  id: string;
  title: string;
  description?: string;
  tone: "info" | "ok" | "warn" | "danger";
}

interface UIState {
  commandPaletteOpen: boolean;
  toasts: ToastItem[];
  setCommandPaletteOpen: (open: boolean) => void;
  pushToast: (item: Omit<ToastItem, "id">) => void;
  dismissToast: (id: string) => void;
}

export const useUiStore = create<UIState>((set) => ({
  commandPaletteOpen: false,
  toasts: [],
  setCommandPaletteOpen: (commandPaletteOpen) => set({ commandPaletteOpen }),
  pushToast: (item) =>
    set((state) => ({
      toasts: [...state.toasts, { ...item, id: randomId("toast") }],
    })),
  dismissToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((toast) => toast.id !== id),
    })),
}));
