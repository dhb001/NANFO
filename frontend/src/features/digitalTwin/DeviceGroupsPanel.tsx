import { useState } from "react";
import { useDeviceGroups, useUpsertDeviceGroups } from "@/features/networks/hooks";
import { ApiClientError, toErrorMessage } from "@/shared/lib/errors";
import type { DeviceGroupRecord } from "@/shared/types/network";
import { useUiStore } from "@/shared/state/ui-store";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { ConfirmDialog } from "./ConfirmDialog";
import { describeGroupConflicts, deriveGroupProposal, type GroupConflict, type GroupFocus, type GroupProposal, type GroupProposalNode } from "./groupProposal";

interface Review {
  proposal: GroupProposal;
  /** The server list the proposal (and its expected_updated_at values) was computed from. */
  basis: DeviceGroupRecord[];
  conflicts: GroupConflict[];
  error: string | null;
}

export function DeviceGroupsPanel({ token, networkId, nodes, focus, graphComplete, graphFetching }: {
  token: string | null;
  networkId: string | null;
  nodes: readonly GroupProposalNode[];
  focus: GroupFocus;
  graphComplete: boolean;
  graphFetching: boolean;
}) {
  const query = useDeviceGroups(token, networkId);
  const save = useUpsertDeviceGroups(token, networkId);
  const pushToast = useUiStore((state) => state.pushToast);
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const loaded = Boolean(query.data) && !query.isError;
  const canPropose = loaded && graphComplete && !graphFetching && nodes.length > 0 && Boolean(token && networkId) && !busy;

  function open() {
    if (!query.data || !canPropose) return;
    const basis = query.data.items;
    setReview({ proposal: deriveGroupProposal({ nodes, focus, existingGroups: basis }), basis, conflicts: [], error: null });
  }

  async function confirm() {
    if (!review || review.proposal.blockedReason) return;
    setBusy(true);
    try {
      const saved = await save.mutateAsync({ replaceExisting: false, groups: review.proposal.groups.map((item) => item.input) });
      setReview(null);
      pushToast({ tone: "ok", title: "Device groups persisted", description: saved.items.map((item) => `${item.group_key}: ${item.device_ids.length} members`).join("; ") || "Native network device groups updated." });
    } catch (error) {
      if (error instanceof ApiClientError && error.status === 409 && error.code === "DEVICE_GROUP_CONFLICT") {
        const reloaded = await query.refetch();
        if (reloaded.isError || !reloaded.data) {
          setReview({ ...review, error: "Another change was saved first, and reloading the current groups failed. Close and retry." });
        } else {
          const keys = review.proposal.groups.map((item) => item.input.group_key);
          const fresh = reloaded.data.items;
          setReview({ proposal: deriveGroupProposal({ nodes, focus, existingGroups: fresh }), basis: fresh,
            conflicts: describeGroupConflicts(review.basis, fresh, keys), error: "These groups changed on the server since they were read. Review the reloaded state below and confirm again." });
        }
      } else {
        setReview({ ...review, error: `${toErrorMessage(error)} Nothing was confirmed as saved; reload groups to check before retrying.` });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="twin-card" aria-label="Device groups">
      <h4 className="twin-card-title">Device groups</h4>
      {query.isLoading ? <p role="status" className="twin-muted">Loading persisted device groups…</p> : null}
      {query.isError ? (
        <div role="alert" className="twin-error">
          Persisted device groups unavailable: {toErrorMessage(query.error)}{" "}
          <Button type="button" tone="ghost" onClick={() => void query.refetch()}>Retry loading groups</Button>
        </div>
      ) : null}
      <div className="twin-badges">
        {loaded ? <Badge text={`persisted ${query.data!.total}`} tone={query.data!.total > 0 ? "ok" : "neutral"} /> : null}
        <Badge text="native network groups" tone="info" />
      </div>
      <p className="twin-muted">Scope uses persisted spatial_ref_id values only; the server resolves members from selectors.</p>
      {!loaded && !query.isLoading ? <p className="twin-muted">Group persistence needs the current group list (for concurrency checks).</p> : null}
      <div className="twin-actions">
        <Button type="button" tone="ghost" permission="write:config" disabled={!canPropose} onClick={open}>
          {busy ? "Persisting groups..." : "Persist Device Groups"}
        </Button>
      </div>
      {review ? (
        <ConfirmDialog
          title="Review device groups before persisting"
          confirmLabel="Confirm and persist groups"
          busy={busy}
          confirmDisabled={Boolean(review.proposal.blockedReason)}
          onCancel={() => setReview(null)}
          onConfirm={() => void confirm()}
        >
          {review.error ? <p role="alert" className="twin-error">{review.error}</p> : null}
          {review.conflicts.length ? (
            <ul aria-label="Server changes since last read" className="twin-diff-list">
              {review.conflicts.map((conflict) => (
                <li key={conflict.groupKey}>
                  <strong>{conflict.groupKey}</strong>: {conflict.change}
                  {conflict.fields.length ? ` (${conflict.fields.join(", ")})` : ""} · updated {conflict.previousUpdatedAt ?? "never"} → {conflict.currentUpdatedAt ?? "deleted"}
                  {conflict.previousMembers !== null || conflict.currentMembers !== null ? ` · members ${conflict.previousMembers ?? 0} → ${conflict.currentMembers ?? 0}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
          <p>Scope: <strong>{review.proposal.scope.label}</strong> ({review.proposal.scope.source === "focus" ? "campus focus" : review.proposal.scope.source === "persisted_majority" ? "most common persisted building" : "whole network"})
            {review.proposal.scope.sitePrefix ? <> · site_prefix <code>{review.proposal.scope.sitePrefix}</code></> : null}</p>
          <p>{review.proposal.persistedDevicesInScope} devices currently in scope · {review.proposal.devicesWithoutPersistedRef} without a persisted spatial_ref_id.</p>
          {review.proposal.blockedReason ? <p role="alert" className="twin-error">{review.proposal.blockedReason}</p> : null}
          <ul aria-label="Proposed groups" className="twin-diff-list">
            {review.proposal.groups.map((item) => (
              <li key={item.input.group_key}>
                <strong>{item.action === "create" ? "Create" : "Update"}</strong> {item.input.name} (<code>{item.input.group_key}</code>, {item.input.group_type})
                · selector <code>{JSON.stringify(item.input.selector)}</code>
                · {item.input.device_ids?.length ? `${item.input.device_ids.length} explicit members` : "members resolved by the server"}
                {item.existing ? ` · expected_updated_at ${item.existing.updated_at}` : ""}
                {item.changes.length ? ` · ${item.changes.join("; ")}` : ""}
              </li>
            ))}
          </ul>
          <p className="twin-muted">Other groups are retained (no replacement).</p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}
