import { useState, type FormEvent, type ReactNode } from "react";
import { toErrorMessage } from "@/shared/lib/errors";
import { isAmbiguousMutation } from "./tenancy-logic";
import { Button } from "@/shared/ui/Button";

/** Shared only by the tenancy and inventory editors owned by this workstream. */
export function ResourceForm({ label, submitLabel, disabled, onSubmit, onRefresh, children }: {
  label: string; submitLabel: string; disabled?: boolean; children: ReactNode;
  onSubmit: () => Promise<void>; onRefresh: () => Promise<unknown>;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const ambiguous = error !== null && isAmbiguousMutation(error);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (disabled || pending || (ambiguous && !reviewed)) return;
    setPending(true); setError(null); setSuccess(false); setReviewed(false);
    try { await onSubmit(); setSuccess(true); } catch (failure) { setError(failure); }
    finally { setPending(false); }
  }
  return <form aria-label={label} onSubmit={submit} style={{ display: "grid", gap: "0.6rem", marginBlock: "0.7rem" }}>
    <fieldset disabled={disabled || pending} style={{ border: 0, padding: 0, margin: 0, display: "grid", gap: "0.55rem", minWidth: 0 }}>
      {children}
      <Button permission="write:config" type="submit" disabled={ambiguous && !reviewed}>{pending ? "Saving…" : submitLabel}</Button>
    </fieldset>
    {pending ? <p role="status">Request pending. Keep this scope open until the outcome is known.</p> : null}
    {error !== null ? <div role="alert"><strong>{ambiguous ? "Outcome uncertain" : "Request failed"}</strong><p>{toErrorMessage(error)}</p>
      {ambiguous ? <><p>The server may have saved this change. Your draft is retained. Refresh and inspect all relevant pages before submitting again to avoid duplicates.</p>
        <Button type="button" tone="ghost" disabled={refreshing} onClick={async () => {
          setRefreshing(true);
          try { await onRefresh(); } catch { /* QueryState displays read failures. */ }
          finally { setRefreshing(false); }
        }}>{refreshing ? "Refreshing…" : "Refresh records"}</Button>
        <label><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} /> I checked the records and intend to submit again</label>
      </> : <p>Your draft is retained. Correct the input or permissions and try again.</p>}
    </div> : null}
    {success ? <p role="status">{label} completed.</p> : null}
  </form>;
}

export function DeleteResource({ name, disabled, onDelete, onRefresh, detail }: {
  name: string; disabled?: boolean; onDelete: () => Promise<void>; onRefresh: () => Promise<unknown>; detail?: string;
}) {
  const [confirm, setConfirm] = useState(false);
  return confirm ? <ResourceForm label={`Delete ${name}`} submitLabel="Confirm deletion" disabled={disabled} onSubmit={async () => { await onDelete(); setConfirm(false); }} onRefresh={onRefresh}>
    <p>Delete {name}? {detail ?? "Historical evidence is retained. The server may reject deletion while resources are in use."}</p>
    <Button type="button" tone="ghost" onClick={() => setConfirm(false)}>Cancel deletion</Button>
  </ResourceForm> : <Button permission="write:config" type="button" tone="danger" disabled={disabled} onClick={() => setConfirm(true)}>Delete {name}</Button>;
}
