import { useId, useState, type ReactNode } from "react";
import { Button } from "@/shared/ui/Button";

/**
 * Toggle button + disclosed content (aria-expanded/aria-controls). `keepMounted` keeps the
 * content (and any draft in it) mounted but hidden after the first open.
 */
export function TwinDisclosure({ label, openLabel, keepMounted = false, children }: {
  label: string;
  openLabel?: string;
  keepMounted?: boolean;
  children: ReactNode;
}) {
  const contentId = useId();
  const [open, setOpen] = useState(false);
  const [opened, setOpened] = useState(false);
  const mounted = open || (keepMounted && opened);
  return (
    <div className="twin-disclosure">
      <Button type="button" tone="ghost" aria-expanded={open} aria-controls={mounted ? contentId : undefined}
        onClick={() => { setOpened(true); setOpen((value) => !value); }}>
        {open && openLabel ? openLabel : label}
      </Button>
      {mounted ? <div id={contentId} hidden={!open}>{children}</div> : null}
    </div>
  );
}
