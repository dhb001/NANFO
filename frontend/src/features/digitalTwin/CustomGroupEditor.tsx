import { useState } from "react";
import { useDeviceGroups, useUpsertDeviceGroups } from "@/features/networks/hooks";
import type { UpsertDeviceGroupInput } from "@/shared/types/network";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { hasPermission } from "@/features/auth/permissions";
import { ApiClientError, toErrorMessage } from "@/shared/lib/errors";
import { Button } from "@/shared/ui/Button";
import { TwinInventoryPicker } from "./TwinInventoryPicker";
import { useSessionScope, authorityKey } from "@/features/auth/sessionScope";
import { retainedGroups, replaceReviewedGroups } from "./assetLifecycle";

const emptyGroup = (): UpsertDeviceGroupInput => ({ group_key: "", name: "", group_type: "custom", description: null, selector: {}, device_ids: [] });

function isGroupConflict(error: unknown) {
  return error instanceof ApiClientError && error.status === 409 && error.code === "DEVICE_GROUP_CONFLICT";
}

const CONFLICT_MESSAGE = "This group (or a retained group) changed on the server since it was loaded (DEVICE_GROUP_CONFLICT). Nothing was changed. Reload groups, select it again and re-apply your edits.";

export function CustomGroupEditor({ token, networkId, canWrite }: { token: string | null; networkId: string | null; canWrite: boolean }) {
  const query = useDeviceGroups(token, networkId);
  const save = useUpsertDeviceGroups(token, networkId);
  const scope = useSessionScope();
  const [removing, setRemoving] = useState(false);
  const [draft, setDraft] = useState(emptyGroup);
  const [editing, setEditing] = useState(false);
  /** C8: the `updated_at` of the record the draft was loaded from (or last saved as). */
  const [baseUpdatedAt, setBaseUpdatedAt] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const disabled = !canWrite || !token || !networkId || save.isPending || removing;
  const members = draft.device_ids ?? [];
  return <section aria-label="Custom device groups">
    {query.isFetching ? <p role="status">Loading groups…</p> : null}
    {query.isError ? <p role="alert">{toErrorMessage(query.error)}</p> : null}
    <Button tone="ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>Reload groups</Button>
    <p>{query.data?.total ?? "unknown"} groups. Saving updates only this key. Existing selectors are retained and may re-add matching devices.</p>
    <label>Edit custom group <select disabled={save.isPending || removing} value={editing ? draft.group_key : ""} onChange={(event) => {
      const group = query.data?.items.find((item) => item.group_key === event.target.value);
      if (!window.confirm("Load this group? Unsaved group edits will be replaced.")) return;
      setDraft(group ? { group_key: group.group_key, name: group.name, group_type: group.group_type, description: group.description, selector: { ...group.selector }, device_ids: [...group.device_ids] } : emptyGroup());
      setEditing(Boolean(group)); setBaseUpdatedAt(group?.updated_at ?? null); setMessage("");
    }}>
      <option value="">New custom group</option>
      {query.data?.items.map((group) => <option key={group.group_key} value={group.group_key}>{group.name} ({group.group_key})</option>)}
    </select></label>
    <form onSubmit={async (event) => {
      event.preventDefault();
      const auth = useAuthStore.getState();
      if (disabled || auth.endingSession || !hasPermission(auth.profile, "write:config") || useWorkspaceStore.getState().networkId !== networkId) return;
      if (!editing && query.data?.items.some((group) => group.group_key === draft.group_key)) { setMessage("That key exists. Select the existing custom group to edit it."); return; }
      if (!members.length && !Object.keys(draft.selector ?? {}).length) { setMessage("An empty group cannot be saved. Remove the selected persisted group to clear its final reference, or select an inventory device."); return; }
      if (!window.confirm(`Save group ${draft.group_key} with ${members.length} explicit members? Other groups are retained.`)) return;
      try {
        const saved = await save.mutateAsync({ replaceExisting: false, groups: [editing && baseUpdatedAt ? { ...draft, expected_updated_at: baseUpdatedAt } : draft] });
        setEditing(true);
        setBaseUpdatedAt(saved.items.find((item) => item.group_key === draft.group_key)?.updated_at ?? null);
        setMessage("Custom group saved.");
      } catch (error) {
        setMessage(isGroupConflict(error) ? `${CONFLICT_MESSAGE} Draft retained.` : `${toErrorMessage(error)} Draft retained; reload groups to check the outcome before retrying.`);
      }
    }}>
      <fieldset disabled={disabled}><legend>Group definition</legend>
        <p>Group type: {draft.group_type}</p>
        <label>Stable group key <input required maxLength={160} pattern="[a-z0-9_:\-]+" readOnly={editing} value={draft.group_key} onChange={(event) => setDraft({ ...draft, group_key: event.target.value })} /></label>
        <label>Group name <input required maxLength={160} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
        <label>Group description <textarea maxLength={400} value={draft.description ?? ""} onChange={(event) => setDraft({ ...draft, description: event.target.value || null })} /></label>
        {Object.keys(draft.selector ?? {}).length ? <><pre>{JSON.stringify(draft.selector, null, 2)}</pre>
          <Button type="button" tone="ghost" onClick={() => {
            if (window.confirm("Clear this group's selectors locally and use only the selected membership on save?")) setDraft({ ...draft, selector: {} });
          }}>Use explicit membership only</Button>
        </> : null}
        <TwinInventoryPicker token={token} networkId={networkId} selected={members} onToggle={(id) => setDraft({ ...draft, device_ids: members.includes(id) ? members.filter((member) => member !== id) : [...members, id] })} />
        <details><summary>Selected membership ({members.length})</summary>
          {members.map((id) => <div key={id}>{id} <Button type="button" tone="ghost" onClick={() => setDraft({ ...draft, device_ids: members.filter((member) => member !== id) })}>Remove {id}</Button></div>)}
        </details>
        <Button type="submit" permission="write:config" disabled={!query.data || query.isError || !draft.name.trim() || members.length > 5000}>{save.isPending ? "Saving group…" : "Save custom group"}</Button>
      </fieldset>
    </form>
    <Button tone="ghost" permission="write:config" disabled={disabled || !editing} onClick={async () => {
      if (disabled || !editing) return;
      setRemoving(true); setMessage("");
      try {
        const groups = await scope.request((credential) => retainedGroups(credential, networkId, draft.group_key, baseUpdatedAt));
        if (!window.confirm(`Remove persisted group ${draft.group_key}? Unsaved edits to it will be discarded. Full replacement retains ${groups.length} groups: ${groups.map((group) => group.group_key).join(", ") || "none"}. Each retained group is revision-checked; if any changed meanwhile nothing is removed. Proceed with this reviewed list?`)) return;
        scope.assertCurrent();
        if (scope.authority !== authorityKey() || !hasPermission(useAuthStore.getState().profile, "write:config") || useWorkspaceStore.getState().networkId !== networkId) throw new Error("Authority or network changed. Review the action again.");
        await scope.request((credential) => replaceReviewedGroups(credential, networkId, groups));
        setDraft(emptyGroup()); setEditing(false); setBaseUpdatedAt(null);
        const refreshed = await query.refetch();
        setMessage(refreshed.isError ? "Group removed; reload failed. Reload groups before further editing." : "Selected group removed; other groups retained.");
      } catch (error) { setMessage(isGroupConflict(error) ? CONFLICT_MESSAGE : `${toErrorMessage(error)} Draft retained; reload groups to check the outcome before retrying.`); }
      finally { setRemoving(false); }
    }}>Remove selected persisted group</Button>
    {message ? <p role="status">{message}</p> : null}
  </section>;
}
