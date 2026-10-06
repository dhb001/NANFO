import { useState } from "react";
import { useSessionScope, authorityKey } from "@/features/auth/sessionScope";
import { hasPermission } from "@/features/auth/permissions";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { toErrorMessage } from "@/shared/lib/errors";
import { Button } from "@/shared/ui/Button";
import type { CampusModelAssetRecord } from "@/shared/types/network";
import { clearTwinRecords, retireModelAsset } from "./assetLifecycle";

export function TwinLifecycleControls({ networkId, assets, selectedId, onSelect, onRetired, onReload, disabled = false }: {
  networkId: string | null; assets: CampusModelAssetRecord[]; selectedId: string;
  onSelect: (id: string) => void; onRetired: (id: string) => void;
  onReload: () => Promise<boolean>; disabled?: boolean;
}) {
  const scope = useSessionScope();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const selected = assets.find((asset) => asset.campus_model_asset_id === selectedId);
  const canWrite = hasPermission(useAuthStore((state) => state.profile), "write:config");
  const blocked = disabled || busy || !networkId;

  async function mutate(kind: "asset" | "groups" | "buildings") {
    if (blocked || !canWrite || (kind === "asset" && !selected)) return;
    const id = selected?.campus_model_asset_id;
    const description = kind === "asset"
      ? `Retire selected asset ${selected!.model_file_name} (${id}) from network ${networkId}? Historical bytes and scene history remain. An unchanged local restore of this asset will be cleared; unrelated local imports remain.`
      : `Clear ALL active ${kind} in network ${networkId}? This replaces the entire ${kind} list with an empty list, including unrelated ${kind}. Local imports and historical evidence remain. This is not a selected-record removal.`;
    setBusy(true); setMessage(""); setFailed(false);
    try {
      scope.token();
      if (!window.confirm(description)) return;
      scope.assertCurrent();
      if (scope.authority !== authorityKey() || !hasPermission(useAuthStore.getState().profile, "write:config") || useWorkspaceStore.getState().networkId !== networkId) throw new Error("Authority or network changed. Review the action again.");
      await scope.request(async (token) => { await (kind === "asset" ? retireModelAsset(token, networkId, id!) : clearTwinRecords(token, networkId, kind)); });
      if (kind === "asset") onRetired(id!);
      setMessage(kind === "asset" ? "Selected asset retired." : `All active ${kind} cleared.`);
      if (!await onReload()) setMessage("Change succeeded, but reload failed. Reload persisted Twin records to check current state.");
    } catch (error) {
      setFailed(true); setMessage(`${toErrorMessage(error)} Reload persisted Twin records to check the outcome before retrying.`);
    } finally { setBusy(false); }
  }

  return <section aria-label="Persisted Twin lifecycle">
    <h3>Persisted Twin records</h3>
    <label>Persisted model asset <select value={selectedId} disabled={blocked} onChange={(event) => onSelect(event.target.value)}>
      <option value="">Choose an asset to restore or retire</option>
      {assets.map((asset) => <option key={asset.campus_model_asset_id} value={asset.campus_model_asset_id}>{asset.model_file_name} · {asset.created_at} · {asset.campus_model_asset_id}</option>)}
    </select></label>
    <Button tone="ghost" disabled={blocked} onClick={async () => {
      setBusy(true);
      try { const ok = await onReload(); setFailed(!ok); setMessage(ok ? "Persisted Twin records reloaded." : "Reload failed. Try again."); }
      catch (error) { setFailed(true); setMessage(toErrorMessage(error)); }
      finally { setBusy(false); }
    }}>Reload persisted Twin records</Button>
    <Button tone="ghost" permission="write:config" disabled={blocked || !selected || !canWrite} onClick={() => void mutate("asset")}>Retire selected asset</Button>
    <details><summary>Clear active groups or campus buildings</summary>
      <p>These actions clear every active record of the chosen kind in this network. Review groups and building records first. Canonical scene objects and local imports are separate.</p>
      <Button tone="ghost" permission="write:config" disabled={blocked || !canWrite} onClick={() => void mutate("groups")}>Clear all persisted groups</Button>
      <Button tone="ghost" permission="write:config" disabled={blocked || !canWrite} onClick={() => void mutate("buildings")}>Clear all persisted buildings</Button>
    </details>
    {message ? <p role={failed ? "alert" : "status"}>{message}</p> : null}
  </section>;
}
