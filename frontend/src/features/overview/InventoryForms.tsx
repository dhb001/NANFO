import { useState } from "react";
import { ResourceForm } from "@/features/organizations/ResourceForm";
import type { CreateDeviceInput, Device, Network, UpdateNetworkInput } from "@/shared/types/network";

export function NetworkForm({ network, disabled, onSave, onRefresh }: {
  network?: Network | undefined; disabled?: boolean | undefined; onSave: (input: UpdateNetworkInput & { name: string }) => Promise<void>; onRefresh: () => Promise<unknown>;
}) {
  const [name, setName] = useState(network?.name ?? "");
  const [description, setDescription] = useState(network?.description ?? "");
  const [cidr, setCidr] = useState(network?.cidr ?? "");
  return <ResourceForm label={network ? "Edit network" : "Create network"} submitLabel={network ? "Save network" : "Create Network"} disabled={disabled} onRefresh={onRefresh} onSubmit={async () => {
    const input = { name: name.trim(), description: description.trim() || null, cidr: cidr.trim() || null };
    await onSave(input);
    if (!network) { setName(""); setDescription(""); setCidr(""); }
  }}>
    <label className="context-field">Network name<input required pattern=".*\S.*" maxLength={253} value={name} onChange={(e) => setName(e.target.value)} /></label>
    <label className="context-field">Network description<textarea maxLength={4096} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
    <label className="context-field">CIDR<input placeholder="192.0.2.0/24 or 2001:db8::/32" value={cidr} maxLength={49} onChange={(e) => setCidr(e.target.value)} /></label>
  </ResourceForm>;
}

const deviceFields = [
  ["hostname", "Hostname", 253], ["device_type", "Device type", 64], ["ip_address", "IP address", 45],
  ["vendor", "Vendor", 253], ["model", "Model", 253], ["location_hint", "Location hint", 1024], ["spatial_ref_id", "Spatial reference", 512],
] as const;

export function DeviceForm({ device, disabled, onSave, onRefresh }: {
  device?: Device | undefined; disabled?: boolean | undefined; onSave: (input: CreateDeviceInput) => Promise<void>; onRefresh: () => Promise<unknown>;
}) {
  const [draft, setDraft] = useState(() => Object.fromEntries(deviceFields.map(([key]) => [key, device?.[key] ?? ""])) as Record<typeof deviceFields[number][0], string>);
  return <ResourceForm label={device ? "Edit device" : "Create device"} submitLabel={device ? "Save device" : "Add Device"} disabled={disabled} onRefresh={onRefresh} onSubmit={async () => {
    const input: CreateDeviceInput = { hostname: draft.hostname.trim(), device_type: draft.device_type.trim() };
    for (const [key] of deviceFields) {
      if (key !== "hostname" && key !== "device_type") input[key] = draft[key].trim() || null;
    }
    await onSave(input);
    if (!device) setDraft(Object.fromEntries(deviceFields.map(([key]) => [key, ""])) as typeof draft);
  }}>
    {deviceFields.map(([key, label, maxLength]) => <label key={key} className="context-field">{label}
      <input required={key === "hostname" || key === "device_type"} pattern={key === "hostname" || key === "device_type" ? ".*\\S.*" : undefined} maxLength={maxLength} value={draft[key]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
    </label>)}
    <p>Leave optional fields empty for unknown values. Clearing an optional field removes its value.</p>
  </ResourceForm>;
}
