import { create } from "zustand";
import type { ApiMeta } from "@/shared/types/api";

export const useExecutionModeStore = create<{
  mode: ApiMeta["execution_mode"] | null;
  observe: (mode: unknown) => void;
  reset: () => void;
}>((set) => ({
  mode: null,
  observe: (mode) => {
    if (mode === "demo" || mode === "emulation" || mode === "production") set({ mode });
  },
  reset: () => set({ mode: null }),
}));
