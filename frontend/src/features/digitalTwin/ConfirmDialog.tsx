import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/shared/ui/Button";

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Modal confirmation with explicit focus management: focus moves into the dialog
 * (Cancel first, so Enter never confirms by accident), Tab is trapped, Escape cancels
 * and focus returns to the element that opened the dialog.
 */
export function ConfirmDialog({ title, children, confirmLabel, cancelLabel = "Cancel", onConfirm, onCancel, busy = false, confirmDisabled = false, danger = false }: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
  confirmDisabled?: boolean;
  danger?: boolean;
}) {
  const titleId = useId();
  const bodyId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const cancelHandler = useRef(onCancel);
  cancelHandler.current = onCancel;

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.querySelector<HTMLElement>("[data-dialog-cancel]")?.focus();
    return () => { if (opener?.isConnected) opener.focus(); };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (!busy) cancelHandler.current();
      return;
    }
    if (event.key !== "Tab" || !dialog.current) return;
    const items = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  return createPortal(
    <div className="twin-dialog-backdrop">
      <div ref={dialog} className="twin-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={bodyId} onKeyDown={onKeyDown}>
        <h2 id={titleId} className="twin-dialog-title">{title}</h2>
        <div id={bodyId} className="twin-dialog-body">{children}</div>
        <div className="twin-actions twin-dialog-actions">
          <Button data-dialog-cancel="" type="button" tone="ghost" disabled={busy} onClick={onCancel}>{cancelLabel}</Button>
          <Button type="button" tone={danger ? "danger" : "primary"} disabled={busy || confirmDisabled} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
