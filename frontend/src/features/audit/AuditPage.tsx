import { useState } from "react";
import { useAuditLogs } from "@/features/audit/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { QueryState } from "@/shared/ui/QueryState";
import { AsyncState } from "@/shared/ui/AsyncState";
import { Panel } from "@/shared/ui/Panel";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { formatTimestamp } from "@/shared/lib/format";
import type { AuditScope } from "@/shared/types/audit";
import "./audit.css";

const PAGE_SIZE = 50;
const emptyFilters = { search: "", actorId: "", resourceType: "" };

export function AuditPage() {
  const orgId = useWorkspaceStore((state) => state.organizationId);
  const userId = useAuthStore((state) => state.userId);
  const [scope, setScope] = useState<AuditScope>("org");
  return <AuditTimeline key={`${userId}:${orgId}:${scope}`} orgId={orgId} scope={scope} onScopeChange={setScope} />;
}

function AuditTimeline({ orgId, scope, onScopeChange }: { orgId: string | null; scope: AuditScope; onScopeChange: (scope: AuditScope) => void }) {
  const token = useAuthStore((state) => state.accessToken);
  const [draft, setDraft] = useState(emptyFilters);
  const [filters, setFilters] = useState(emptyFilters);
  const [page, setPage] = useState(1);
  const auditQuery = useAuditLogs(token, orgId, { ...filters, page, pageSize: PAGE_SIZE }, scope);
  const ready = scope === "platform" || Boolean(orgId);

  return <Panel title="Audit Timeline" subtitle="Search the recorded actions and inspect who changed what">
    <div className="audit-timeline">
      <fieldset className="audit-scope">
        <legend>Audit scope</legend>
        <label><input type="radio" name="audit-scope" value="org" checked={scope === "org"} onChange={() => onScopeChange("org")} /> This organization</label>
        <label><input type="radio" name="audit-scope" value="platform" checked={scope === "platform"} onChange={() => onScopeChange("platform")} /> Platform events (sign-in and account activity without an organization)</label>
      </fieldset>
      <p>{scope === "platform"
        ? "Platform scope lists events recorded without an organization. It requires global Admin with an unscoped session."
        : `Organization: ${orgId ?? "None selected"}. Audit records cover this organization.`}</p>
      <form className="audit-filters" onSubmit={(event) => {
        event.preventDefault();
        setFilters({ search: draft.search.trim(), actorId: draft.actorId.trim(), resourceType: draft.resourceType.trim() });
        setPage(1);
      }}>
        <label>Search audit records
          <input value={draft.search} maxLength={200} placeholder="Event, correlation or resource identity"
            onChange={(event) => setDraft({ ...draft, search: event.target.value })} />
        </label>
        <label>Actor ID
          <input value={draft.actorId} placeholder="Exact actor UUID" pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
            title="Enter a UUID, or leave blank for all actors" onChange={(event) => setDraft({ ...draft, actorId: event.target.value })} />
        </label>
        <label>Resource type
          <input value={draft.resourceType} placeholder="Exact resource type" maxLength={100}
            onChange={(event) => setDraft({ ...draft, resourceType: event.target.value })} />
        </label>
        <div className="audit-actions">
          <Button type="submit" disabled={!ready}>Apply filters</Button>
          <Button type="button" tone="ghost" onClick={() => { setDraft(emptyFilters); setFilters(emptyFilters); setPage(1); }}>Clear filters</Button>
          <Button type="button" tone="ghost" disabled={!ready || auditQuery.isFetching} onClick={() => void auditQuery.refetch()}>Refresh audit</Button>
        </div>
      </form>
      {!ready ? <AsyncState title="Select an organization" description="Choose an organization to view its audit records, or switch to platform scope." /> :
        <QueryState query={auditQuery}>
          {(data) => <>
            <nav aria-label="Audit pagination" className="audit-actions">
              <Button tone="ghost" disabled={page <= 1 || auditQuery.isFetching} onClick={() => setPage(page - 1)}>Previous page</Button>
              <span role="status">Page {data.page} of {Math.max(1, Math.ceil(data.total / data.page_size))} · {data.total} matching records</span>
              <Button tone="ghost" disabled={data.page * data.page_size >= data.total || auditQuery.isFetching} onClick={() => setPage(page + 1)}>Next page</Button>
            </nav>
            {!data.items.length ? <AsyncState title="No audit records match these filters" description="Clear or adjust the filters to search again." /> :
              <ol className="audit-records" aria-label="Audit records" key={`${page}:${JSON.stringify(filters)}`}>
                {data.items.map((row) => <li key={row.log_id}>
                  <article>
                    <div className="audit-actions"><strong>{row.event_type}</strong><Badge text={row.resource_type ?? "system"} tone="info" /></div>
                    <div className="mono">Correlation: {row.correlation_id}</div>
                    <time dateTime={row.timestamp}>{formatTimestamp(row.timestamp)}</time>
                    <details>
                      <summary>Audit details: {row.event_type}</summary>
                      <dl>
                        <dt>Actor ID</dt><dd>{row.actor_id ?? "Not recorded"}</dd>
                        <dt>Resource type</dt><dd>{row.resource_type ?? "Not recorded"}</dd>
                        <dt>Resource ID</dt><dd>{row.resource_id ?? "Not recorded"}</dd>
                        <dt>Organization ID</dt><dd>{row.org_id ?? "Not recorded"}</dd>
                        <dt>Log ID</dt><dd>{row.log_id}</dd>
                        <dt>Metadata (including recorded before/after evidence)</dt>
                        <dd>{row.metadata ? <pre>{JSON.stringify(row.metadata, null, 2)}</pre> : "No metadata recorded"}</dd>
                      </dl>
                    </details>
                  </article>
                </li>)}
              </ol>}
          </>}
        </QueryState>}
    </div>
  </Panel>;
}
