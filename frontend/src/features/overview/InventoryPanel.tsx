import { useEffect, useState } from "react";
import { useCreateDevice, useCreateNetwork, useDeleteDevice, useDeleteNetwork, useDevices, useNetworks, useUpdateDevice, useUpdateNetwork } from "@/features/networks/hooks";
import { DeviceForm, NetworkForm } from "./InventoryForms";
import { changedDeviceFields, changedNetworkFields } from "./inventory-logic";
import { DeleteResource } from "@/features/organizations/ResourceForm";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useAuthStore } from "@/shared/state/auth-store";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";
import { Pagination } from "@/shared/ui/Pagination";
import { Badge } from "@/shared/ui/Badge";
import { deviceStatusTone, statusLabel } from "@/shared/lib/statusTones";
import { rememberFocus } from "@/shared/lib/focusRestore";
import { Button } from "@/shared/ui/Button";
import { useScopeState } from "@/features/organizations/useScopeState";
import type { Device, Network } from "@/shared/types/network";

export function InventoryPanel({ canWrite }: { canWrite: boolean }) {
  const token = useAuthStore((s) => s.accessToken);
  const workspaceId = useWorkspaceStore((s) => s.workspaceId);
  const networkId = useWorkspaceStore((s) => s.networkId);
  const selectNetwork = useWorkspaceStore((s) => s.setNetworkId);
  const [page, setPage] = useScopeState("inventory-network-page", workspaceId, 1);
  const [initialSelection, setInitialSelection] = useScopeState("inventory-initial-selection", workspaceId, true);
  const [selected, setSelected] = useScopeState<Network | null>("inventory-network-selected", workspaceId, null);
  const [editing, setEditing] = useState<Network | null>(null);
  const networks = useNetworks(token, workspaceId, page);
  const create = useCreateNetwork(token, workspaceId);
  const update = useUpdateNetwork(token, workspaceId);
  const remove = useDeleteNetwork(token, workspaceId);
  useEffect(() => {
    if (initialSelection && !networkId && networks.data?.items[0]) selectNetwork(networks.data.items[0].network_id);
  }, [initialSelection, networkId, networks.data, selectNetwork]);
  useEffect(() => {
    if (networks.data && page > Math.max(1, Math.ceil(networks.data.total / 20))) setPage(Math.max(1, Math.ceil(networks.data.total / 20)));
  }, [networks.data, page, setPage]);
  const active = networks.data?.items.find((n) => n.network_id === networkId) ?? (selected?.network_id === networkId ? selected : null);
  return <>
    <div className="inventory-grid">
      <Panel title="Networks" subtitle="Select active network context for all views">
        <p role="status">Selected network: {active?.name ?? networkId ?? "None"}</p>
        <details><summary>Create a network</summary><NetworkForm disabled={!workspaceId || !canWrite} onRefresh={() => networks.refetch()} onSave={async (input) => {
          const created = await create.mutateAsync(input); setSelected(created); setInitialSelection(false); selectNetwork(created.network_id);
        }} /></details>
        <QueryState query={networks} hasData={(d) => d.items.length > 0} emptyTitle="No networks" emptyDescription="Create a network in this workspace.">
          {(data) => <div style={{ display: "grid", gap: "0.5rem" }}>{data.items.map((network, index) => <div key={network.network_id}>
            <button className="network-choice" data-focus-key={`network-choice:${network.network_id}`} aria-pressed={network.network_id === networkId} onClick={() => { setSelected(network); rememberFocus(`network-choice:${network.network_id}`); selectNetwork(network.network_id); }}>
              <span className="network-choice-index">{String((page - 1) * 20 + index + 1).padStart(2, "0")}</span>
              <span><strong>{network.name}</strong><small>{network.network_id}</small></span>
              <span aria-hidden="true">{network.network_id === networkId ? "●" : "↗"}</span>
            </button>
            <Button permission="write:config" tone="ghost" disabled={!canWrite} onClick={() => setEditing(network)}>Edit {network.name}</Button>
            <DeleteResource name={network.name} disabled={!canWrite} onRefresh={() => networks.refetch()} onDelete={async () => {
              await remove.mutateAsync(network.network_id);
              setInitialSelection(false);
              if (useWorkspaceStore.getState().networkId === network.network_id) { selectNetwork(null); setSelected(null); }
              if (editing?.network_id === network.network_id) setEditing(null);
            }} />
          </div>)}</div>}
        </QueryState>
        <Pagination label="Networks" page={page} pageSize={20} total={networks.data?.total ?? 0} pending={networks.isFetching} onPageChange={setPage} />
        {editing ? <div><NetworkForm key={editing.network_id} network={editing} disabled={!canWrite} onRefresh={() => networks.refetch()} onSave={async (input) => {
          const changes = changedNetworkFields(editing, input);
          if (Object.keys(changes).length) { const saved = await update.mutateAsync({ networkId: editing.network_id, changes }); setSelected(saved); }
          setEditing(null);
        }} /><Button tone="ghost" onClick={() => setEditing(null)}>Close network editor</Button></div> : null}
      </Panel>
      <DeviceInventory key={networkId ?? "none"} canWrite={canWrite} />
    </div>
  </>;
}

function DeviceInventory({ canWrite }: { canWrite: boolean }) {
  const token = useAuthStore((s) => s.accessToken);
  const networkId = useWorkspaceStore((s) => s.networkId);
  const [page, setPage] = useScopeState("inventory-device-page", networkId, 1);
  const [selected, setSelected] = useState<Device | null>(null);
  const [editing, setEditing] = useState<Device | null>(null);
  const devices = useDevices(token, networkId, page);
  const create = useCreateDevice(token, networkId);
  const update = useUpdateDevice(token, networkId);
  const remove = useDeleteDevice(token, networkId);
  useEffect(() => {
    if (devices.data && page > Math.max(1, Math.ceil(devices.data.total / 20))) setPage(Math.max(1, Math.ceil(devices.data.total / 20)));
  }, [devices.data, page, setPage]);
  return <Panel title="Devices" subtitle="Device inventory and spatial references">
    {selected ? <p role="status">Selected device: {selected.hostname} ({selected.device_id})</p> : null}
    <details><summary>Add a device</summary><DeviceForm disabled={!networkId || !canWrite} onRefresh={() => devices.refetch()} onSave={async (input) => { setSelected(await create.mutateAsync(input)); }} /></details>
    <QueryState query={devices} hasData={(d) => d.items.length > 0} emptyTitle="No devices" emptyDescription="Add a device to the selected network.">
      {(data) => <div style={{ display: "grid", gap: "0.5rem" }}>{data.items.map((device) => <div className="device-entry" key={device.device_id}>
        <div style={{ display: "flex", justifyContent: "space-between" }}><strong>{device.hostname}</strong><Badge text={statusLabel(device.status)} tone={deviceStatusTone(device.status)} /></div>
        <div className="device-reference">{device.device_id}</div>
        <div className="device-reference">{device.device_type} · {device.ip_address ?? "IP unknown"} · {device.spatial_ref_id ?? "Location unknown"}</div>
        <Button permission="write:config" tone="ghost" disabled={!canWrite} onClick={() => { setSelected(device); setEditing(device); }}>Edit {device.hostname}</Button>
        <DeleteResource name={device.hostname} disabled={!canWrite} onRefresh={() => devices.refetch()} onDelete={async () => {
          await remove.mutateAsync(device.device_id);
          if (selected?.device_id === device.device_id) setSelected(null);
          if (editing?.device_id === device.device_id) setEditing(null);
        }} />
      </div>)}</div>}
    </QueryState>
    <Pagination label="Devices" page={page} pageSize={20} total={devices.data?.total ?? 0} pending={devices.isFetching} onPageChange={setPage} />
    {editing ? <div><DeviceForm key={editing.device_id} device={editing} disabled={!canWrite} onRefresh={() => devices.refetch()} onSave={async (input) => {
      const changes = changedDeviceFields(editing, input);
      if (Object.keys(changes).length) setSelected(await update.mutateAsync({ deviceId: editing.device_id, changes }));
      setEditing(null);
    }} /><Button tone="ghost" onClick={() => setEditing(null)}>Close device editor</Button></div> : null}
  </Panel>;
}
