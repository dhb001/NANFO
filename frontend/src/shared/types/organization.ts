import type { Schema } from "@/shared/types/contracts";

/** Organization roles (backend `OrgRole`, generated from `OrgResponse.caller_role`). */
export type OrgRole = NonNullable<Schema<"OrgResponse">["caller_role"]>;

export interface Organization {
  org_id: string;
  name: string;
  slug: string;
  created_at: string;
  /** The caller's own membership role (ADR-028 C6); absent from older backends. */
  caller_role?: OrgRole | null;
}

// Organization, workspace and member lists return `{items, total}` only;
// the requested page is the caller's own state.
export interface OrganizationList {
  items: Organization[];
  total: number;
}

export interface Workspace {
  workspace_id: string;
  org_id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface WorkspaceList {
  items: Workspace[];
  total: number;
}

export interface OrgMember {
  org_id: string;
  user_id: string;
  org_role: OrgRole | (string & {});
  created_at: string;
}

export interface OrgMemberList {
  items: OrgMember[];
  total: number;
}
