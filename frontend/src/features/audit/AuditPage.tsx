import { useMemo, useState } from "react";
import { useAuditLogs } from "@/features/audit/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { QueryState } from "@/shared/ui/QueryState";
import { Panel } from "@/shared/ui/Panel";
import { Badge } from "@/shared/ui/Badge";
import { formatTimestamp } from "@/shared/lib/format";
import { useVirtualizer } from "@tanstack/react-virtual";

export function AuditPage() {
  const token = useAuthStore((state) => state.accessToken);
  const orgId = useWorkspaceStore((state) => state.organizationId);
  const auditQuery = useAuditLogs(token, orgId);

  const [filter, setFilter] = useState("");

  const rows = useMemo(() => {
    const items = auditQuery.data?.items ?? [];
    if (!filter.trim()) {
      return items;
    }
    const needle = filter.toLowerCase();
    return items.filter((item) => {
      return (
        item.event_type.toLowerCase().includes(needle) ||
        (item.resource_type ?? "").toLowerCase().includes(needle) ||
        item.correlation_id.toLowerCase().includes(needle)
      );
    });
  }, [auditQuery.data?.items, filter]);

  const parentRef = useState(() => ({ current: null as HTMLDivElement | null }))[0];

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 54,
    overscan: 12,
  });

  return (
    <Panel
      title="Audit Timeline"
      subtitle="Dense log review with virtualized rendering and keyboard-first filtering"
      action={
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter by event, resource, correlation id"
          style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.52rem", minWidth: 320 }}
        />
      }
    >
      <QueryState query={auditQuery} hasData={(data) => data.items.length > 0} emptyTitle="No audit logs">
        {() => (
          <div
            ref={(element) => {
              parentRef.current = element;
            }}
            style={{
              height: 640,
              overflow: "auto",
              border: "1px solid var(--line-soft)",
              borderRadius: "10px",
              position: "relative",
            }}
          >
            <div
              style={{
                height: rowVirtualizer.getTotalSize(),
                width: "100%",
                position: "relative",
              }}
            >
              {rowVirtualizer.getVirtualItems().map((item) => {
                const row = rows[item.index];
                return (
                  <div
                    key={row.log_id}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateY(${item.start}px)`,
                      padding: "0.5rem 0.55rem",
                      borderBottom: "1px solid var(--line-soft)",
                      display: "grid",
                      gap: "0.15rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <strong>{row.event_type}</strong>
                      <Badge text={row.resource_type ?? "system"} tone="info" />
                    </div>
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                      corr {row.correlation_id}
                    </div>
                    <div style={{ color: "var(--ink-3)", fontSize: "0.78rem" }}>{formatTimestamp(row.timestamp)}</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </QueryState>
    </Panel>
  );
}
