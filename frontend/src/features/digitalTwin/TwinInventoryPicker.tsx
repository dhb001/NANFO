import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listDevices } from "@/features/networks/api";
import { Button } from "@/shared/ui/Button";
import { toErrorMessage } from "@/shared/lib/errors";

/** Explicit pages keep selectors complete without loading an unbounded inventory. */
export function TwinInventoryPicker({ token, networkId, selected, onToggle, disabled = false }: {
  token: string | null; networkId: string | null; selected: string[];
  onToggle: (id: string) => void; disabled?: boolean;
}) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["twin-inventory", token, networkId, page],
    queryFn: async () => (await listDevices(token!, networkId!, page, 20)).data,
    enabled: Boolean(token && networkId), retry: false,
  });
  return <fieldset disabled={disabled}><legend>Network inventory</legend>
    {query.isFetching ? <p role="status">Loading inventory…</p> : null}
    {query.isError ? <p role="alert">{toErrorMessage(query.error)}</p> : null}
    <Button type="button" tone="ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>Reload inventory</Button>
    <p>Inventory page {page} · {query.data?.total ?? "unknown"} total · {selected.length} selected across pages</p>
    {query.data?.items.length === 0 ? <p>No devices on this page.</p> : null}
    {query.data?.items.map((device) => <label key={device.device_id} style={{ display: "block" }}>
      <input type="checkbox" checked={selected.includes(device.device_id)} onChange={() => onToggle(device.device_id)} />
      {device.hostname} · {device.device_type} · {device.device_id}
    </label>)}
    <Button type="button" tone="ghost" disabled={page === 1 || query.isFetching} onClick={() => setPage(page - 1)}>Previous inventory page</Button>
    <Button type="button" tone="ghost" disabled={!query.data || page * 20 >= query.data.total || query.isFetching} onClick={() => setPage(page + 1)}>Next inventory page</Button>
  </fieldset>;
}
