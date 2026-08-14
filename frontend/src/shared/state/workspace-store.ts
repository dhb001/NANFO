import { create } from "zustand";

interface WorkspaceSelection {
  organizationId: string | null;
  workspaceId: string | null;
  networkId: string | null;
  setOrganizationId: (organizationId: string | null) => void;
  setWorkspaceId: (workspaceId: string | null) => void;
  setNetworkId: (networkId: string | null) => void;
}

const ORGANIZATION_STORAGE_KEY = "nanfo.workspace.organizationId";
const WORKSPACE_STORAGE_KEY = "nanfo.workspace.workspaceId";
const NETWORK_STORAGE_KEY = "nanfo.workspace.networkId";

function readWorkspaceSelection() {
  if (typeof window === "undefined") {
    return {
      organizationId: null,
      workspaceId: null,
      networkId: null,
    };
  }

  return {
    organizationId: window.localStorage.getItem(ORGANIZATION_STORAGE_KEY),
    workspaceId: window.localStorage.getItem(WORKSPACE_STORAGE_KEY),
    networkId: window.localStorage.getItem(NETWORK_STORAGE_KEY),
  };
}

function persistWorkspaceSelection(selection: {
  organizationId: string | null;
  workspaceId: string | null;
  networkId: string | null;
}) {
  if (typeof window === "undefined") {
    return;
  }

  if (selection.organizationId) {
    window.localStorage.setItem(ORGANIZATION_STORAGE_KEY, selection.organizationId);
  } else {
    window.localStorage.removeItem(ORGANIZATION_STORAGE_KEY);
  }

  if (selection.workspaceId) {
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, selection.workspaceId);
  } else {
    window.localStorage.removeItem(WORKSPACE_STORAGE_KEY);
  }

  if (selection.networkId) {
    window.localStorage.setItem(NETWORK_STORAGE_KEY, selection.networkId);
  } else {
    window.localStorage.removeItem(NETWORK_STORAGE_KEY);
  }
}

const initialSelection = readWorkspaceSelection();

export const useWorkspaceStore = create<WorkspaceSelection>((set) => ({
  organizationId: initialSelection.organizationId,
  workspaceId: initialSelection.workspaceId,
  networkId: initialSelection.networkId,
  setOrganizationId: (organizationId) =>
    set(() => {
      const next = {
        organizationId,
        workspaceId: null,
        networkId: null,
      };
      persistWorkspaceSelection(next);
      return next;
    }),
  setWorkspaceId: (workspaceId) =>
    set((state) => {
      const next = {
        organizationId: state.organizationId,
        workspaceId,
        networkId: null,
      };
      persistWorkspaceSelection(next);
      return next;
    }),
  setNetworkId: (networkId) =>
    set((state) => {
      const next = {
        organizationId: state.organizationId,
        workspaceId: state.workspaceId,
        networkId,
      };
      persistWorkspaceSelection(next);
      return next;
    }),
}));
