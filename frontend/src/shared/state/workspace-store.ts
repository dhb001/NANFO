import { create } from "zustand";

interface WorkspaceSelection {
  organizationId: string | null;
  workspaceId: string | null;
  networkId: string | null;
  setOrganizationId: (organizationId: string | null) => void;
  setWorkspaceId: (workspaceId: string | null) => void;
  setNetworkId: (networkId: string | null) => void;
  reset: () => void;
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
    organizationId: window.sessionStorage.getItem(ORGANIZATION_STORAGE_KEY),
    workspaceId: window.sessionStorage.getItem(WORKSPACE_STORAGE_KEY),
    networkId: window.sessionStorage.getItem(NETWORK_STORAGE_KEY),
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
    window.sessionStorage.setItem(ORGANIZATION_STORAGE_KEY, selection.organizationId);
  } else {
    window.sessionStorage.removeItem(ORGANIZATION_STORAGE_KEY);
  }

  if (selection.workspaceId) {
    window.sessionStorage.setItem(WORKSPACE_STORAGE_KEY, selection.workspaceId);
  } else {
    window.sessionStorage.removeItem(WORKSPACE_STORAGE_KEY);
  }

  if (selection.networkId) {
    window.sessionStorage.setItem(NETWORK_STORAGE_KEY, selection.networkId);
  } else {
    window.sessionStorage.removeItem(NETWORK_STORAGE_KEY);
  }
}

// Discard legacy cross-tab selections along with shared authentication persistence.
try {
  for (const key of [ORGANIZATION_STORAGE_KEY, WORKSPACE_STORAGE_KEY, NETWORK_STORAGE_KEY]) {
    window.localStorage.removeItem(key);
  }
} catch {
  // Selection is tab-local even when shared storage is unavailable.
}
const initialSelection = readWorkspaceSelection();

export const useWorkspaceStore = create<WorkspaceSelection>((set) => ({
  reset: () => {
    const next = { organizationId: null, workspaceId: null, networkId: null };
    persistWorkspaceSelection(next);
    set(next);
  },
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
