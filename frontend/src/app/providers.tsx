import { PropsWithChildren, useMemo } from "react";
import { ToastCenter } from "@/shared/ui/ToastCenter";
import { HotkeyLayer } from "@/shared/ui/HotkeyLayer";
import { CommandPalette } from "@/shared/ui/CommandPalette";

export function AppProviders({ children }: PropsWithChildren) {
  const overlays = useMemo(
    () => (
      <>
        <ToastCenter />
        <HotkeyLayer />
        <CommandPalette />
      </>
    ),
    [],
  );

  return (
    <>
      {children}
      {overlays}
    </>
  );
}
