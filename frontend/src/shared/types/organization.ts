export interface Organization {
  org_id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface OrganizationList {
  items: Organization[];
  total: number;
  page?: number;
  page_size?: number;
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
  page?: number;
  page_size?: number;
}

export interface OrgMember {
  org_id: string;
  user_id: string;
  org_role: string;
  created_at: string;
}

export interface OrgMemberList {
  items: OrgMember[];
  total: number;
  page?: number;
  page_size?: number;
}
